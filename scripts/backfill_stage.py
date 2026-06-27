"""Backfill identity.stage / identity.archived in a scraped JSONL file.

By default, re-fetches only records where stage or archived is missing (null)
and writes an updated JSONL in-place.

Use --archived to re-fetch *every* record and overwrite identity.archived. This
is needed to repair files scraped while archived was miscoded (it used the
always-true query.rw flag instead of dc.status == 2).

Usage:
    python scripts/backfill_stage.py output/usa.jsonl
    python scripts/backfill_stage.py output/usa.jsonl --archived
    python scripts/backfill_stage.py output/usa.jsonl --proxy-file proxies.txt
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request

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

try:
    import curl_cffi.requests as _cffi_requests
    _cffi_session = _cffi_requests.Session(impersonate="chrome120")
    _USE_CURL = True
except ImportError:
    _cffi_session = None
    _USE_CURL = False

# Proxy pool (populated by main() from --proxy / --proxy-file). A random proxy is
# chosen per request so a rotating residential pool spreads load across many IPs.
_PROXIES: list[str] = []


def _normalize_proxy(line: str) -> str | None:
    """Turn a proxy line into a full proxy URL (Webshare host:port:user:pass)."""
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
    return line


def _pick_proxy() -> dict | None:
    if not _PROXIES:
        return None
    proxy = random.choice(_PROXIES)
    return {"http": proxy, "https": proxy}


def _get(url: str, delay: float = 1.0, max_retries: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        pause = (delay if attempt == 0 else delay * (2 ** attempt))
        pause *= random.uniform(0.8, 1.2)
        time.sleep(pause)
        proxies = _pick_proxy()
        try:
            if _USE_CURL:
                kwargs: dict = {"timeout": 20}
                if proxies:
                    kwargs["proxies"] = proxies
                resp = _cffi_session.get(url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = f"HTTP {resp.status_code}"
                    continue
                resp.raise_for_status()
                return resp.text
            rq = urllib.request.Request(url, headers=_HEADERS)
            opener = urllib.request.urlopen
            if proxies:
                handler = urllib.request.ProxyHandler(proxies)
                opener = urllib.request.build_opener(handler).open
            with opener(rq, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                last_exc = exc
                continue
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            continue
        except Exception as exc:
            if _USE_CURL:
                last_exc = exc
                continue
            raise
    raise RuntimeError(f"Failed after {max_retries} attempts: {url}")


def _fetch_fields(url: str) -> dict | None:
    """Return {stage, archived} from the page, or None on failure."""
    try:
        html = _get(url)
    except Exception as exc:
        print(f"  fetch error {url}: {exc}", file=sys.stderr)
        return None
    idx = html.find("__NEXT_DATA__")
    if idx == -1:
        return None
    try:
        start = html.index("{", idx)
        end = html.find("</script>", start)
        data = json.loads(html[start:end])
        page_props = data["props"]["pageProps"]
        dc = page_props.get("dc") or {}
        # Archived listings keep stage: 2 but are marked status: 2 (active = 1).
        # query.rw is "true" on every page and is NOT an archived signal.
        archived = dc.get("status") == 2
        return {"stage": dc.get("stage"), "archived": archived}
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill identity.stage / identity.archived in a JSONL file."
    )
    parser.add_argument("input", help="JSONL file to update in-place")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds between requests (default: 1.0)")
    parser.add_argument("--archived", action="store_true",
                        help="Re-fetch every record and overwrite "
                             "identity.archived (repairs the old query.rw bug)")
    parser.add_argument("--proxy", default=None, metavar="URL", action="append",
                        help="Proxy URL (host:port[:user:pass] or full URL). "
                             "Repeatable. Combined with --proxy-file.")
    parser.add_argument("--proxy-file", default=None, metavar="PATH",
                        help="File with one proxy per line "
                             "(Webshare host:port:user:pass format supported)")
    args = parser.parse_args()

    # Build the proxy pool (random proxy per request).
    for raw in (args.proxy or []):
        p = _normalize_proxy(raw)
        if p:
            _PROXIES.append(p)
    if args.proxy_file:
        pf = pathlib.Path(args.proxy_file)
        if not pf.exists():
            print(f"Proxy file not found: {pf}", file=sys.stderr)
            sys.exit(1)
        for line in pf.read_text(encoding="utf-8").splitlines():
            p = _normalize_proxy(line)
            if p:
                _PROXIES.append(p)
    if _PROXIES:
        print(f"Proxy pool: {len(_PROXIES)} proxies loaded", file=sys.stderr)

    path = pathlib.Path(args.input)
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if args.archived:
        # Repair mode: re-fetch everything to overwrite the (possibly wrong)
        # archived flag, regardless of whether it is currently set.
        need_backfill = list(records)
        print(
            f"{len(records)} records total, re-fetching all to fix archived",
            file=sys.stderr,
        )
    else:
        need_backfill = [
            r for r in records
            if r.get("identity", {}).get("stage") is None
            or r.get("identity", {}).get("archived") is None
        ]
        print(
            f"{len(records)} records total,"
            f" {len(need_backfill)} missing stage/archived",
            file=sys.stderr,
        )

    if not need_backfill:
        print("Nothing to do.", file=sys.stderr)
        return

    updated = 0
    errors = 0
    for i, rec in enumerate(need_backfill, 1):
        url = rec.get("source", {}).get("detail_url", "")
        print(f"  [{i}/{len(need_backfill)}] {url}", file=sys.stderr)
        fields = _fetch_fields(url)
        if fields is not None:
            identity = rec.setdefault("identity", {})
            identity["stage"] = fields["stage"]
            identity["archived"] = fields["archived"]
            updated += 1
        else:
            errors += 1

    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    print(
        f"\nDone: {updated} updated, {errors} fetch errors -> {path}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
