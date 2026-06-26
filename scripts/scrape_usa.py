"""Scrape US data centers from datacentermap.com.

Phase 1 – URL discovery: try sitemap, fall back to BFS crawl.
Phase 2 – Detail scrape: parse __NEXT_DATA__, follow website redirect.

Usage:
    python scripts/scrape_usa.py [--sample 10] [--delay 1.0] [--output output/usa.jsonl]
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
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(url: str, delay: float = 1.0, max_retries: int = 4) -> str:
    """Fetch URL with exponential back-off on 429."""
    for attempt in range(max_retries):
        pause = delay if attempt == 0 else delay * (3 ** attempt)
        time.sleep(pause)
        if attempt > 0:
            print(f"  [retry {attempt}] waiting {pause:.0f}s for {url}", file=sys.stderr)
        try:
            rq = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(rq, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                continue
            raise
    raise RuntimeError(f"Failed after {max_retries} attempts: {url}")


def _get_redirect(url: str, delay: float = 1.0) -> str | None:
    """Return the Location header from a redirect without following it."""
    time.sleep(delay)

    class _NoFollow(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            return None

    opener = urllib.request.build_opener(_NoFollow())
    try:
        opener.open(urllib.request.Request(url, headers=_HEADERS), timeout=10)
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            loc = exc.headers.get("Location")
            # Skip same-domain redirects (not an external website)
            if loc and "datacentermap.com" not in loc:
                return loc
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# __NEXT_DATA__ parser
# ---------------------------------------------------------------------------

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
# Phase 1 – URL discovery
# ---------------------------------------------------------------------------

def _extract_dc_urls_from_text(text: str) -> list[str]:
    """Pull out https://…/usa/{state}/{city}/{slug}/ URLs from any text."""
    return re.findall(
        r"https?://(?:www\.)?datacentermap\.com"
        r"/usa/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/",
        text,
    )


def _discover_from_sitemap(delay: float) -> list[str]:
    print("  Trying sitemap …", file=sys.stderr)
    try:
        xml = _get(f"{BASE_URL}/sitemap.xml", delay=delay)
    except Exception as exc:
        print(f"  sitemap.xml failed: {exc}", file=sys.stderr)
        return []

    # Sitemap index? Fetch each sub-sitemap.
    sub_maps = re.findall(r"<loc>(https?://[^<]+sitemap[^<]*)</loc>", xml)
    if sub_maps:
        all_urls: list[str] = []
        for sm in sub_maps:
            try:
                sub_xml = _get(sm, delay=delay)
                all_urls.extend(_extract_dc_urls_from_text(sub_xml))
            except Exception:
                pass
        return all_urls

    return _extract_dc_urls_from_text(xml)


def _discover_from_crawl(delay: float) -> list[str]:
    """BFS: /usa/ → state pages → city pages → datacenter URLs."""
    print("  Crawling /usa/ …", file=sys.stderr)
    dc_urls: list[str] = []

    usa_html = _get(f"{BASE_URL}/usa/", delay=delay)

    # State slugs: href="/usa/{state}/"
    state_slugs = list(dict.fromkeys(
        re.findall(r'href="/usa/([A-Za-z0-9_-]+)/"', usa_html)
    ))
    print(f"  {len(state_slugs)} states found", file=sys.stderr)

    for state in state_slugs:
        try:
            state_html = _get(f"{BASE_URL}/usa/{state}/", delay=delay)
        except Exception as exc:
            print(f"  skip state {state}: {exc}", file=sys.stderr)
            continue

        # City slugs: href="/usa/{state}/{city}/"
        cities = list(dict.fromkeys(
            re.findall(rf'href="/usa/{state}/([A-Za-z0-9_-]+)/"', state_html)
        ))

        for city in cities:
            try:
                city_html = _get(f"{BASE_URL}/usa/{state}/{city}/", delay=delay)
            except Exception as exc:
                print(f"  skip city {state}/{city}: {exc}", file=sys.stderr)
                continue

            # DC slugs: href="/usa/{state}/{city}/{slug}/"
            slugs = list(dict.fromkeys(
                re.findall(
                    rf'href="/usa/{state}/{city}/([A-Za-z0-9_-]+)/"',
                    city_html,
                )
            ))
            for slug in slugs:
                dc_urls.append(f"{BASE_URL}/usa/{state}/{city}/{slug}/")

    return dc_urls


def discover_usa_urls(delay: float) -> list[str]:
    """Return de-duplicated list of all US datacenter detail-page URLs."""
    print("Phase 1: Discovering US datacenter URLs …", file=sys.stderr)
    urls = _discover_from_sitemap(delay)
    if urls:
        print(f"  sitemap gave {len(urls)} US DC URLs", file=sys.stderr)
    else:
        print("  sitemap empty/failed – falling back to crawl", file=sys.stderr)
        urls = _discover_from_crawl(delay)
        print(f"  crawl gave {len(urls)} US DC URLs", file=sys.stderr)
    return list(dict.fromkeys(urls))


# ---------------------------------------------------------------------------
# Phase 2 – Detail scrape
# ---------------------------------------------------------------------------

def scrape_dc(url: str, delay: float) -> dict:
    """Fetch one datacenter page and return a structured record."""
    html = _get(url, delay=delay)
    data = _parse_next_data(html)

    dc: dict = {}
    if data:
        dc = (
            data.get("props", {})
                .get("pageProps", {})
                .get("dc", {})
        )

    link = dc.get("link", "")
    statelink = dc.get("statelink", "")
    countrylink = dc.get("countrylink", "usa")
    marketlink = dc.get("marketlink", "")

    # Canonical detail URL rebuilt from parsed slugs; fall back to input url.
    if link and statelink and marketlink:
        detail_url = f"{BASE_URL}/{countrylink}/{statelink}/{marketlink}/{link}/"
    else:
        detail_url = url

    # External website via redirect (only if the page exposes the visit link)
    external_website: str | None = None
    if link and f"/visit/datacenter/{link}/" in html:
        external_website = _get_redirect(
            f"{BASE_URL}/visit/datacenter/{link}/", delay=delay
        )

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
            "country": "United States",
            "state": dc.get("state"),
            "city": dc.get("city"),
            "address": dc.get("address"),
            "postal": dc.get("postal"),
        },
        "links": {"external_website": external_website},
        "location": {
            "latitude": dc.get("latitude"),
            "longitude": dc.get("longitude"),
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape US data centers from datacentermap.com"
    )
    parser.add_argument(
        "--output", default="output/usa.jsonl",
        help="Output JSONL file (default: output/usa.jsonl)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds between requests (default: 1.0)",
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Stop after N records for testing (0 = scrape all)",
    )
    args = parser.parse_args()

    out_path = pathlib.Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Resume: load already-scraped URLs
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

    all_urls = discover_usa_urls(args.delay)
    todo = [u for u in all_urls if u not in seen]
    print(
        f"Phase 2: {len(todo)} to scrape "
        f"({len(seen)} already done, {len(all_urls)} total)",
        file=sys.stderr,
    )

    count = 0
    with out_path.open("a", encoding="utf-8") as fh:
        try:
            from tqdm import tqdm  # type: ignore[import]
            iterator: Iterator[str] = tqdm(todo, desc="scraping", unit="dc")
        except ImportError:
            iterator = iter(todo)

        for url in iterator:
            if args.sample and count >= args.sample:
                break
            try:
                record = scrape_dc(url, args.delay)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                count += 1
            except Exception as exc:
                print(f"  ERROR {url}: {exc}", file=sys.stderr)

    print(f"Done: {count} new records written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
