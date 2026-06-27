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
import random
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Iterator

BASE_URL = "https://www.datacentermap.com"


# ---------------------------------------------------------------------------
# Context and configuration
# ---------------------------------------------------------------------------

class _RetryableError(Exception):
    """A transient failure (429/5xx or network error) that warrants a back-off retry."""


class ScrapeContext:
    """Owns the HTTP session, proxy pool, and configuration for scraping.

    All network access goes through ``fetch``; callers never touch the
    underlying curl_cffi session directly.
    """

    def __init__(
        self,
        delay: float,
        cffi_requests=None,
        proxies: list[str] | None = None,
    ):
        self.delay = delay
        self._cffi_requests = cffi_requests
        self._cffi_session = None
        self.proxies = proxies or []

        if self.use_curl:
            assert self._cffi_requests is not None
            self._cffi_session = self._cffi_requests.Session(impersonate="chrome120")

    @property
    def use_curl(self) -> bool:
        """True when curl_cffi is available (single source of truth)."""
        return self._cffi_requests is not None

    def pick_proxy(self) -> dict | None:
        """Random proxy from the pool as a curl_cffi/requests-style mapping."""
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        return {"http": proxy, "https": proxy}

    def refresh_session(self) -> None:
        """Replace the curl_cffi session to clear cookies and connection state."""
        if self.use_curl:
            assert self._cffi_requests is not None
            self._cffi_session = self._cffi_requests.Session(impersonate="chrome120")

    def fetch(self, url: str) -> str:
        """Perform one HTTP GET and return the body text.

        Raises ``_RetryableError`` for 429/5xx and network failures (the caller
        retries those with back-off); other HTTP errors propagate as fatal.
        """
        proxies = self.pick_proxy()
        if self.use_curl:
            referer = url.rstrip("/").rsplit("/", 1)[0] + "/"
            kwargs: dict = {"headers": {"Referer": referer}, "timeout": 20}
            if proxies:
                kwargs["proxies"] = proxies
            assert self._cffi_session is not None
            try:
                resp = self._cffi_session.get(url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise _RetryableError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.text
            except _RetryableError:
                raise
            except Exception as exc:  # curl_cffi network/TLS errors are transient
                raise _RetryableError(str(exc)) from exc

        rq = urllib.request.Request(url, headers=_HEADERS)
        opener = urllib.request.urlopen
        if proxies:
            handler = urllib.request.ProxyHandler(proxies)
            opener = urllib.request.build_opener(handler).open
        try:
            with opener(rq, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                raise _RetryableError(str(exc)) from exc
            raise
        except urllib.error.URLError as exc:
            raise _RetryableError(str(exc)) from exc


# ---------------------------------------------------------------------------
# HTTP utilities
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _normalize_proxy(line: str) -> str | None:
    """Turn a proxy line into a full proxy URL curl_cffi/urllib understands.

    Accepts the formats Webshare hands out:
        host:port:username:password   -> http://username:password@host:port
        host:port                     -> http://host:port
        http(s)://...                 -> used as-is
        socks5://...                  -> used as-is
    Returns None for blank lines / comments.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = line.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{user}:{pwd}@{host}:{port}"
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    return line  # let the HTTP client reject anything malformed


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


def _get(
    url: str,
    ctx: ScrapeContext,
    bar: object = None,
    max_retries: int = 3,
) -> str:
    """Fetch URL with exponential back-off on 429/5xx and network errors."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        pause = ctx.delay if attempt == 0 else ctx.delay * (2 ** attempt)
        pause *= random.uniform(0.8, 1.2)  # jitter so timing isn't robotic
        time.sleep(pause)
        if attempt > 0:
            _log(f"  [retry {attempt}] {last_exc} -> {url}", bar)
        try:
            return ctx.fetch(url)
        except _RetryableError as exc:
            last_exc = exc
            continue
    raise RuntimeError(f"Failed after {max_retries} attempts: {url}")


def _parse_next_data(html: str) -> dict | None:
    """Extract the __NEXT_DATA__ JSON payload from HTML."""
    idx = html.find("__NEXT_DATA__")
    if idx == -1:
        return None
    try:
        start = html.index("{", idx)
        end = html.find("</script>", start)
        return json.loads(html[start:end])
    except (ValueError, json.JSONDecodeError):
        return None


def _extract_dc_payload(html: str) -> dict | None:
    """Extract the dc object from __NEXT_DATA__ JSON payload."""
    data = _parse_next_data(html)
    if not data:
        return None
    return data.get("props", {}).get("pageProps", {}).get("dc") or None


def _normalize_dc_record(dc: dict, fallback_url: str) -> dict:
    """Convert raw dc payload into the final JSONL record format."""
    link = dc.get("link", "")
    statelink = dc.get("statelink", "")
    countrylink = dc.get("countrylink", "usa")
    marketlink = dc.get("marketlink", "")

    if link and statelink and marketlink:
        detail_url = f"{BASE_URL}/{countrylink}/{statelink}/{marketlink}/{link}/"
    else:
        detail_url = fallback_url

    operator = None
    if isinstance(dc.get("companies"), dict):
        operator = dc["companies"].get("name")

    archived = dc.get("status") == 2

    return {
        "source": {"detail_url": detail_url},
        "identity": {
            "name": dc.get("name"),
            "operator_name": operator,
            "stage": dc.get("stage"),
            "archived": archived,
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
# URL discovery utilities
# ---------------------------------------------------------------------------

def _to_slug(name: str) -> str:
    """Convert a human-readable name to a datacentermap.com URL slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def _to_label(slug: str) -> str:
    """'new-york' -> 'New York'  (for display only)."""
    return slug.replace("-", " ").title()


def _urls_in_city(
    country: str, state: str, city: str, ctx: ScrapeContext
) -> list[str]:
    """All DC detail-page URLs under /{country}/{state}/{city}/."""
    page_url = f"{BASE_URL}/{country}/{state}/{city}/"
    try:
        html = _get(page_url, ctx=ctx)
    except Exception as exc:
        print(f"  skip {country}/{state}/{city}: {exc}", file=sys.stderr)
        return []
    slugs = list(dict.fromkeys(
        re.findall(
            rf'href="/{country}/{state}/{city}/([A-Za-z0-9_-]+)/"', html
        )
    ))
    return [f"{BASE_URL}/{country}/{state}/{city}/{s}/" for s in slugs]


def _urls_in_state(country: str, state: str, ctx: ScrapeContext) -> list[str]:
    """All DC detail-page URLs under /{country}/{state}/ (crawls every city)."""
    page_url = f"{BASE_URL}/{country}/{state}/"
    try:
        html = _get(page_url, ctx=ctx)
    except Exception as exc:
        print(f"  skip {country}/{state}: {exc}", file=sys.stderr)
        return []
    cities = list(dict.fromkeys(
        re.findall(rf'href="/{country}/{state}/([A-Za-z0-9_-]+)/"', html)
    ))
    print(
        f"  {len(cities)} cities found in {_to_label(state)}", file=sys.stderr
    )
    all_urls: list[str] = []
    for city in cities:
        all_urls.extend(_urls_in_city(country, state, city, ctx))
    return all_urls


def _urls_from_sitemap(country: str, ctx: ScrapeContext) -> list[str]:
    """Pull all /{country}/{state}/{city}/{slug}/ URLs from the sitemap."""
    print("  Checking sitemap ...", file=sys.stderr)
    try:
        xml = _get(f"{BASE_URL}/sitemap.xml", ctx=ctx)
    except Exception as exc:
        print(f"  sitemap.xml failed: {exc}", file=sys.stderr)
        return []

    # Sitemap index? Expand sub-sitemaps first.
    sub_maps = re.findall(r"<loc>(https?://[^<]+sitemap[^<]*)</loc>", xml)
    texts = [xml] if not sub_maps else []
    for sm in sub_maps:
        try:
            texts.append(_get(sm, ctx=ctx))
        except Exception:
            pass

    pattern = (
        rf"https?://(?:www\.)?datacentermap\.com"
        rf"/{country}/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/\""
    )
    urls: list[str] = []
    for text in texts:
        urls.extend(re.findall(pattern, text))
    return list(dict.fromkeys(urls))


def _urls_from_country_crawl(country: str, ctx: ScrapeContext) -> list[str]:
    """BFS crawl: /{country}/ -> state pages -> city pages -> DC URLs."""
    print("  Crawling country page ...", file=sys.stderr)
    try:
        html = _get(f"{BASE_URL}/{country}/", ctx=ctx)
    except Exception as exc:
        print(f"  country page failed: {exc}", file=sys.stderr)
        return []
    states = list(dict.fromkeys(
        re.findall(rf'href="/{country}/([A-Za-z0-9_-]+)/"', html)
    ))
    print(f"  {len(states)} states/regions found", file=sys.stderr)
    all_urls: list[str] = []
    for state in states:
        all_urls.extend(_urls_in_state(country, state, ctx))
    return all_urls


def discover_urls(
    country: str,
    state: str | None,
    city: str | None,
    ctx: ScrapeContext,
) -> list[str]:
    """Return de-duplicated DC detail-page URLs for the requested geography."""
    if state and city:
        return _urls_in_city(country, state, city, ctx)
    if state:
        return _urls_in_state(country, state, ctx)
    # Full country: sitemap is fastest
    urls = _urls_from_sitemap(country, ctx)
    if urls:
        print(f"  Sitemap: {len(urls)} URLs found", file=sys.stderr)
        return urls
    print("  Sitemap empty/failed -- falling back to crawl", file=sys.stderr)
    return _urls_from_country_crawl(country, ctx)


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
    state_raw = input("State   [all]: ").strip()
    city_raw = input("City    [all]: ").strip() if state_raw else ""

    country = _to_slug(country_raw)
    state = _to_slug(state_raw) if state_raw else None
    city = _to_slug(city_raw) if city_raw else None
    return country, state, city


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def _default_output(
    country: str, state: str | None, city: str | None
) -> pathlib.Path:
    parts = [country]
    if state:
        parts.append(state)
    if city:
        parts.append(city)
    return pathlib.Path("output") / ("_".join(parts) + ".jsonl")


# ---------------------------------------------------------------------------
# Main orchestration
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
    parser.add_argument("--state", default=None, metavar="NAME",
                        help="State or region (optional)")
    parser.add_argument("--city", default=None, metavar="NAME",
                        help="City (optional; requires --state)")
    parser.add_argument("--output", default=None, metavar="PATH",
                        help="Override output JSONL file path")
    parser.add_argument("--delay", type=float, default=3.0,
                        help="Seconds between requests (default: 3.0)")
    parser.add_argument("--sample", type=int, default=0,
                        help="Stop after N records, for testing (0 = all)")
    parser.add_argument("--rediscover", action="store_true",
                        help="Re-run URL discovery even if a cache file exists")
    parser.add_argument("--proxy", default=None, metavar="URL", action="append",
                        help="Proxy URL (host:port[:user:pass] or full URL). "
                             "Repeatable. Combined with --proxy-file.")
    parser.add_argument("--proxy-file", default=None, metavar="PATH",
                        help="File with one proxy per line "
                             "(Webshare host:port:user:pass format supported)")
    args = parser.parse_args()

    # Determine geography
    if args.country or args.state or args.city:
        country = _to_slug(args.country or "usa")
        state = _to_slug(args.state) if args.state else None
        city = _to_slug(args.city) if args.city else None
    else:
        country, state, city = _prompt_geography()

    # Build proxy pool
    proxies: list[str] = []
    for raw in (args.proxy or []):
        p = _normalize_proxy(raw)
        if p:
            proxies.append(p)
    if args.proxy_file:
        pf = pathlib.Path(args.proxy_file)
        if not pf.exists():
            print(f"Proxy file not found: {pf}", file=sys.stderr)
            sys.exit(1)
        for line in pf.read_text(encoding="utf-8").splitlines():
            p = _normalize_proxy(line)
            if p:
                proxies.append(p)

    # Initialize context
    try:
        import curl_cffi.requests as cffi_requests
    except ImportError:
        cffi_requests = None

    ctx = ScrapeContext(
        delay=args.delay,
        cffi_requests=cffi_requests,
        proxies=proxies,
    )

    if proxies:
        if not ctx.use_curl:
            print(
                "WARNING: curl_cffi not installed -- using proxies over urllib,"
                " which still exposes a non-Chrome TLS fingerprint. Install"
                " curl_cffi (see requirements.txt) for best results.",
                file=sys.stderr,
            )
        print(f"Proxy pool: {len(proxies)} proxies loaded", file=sys.stderr)

    out_path = (
        pathlib.Path(args.output)
        if args.output
        else _default_output(country, state, city)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Print scope summary
    scope_parts = [_to_label(country)]
    if state:
        scope_parts.append(_to_label(state))
    if city:
        scope_parts.append(_to_label(city))
    print(f"\nScope:  {' > '.join(scope_parts)}", file=sys.stderr)
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

    urls_cache = out_path.with_name(out_path.stem + "_urls.txt")

    if urls_cache.exists() and not args.rediscover:
        with urls_cache.open(encoding="utf-8") as fh:
            all_urls = [ln.strip() for ln in fh if ln.strip()]
        print(
            f"\nPhase 1: Loaded {len(all_urls)} cached URLs from {urls_cache}"
            f"\n  (use --rediscover to re-run discovery)\n",
            file=sys.stderr,
        )
    else:
        print("\nPhase 1: Discovering datacenter URLs ...", file=sys.stderr)
        all_urls = discover_urls(country, state, city, ctx)

        if not all_urls:
            print(
                "\n  No URLs found. Check your spelling -- the scraper uses the"
                "\n  same slugs as datacentermap.com (e.g. 'New York' -> new-york).",
                file=sys.stderr,
            )
            sys.exit(1)

        urls_cache.write_text("\n".join(all_urls) + "\n", encoding="utf-8")
        print(f"  URLs cached to {urls_cache}", file=sys.stderr)

    todo = [u for u in all_urls if u not in seen]
    grand_total = len(seen) + len(todo)
    print(
        f"Phase 2: Scraping {len(todo)} datacenters"
        f" ({len(seen)} already done, {grand_total} total)\n",
        file=sys.stderr,
    )

    count = 0
    consecutive_bot_checks = 0
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
                html = _get(url, ctx=ctx, bar=bar)
                dc = _extract_dc_payload(html)
                if not dc:
                    raise ValueError(
                        "no __NEXT_DATA__ (possible bot-check or empty page)"
                    )
                record = _normalize_dc_record(dc, fallback_url=url)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                count += 1
                consecutive_bot_checks = 0
                scraped_total = len(seen) + count
                elapsed = _fmt_elapsed(time.time() - start_time)
                if bar is not None:
                    bar.set_description(
                        f"Scraped {scraped_total}/{grand_total}"
                    )
                    bar.set_postfix(elapsed=elapsed)
                elif count % 50 == 0 or count == len(todo):
                    pct = scraped_total / grand_total * 100
                    print(
                        f"  [{scraped_total}/{grand_total}]"
                        f" {pct:.1f}% | {elapsed}",
                        file=sys.stderr,
                    )
            except Exception as exc:
                msg = str(exc)
                if "no __NEXT_DATA__" in msg:
                    _log(f"  ERROR (bot-check) {url}", bar)
                    consecutive_bot_checks += 1
                    if consecutive_bot_checks >= 3:
                        cooldown = random.uniform(180, 300)
                        _log(
                            f"  [{consecutive_bot_checks} consecutive"
                            f" bot-checks] cooling down {cooldown:.0f}s"
                            f" then refreshing session ...",
                            bar,
                        )
                        time.sleep(cooldown)
                        ctx.refresh_session()
                        consecutive_bot_checks = 0
                else:
                    _log(f"  ERROR {url}: {exc}", bar)
                    consecutive_bot_checks = 0

    print(
        f"\nDone: {count} new records written to {out_path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()