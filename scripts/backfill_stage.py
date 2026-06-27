"""Backfill identity.stage for records scraped before stage was added.

Reads the JSONL, re-fetches only records where stage is missing,
writes an updated JSONL in-place.

Usage:
    python scripts/backfill_stage.py output/usa.jsonl
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


def _get(url: str, delay: float = 1.0, max_retries: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        pause = (delay if attempt == 0 else delay * (2 ** attempt))
        pause *= random.uniform(0.8, 1.2)
        time.sleep(pause)
        try:
            if _USE_CURL:
                resp = _cffi_session.get(url, timeout=20)
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = f"HTTP {resp.status_code}"
                    continue
                resp.raise_for_status()
                return resp.text
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
        archived = page_props.get("query", {}).get("rw") == "true"
        return {"stage": dc.get("stage"), "archived": archived}
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill identity.stage in a scraped JSONL file."
    )
    parser.add_argument("input", help="JSONL file to update in-place")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Seconds between requests (default: 1.0)")
    args = parser.parse_args()

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

    need_backfill = [
        r for r in records
        if r.get("identity", {}).get("stage") is None
        or r.get("identity", {}).get("archived") is None
    ]
    print(
        f"{len(records)} records total, {len(need_backfill)} missing stage/archived",
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
