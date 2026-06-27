"""Scrape data centers from datacentermap.com.

Run with no arguments to be prompted for geography interactively:

    python scripts/scrape.py

Or pass geography directly as flags:

    python scripts/scrape.py --state Ohio
    python scripts/scrape.py --state Ohio --city Cleveland
    python scripts/scrape.py --country Germany
    python scripts/scrape.py --country USA --state "New York" --city "New York City"

Output is saved to output/<country>.jsonl, output/<country>_<state>.jsonl, etc.
Use --output to override the path.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Iterator

BASE_URL = "https://www.datacentermap.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _to_slug(name: str) -> str:
    """Convert a human-readable name to a datacentermap.com URL slug.

    Examples:  'Ohio' → 'ohio'
               'New York' → 'new-york'
               'Los Angeles' → 'los-angeles'
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def _to_label(slug: str) -> str:
    """'new-york' → 'New York'  (for display only)."""
    return slug.replace("-", " ").title()


def _fmt_elapsed(seconds: float) -> str:
    """Format elapsed seconds as '2h 04m 30s', '4m 30s', or '30s'."""
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _log(msg: str, bar: object = None) -> None:
    """Print to stderr; route through tqdm.write when a bar is active."""
    try:
        bar.write(msg)  # type: ignore[union-attr]
    except Exception:
        print(msg, file=sys.stderr)


def _get(url: str, delay: float = 1.0, max_retries: int = 3, bar: object = None) -> str:
    """Fetch URL with exponential back-off on 429/5xx and network errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        pause = delay if attempt == 0 else delay * (2 ** attempt)
        time.sleep(pause)
        if attempt > 0:
            _log(f"  [retry {attempt}] {last_exc} → {url}", bar)
        try:
            rq = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(rq, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                last_exc = exc
                continue
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"Failed after {max_retries} attempts: {url}")


def _parse_next_data(html: str) -> dict | None:
    idx = html.find("__NEXT_DATA__")
    if idx == -1:
        return None
    try:
        start = html.index("{", idx)
        end = html.find("</script>", start)
        return json.loads(html[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# URL discovery — scoped to the requested geography
# ---------------------------------------------------------------------------

def _urls_in_city(country: str, state: str, city: str, delay: float) -> list[str]:
    """All DC detail-page URLs under /{country}/{state}/{city}/."""
    page_url = f"{BASE_URL}/{country}/{state}/{city}/"
    try:
        html = _get(page_url, delay=delay)
    except Exception as exc:
        print(f"  skip {country}/{state}/{city}: {exc}", file=sys.stderr)
        return []
    slugs = list(dict.fromkeys(
        re.findall(rf'href="/{country}/{state}/{city}/([A-Za-z0-9_-]+)/"', html)
    ))
    return [f"{BASE_URL}/{country}/{state}/{city}/{s}/" for s in slugs]


def _urls_in_state(country: str, state: str, delay: float) -> list[str]:
    """All DC detail-page URLs under /{country}/{state}/ (crawls every city)."""
    page_url = f"{BASE_URL}/{country}/{state}/"
    try:
        html = _get(page_url, delay=delay)
    except Exception as exc:
        print(f"  skip {country}/{state}: {exc}", file=sys.stderr)
        return []
    cities = list(dict.fromkeys(
        re.findall(rf'href="/{country}/{state}/([A-Za-z0-9_-]+)/"', html)
    ))
    print(f"  {len(cities)} cities found in {_to_label(state)}", file=sys.stderr)
    all_urls: list[str] = []
    for city in cities:
        all_urls.extend(_urls_in_city(country, state, city, delay))
    return all_urls


def _urls_from_sitemap(country: str, delay: float) -> list[str]:
    """Pull all /{country}/{state}/{city}/{slug}/ URLs from the sitemap."""
    print("  Checking sitemap …", file=sys.stderr)
    try:
        xml = _get(f"{BASE_URL}/sitemap.xml", delay=delay)
    except Exception as exc:
        print(f"  sitemap.xml failed: {exc}", file=sys.stderr)
        return []

    # Sitemap index? Expand sub-sitemaps first.
    sub_maps = re.findall(r"<loc>(https?://[^<]+sitemap[^<]*)</loc>", xml)
    texts = [xml] if not sub_maps else []
    for sm in sub_maps:
        try:
            texts.append(_get(sm, delay=delay))
        except Exception:
            pass

    pattern = (
        rf"https?://(?:www\.)?datacentermap\.com"
        rf"/{country}/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/"
    )
    urls: list[str] = []
    for text in texts:
        urls.extend(re.findall(pattern, text))
    return list(dict.fromkeys(urls))


def _urls_from_country_crawl(country: str, delay: float) -> list[str]:
    """BFS crawl: /{country}/ → state pages → city pages → DC URLs."""
    print("  Crawling country page …", file=sys.stderr)
    try:
        html = _get(f"{BASE_URL}/{country}/", delay=delay)
    except Exception as exc:
        print(f"  country page failed: {exc}", file=sys.stderr)
        return []
    states = list(dict.fromkeys(
        re.findall(rf'href="/{country}/([A-Za-z0-9_-]+)/"', html)
    ))
    print(f"  {len(states)} states/regions found", file=sys.stderr)
    all_urls: list[str] = []
    for state in states:
        all_urls.extend(_urls_in_state(country, state, delay))
    return all_urls


def discover_urls(
    country: str,
    state: str | None,
    city: str | None,
    delay: float,
) -> list[str]:
    """Return de-duplicated DC detail-page URLs for the requested geography."""
    if state and city:
        return _urls_in_city(country, state, city, delay)
    if state:
        return _urls_in_state(country, state, delay)
    # Full country: sitemap is fastest
    urls = _urls_from_sitemap(country, delay)
    if urls:
        print(f"  Sitemap: {len(urls)} URLs found", file=sys.stderr)
        return urls
    print("  Sitemap empty/failed — falling back to crawl", file=sys.stderr)
    return _urls_from_country_crawl(country, delay)


# ---------------------------------------------------------------------------
# Page scraping
# ---------------------------------------------------------------------------

def scrape_dc(url: str, delay: float, bar: object = None) -> dict:
    """Fetch one datacenter detail page and return a structured record."""
    html = _get(url, delay=delay, bar=bar)
    data = _parse_next_data(html)

    dc: dict = {}
    if data:
        dc = data.get("props", {}).get("pageProps", {}).get("dc", {}) or {}

    if not dc.get("name"):
        raise ValueError("no dc data in __NEXT_DATA__ (possible bot-check or empty page)")

    link = dc.get("link", "")
    statelink = dc.get("statelink", "")
    countrylink = dc.get("countrylink", "usa")
    marketlink = dc.get("marketlink", "")

    if link and statelink and marketlink:
        detail_url = f"{BASE_URL}/{countrylink}/{statelink}/{marketlink}/{link}/"
    else:
        detail_url = url

    operator: str | None = None
    if isinstance(dc.get("companies"), dict):
        operator = dc["companies"].get("name")

    return {
        "source": {"detail_url": detail_url},
        "identity": {
            "name": dc.get("name"),
            "operator_name": operator,
        },
        "address": {
            "country": dc.get("country"),
            "state": dc.get("state"),
            "city": dc.get("city"),
            "address": dc.get("address"),
            "postal": dc.get("postal"),
        },
        "location": {
            "latitude": dc.get("latitude"),
            "longitude": dc.get("longitude"),
        },
    }


# ---------------------------------------------------------------------------
# Interactive geography prompts
# ---------------------------------------------------------------------------

def _prompt_geography() -> tuple[str, str | None, str | None]:
    """Ask the user for country / state / city interactively."""
    print()
    print("DataCenterMap Scraper")
    print("=" * 40)
    print("Press Enter to accept the default shown in [brackets].")
    print()

    country_raw = input("Country [USA]: ").strip() or "USA"
    state_raw   = input("State   [all]: ").strip()
    city_raw    = input("City    [all]: ").strip() if state_raw else ""

    country = _to_slug(country_raw)
    state   = _to_slug(state_raw) if state_raw else None
    city    = _to_slug(city_raw)  if city_raw  else None
    return country, state, city


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def _default_output(country: str, state: str | None, city: str | None) -> pathlib.Path:
    parts = [country]
    if state:
        parts.append(state)
    if city:
        parts.append(city)
    return pathlib.Path("output") / ("_".join(parts) + ".jsonl")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape data centers from datacentermap.com.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/scrape.py                         # interactive\n"
            "  python scripts/scrape.py --state Ohio\n"
            "  python scripts/scrape.py --state Ohio --city Cleveland\n"
            "  python scripts/scrape.py --country Germany\n"
        ),
    )
    parser.add_argument("--country", default=None, metavar="NAME",
                        help="Country name or slug (default: USA)")
    parser.add_argument("--state",   default=None, metavar="NAME",
                        help="State or region (optional)")
    parser.add_argument("--city",    default=None, metavar="NAME",
                        help="City (optional; requires --state)")
    parser.add_argument("--output",  default=None, metavar="PATH",
                        help="Override output JSONL file path")
    parser.add_argument("--delay",   type=float, default=1.0,
                        help="Seconds between requests (default: 1.0)")
    parser.add_argument("--sample",  type=int, default=0,
                        help="Stop after N records, for testing (0 = all)")
    args = parser.parse_args()

    # Determine geography
    if args.country or args.state or args.city:
        country = _to_slug(args.country or "usa")
        state   = _to_slug(args.state) if args.state else None
        city    = _to_slug(args.city)  if args.city  else None
    else:
        country, state, city = _prompt_geography()

    out_path = pathlib.Path(args.output) if args.output else _default_output(country, state, city)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Print scope summary
    scope_parts = [_to_label(country)]
    if state:
        scope_parts.append(_to_label(state))
    if city:
        scope_parts.append(_to_label(city))
    print(f"\nScope:  {' › '.join(scope_parts)}", file=sys.stderr)
    print(f"Output: {out_path}", file=sys.stderr)

    # Load already-scraped URLs (resume support)
    seen: set[str] = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    seen.add(json.loads(line)["source"]["detail_url"])
                except Exception:
                    pass
        if seen:
            print(f"Resuming: {len(seen)} already scraped", file=sys.stderr)

    print("\nPhase 1: Discovering datacenter URLs …", file=sys.stderr)
    all_urls = discover_urls(country, state, city, args.delay)

    if not all_urls:
        print(
            "\n  No URLs found. Check your spelling — the scraper uses the same"
            "\n  slugs as datacentermap.com (e.g. 'New York' → new-york).",
            file=sys.stderr,
        )
        sys.exit(1)

    todo = [u for u in all_urls if u not in seen]
    grand_total = len(seen) + len(todo)
    print(
        f"Phase 2: Scraping {len(todo)} datacenters"
        f" ({len(seen)} already done, {grand_total} total)\n",
        file=sys.stderr,
    )

    count = 0
    bar = None
    start_time = time.time()
    with out_path.open("a", encoding="utf-8") as fh:
        try:
            from tqdm import tqdm  # type: ignore[import]
            bar = tqdm(
                todo,
                desc=f"Scraped {len(seen)}/{grand_total}",
                unit="dc",
                dynamic_ncols=True,
                initial=len(seen),
                total=grand_total,
            )
            iterator: Iterator[str] = iter(bar)
        except ImportError:
            bar = None
            iterator = iter(todo)

        for url in iterator:
            if args.sample and count >= args.sample:
                break
            try:
                record = scrape_dc(url, args.delay, bar=bar)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                count += 1
                scraped_total = len(seen) + count
                elapsed = _fmt_elapsed(time.time() - start_time)
                if bar is not None:
                    bar.set_description(f"Scraped {scraped_total}/{grand_total}")
                    bar.set_postfix(elapsed=elapsed)
                elif count % 50 == 0 or count == len(todo):
                    pct = scraped_total / grand_total * 100
                    print(f"  [{scraped_total}/{grand_total}] {pct:.1f}% | {elapsed}", file=sys.stderr)
            except Exception as exc:
                _log(f"  ERROR {url}: {exc}", bar)

    print(f"\nDone: {count} new records written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
