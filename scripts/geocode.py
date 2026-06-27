"""Enrich scraped datacenter records with geocoding data.

Tier 1 – US Census Geocoder  → lat/lon + FIPS state/county/tract
Tier 2 – Nominatim (OSM)     → ZIP confirmation, display_name, state_abbr, county_name

Writes:
  <output-jsonl>   – enriched JSONL (one record per line)
  <output-csv>     – flat CSV with all columns
  <failed>         – detail_url list for records that couldn't be geocoded

Usage:
    python scripts/geocode.py output/usa.jsonl \\
        --output-jsonl output/usa_geocoded.jsonl \\
        --output-csv   output/usa.csv \\
        --failed       output/failed_geocode.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Census Geocoder
# ---------------------------------------------------------------------------

_CENSUS_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/address"
)
_CENSUS_HEADERS = {
    "User-Agent": "datacentermap-geocoder/1.0 (contact: research use)",
    "Accept": "application/json",
}


def _census_geocode(street: str, city: str, state: str, postal: str | None) -> dict | None:
    """
    Call the Census Geocoder and return a dict of extracted fields, or None.

    Returned keys: latitude, longitude, state_fips, county_fips,
                   census_tract, state_name, county_name.
    """
    params: dict[str, str] = {
        "street": street,
        "city": city,
        "state": state,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    if postal:
        params["zip"] = postal

    url = _CENSUS_URL + "?" + urllib.parse.urlencode(params)
    try:
        rq = urllib.request.Request(url, headers=_CENSUS_HEADERS)
        with urllib.request.urlopen(rq, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"    Census error: {exc}", file=sys.stderr)
        return None

    matches = (
        data.get("result", {})
        .get("addressMatches", [])
    )
    if not matches:
        return None

    m = matches[0]
    coords = m.get("coordinates", {})
    out = _extract_fips(m.get("geographies", {}))
    out["latitude"] = coords.get("y")
    out["longitude"] = coords.get("x")
    return out


def _extract_fips(geographies: dict) -> dict:
    """Pull state/county/tract FIPS + names out of a Census `geographies` block.

    Shared by the address and coordinates endpoints (both return the same
    `Census Tracts` / `Counties` / `States` shape).
    """
    geos = geographies.get("Census Tracts", [{}])
    geo = geos[0] if geos else {}
    counties = geographies.get("Counties", [{}])
    county = counties[0] if counties else {}
    states = geographies.get("States", [{}])
    st = states[0] if states else {}

    return {
        "state_fips": geo.get("STATE") or st.get("STATE"),
        "county_fips": geo.get("COUNTY") or county.get("COUNTY"),
        "census_tract": geo.get("TRACT"),
        "state_name": st.get("NAME"),
        "county_name": county.get("NAME"),
    }


_CENSUS_COORDS_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
)


def _census_geocode_coords(lat: float, lon: float) -> dict | None:
    """Reverse-lookup FIPS from coordinates via the Census `coordinates` endpoint.

    Used as a fallback when the address geocoder fails to match but the record
    already has lat/lon (from the site or Nominatim). Returns the same FIPS keys
    as `_census_geocode` (minus lat/lon), or None on error / no match.
    """
    params = {
        "x": str(lon),
        "y": str(lat),
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    url = _CENSUS_COORDS_URL + "?" + urllib.parse.urlencode(params)
    try:
        rq = urllib.request.Request(url, headers=_CENSUS_HEADERS)
        with urllib.request.urlopen(rq, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        print(f"    Census coords error: {exc}", file=sys.stderr)
        return None

    geographies = data.get("result", {}).get("geographies")
    if not geographies:
        return None
    out = _extract_fips(geographies)
    if not out.get("state_fips"):
        return None
    return out


# ---------------------------------------------------------------------------
# Nominatim (OSM)
# ---------------------------------------------------------------------------

def _nominatim_geocode(
    street: str, city: str, state: str, postal: str | None
) -> dict | None:
    """
    Call Nominatim and return supplemental string fields, or None.

    Returned keys: latitude, longitude, postcode, display_name,
                   state_abbr, county_name.
    """
    try:
        from geopy.geocoders import Nominatim  # type: ignore[import]
        from geopy.extra.rate_limiter import RateLimiter  # type: ignore[import]
    except ImportError:
        print(
            "    geopy not installed – skipping Nominatim "
            "(pip install geopy)",
            file=sys.stderr,
        )
        return None

    query_parts = [p for p in [street, city, state, postal, "USA"] if p]
    query = ", ".join(query_parts)

    geolocator = Nominatim(user_agent="datacentermap-geocoder/1.0")
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1)
    try:
        loc = geocode(query, addressdetails=True, language="en", timeout=15)
    except Exception as exc:
        print(f"    Nominatim error: {exc}", file=sys.stderr)
        return None

    if loc is None:
        return None

    addr: dict[str, str] = loc.raw.get("address", {})

    # ISO 3166-2 state code e.g. "US-OH" → "OH"
    iso = addr.get("ISO3166-2-lvl4", "")
    state_abbr = iso.split("-", 1)[-1] if "-" in iso else None

    county_raw = addr.get("county", "")
    # Strip trailing " County" if present for a clean name
    county_name = county_raw.removesuffix(" County") if county_raw else None

    return {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "postcode": addr.get("postcode"),
        "display_name": loc.address,
        "state_abbr": state_abbr,
        "county_name": county_name or county_raw or None,
    }


# ---------------------------------------------------------------------------
# Record enrichment
# ---------------------------------------------------------------------------

def enrich(record: dict, census_delay: float = 1.0) -> dict:
    """Add `geo` block to a record using Census + Nominatim."""
    addr = record.get("address", {})
    street = addr.get("address") or ""
    city = addr.get("city") or ""
    state = addr.get("state") or ""
    postal = addr.get("postal")

    if not street or not city or not state:
        return record  # not enough address info

    # --- Tier 1: Census ---
    time.sleep(census_delay)
    census = _census_geocode(street, city, state, postal)

    # --- Tier 2: Nominatim (always called for string fields) ---
    # RateLimiter inside _nominatim_geocode already enforces 1 req/s
    nom = _nominatim_geocode(street, city, state, postal)

    # Merge: Census provides coordinates + FIPS; Nominatim provides strings.
    geo: dict[str, Any] = {
        "postcode": None,
        "display_name": None,
        "state_abbr": None,
        "county_name": None,
        "state_fips": None,
        "county_fips": None,
        "census_tract": None,
    }

    if census:
        geo.update({
            "state_fips": census.get("state_fips"),
            "county_fips": census.get("county_fips"),
            "census_tract": census.get("census_tract"),
            "county_name": census.get("county_name"),
        })
        # Use Census coordinates if the scraped record has none
        loc = record.setdefault("location", {})
        if loc.get("latitude") is None:
            loc["latitude"] = census.get("latitude")
            loc["longitude"] = census.get("longitude")

    if nom:
        geo.update({
            "postcode": nom.get("postcode"),
            "display_name": nom.get("display_name"),
            "state_abbr": nom.get("state_abbr"),
            # Prefer Census county name (more authoritative for FIPS context)
            "county_name": geo.get("county_name") or nom.get("county_name"),
        })
        # Fall back to Nominatim coordinates if Census also failed
        loc = record.setdefault("location", {})
        if loc.get("latitude") is None:
            loc["latitude"] = nom.get("latitude")
            loc["longitude"] = nom.get("longitude")

    # --- FIPS fallback: address match missed but we have coordinates ---
    # The Census address geocoder is strict about street strings; when it
    # misses, reverse-lookup FIPS from the coordinates we already have.
    loc = record.get("location", {})
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if geo.get("state_fips") is None and lat is not None and lon is not None:
        time.sleep(census_delay)
        fips = _census_geocode_coords(lat, lon)
        if fips:
            geo.update({
                "state_fips": fips.get("state_fips"),
                "county_fips": fips.get("county_fips"),
                "census_tract": fips.get("census_tract"),
                "county_name": geo.get("county_name") or fips.get("county_name"),
            })

    record["geo"] = geo
    return record


def _geocoded(record: dict) -> bool:
    """True if the record has at least lat/lon."""
    loc = record.get("location", {})
    return loc.get("latitude") is not None and loc.get("longitude") is not None


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

_CSV_COLUMNS = [
    "name",
    "operator_name",
    "stage",
    "archived",
    "address",
    "city",
    "state",
    "state_abbr",
    "postal",
    "county_name",
    "detail_url",
    "latitude",
    "longitude",
    "fips_state",
    "fips_county",
    "census_tract",
    "display_name",
]


def _record_to_row(rec: dict) -> dict[str, Any]:
    loc = rec.get("location", {})
    geo = rec.get("geo", {})
    addr = rec.get("address", {})
    identity = rec.get("identity", {})
    return {
        "name": identity.get("name"),
        "operator_name": identity.get("operator_name"),
        "stage": identity.get("stage"),
        "archived": identity.get("archived"),
        "address": addr.get("address"),
        "city": addr.get("city"),
        "state": addr.get("state"),
        "state_abbr": geo.get("state_abbr"),
        "postal": addr.get("postal") or geo.get("postcode"),
        "county_name": geo.get("county_name"),
        "detail_url": rec.get("source", {}).get("detail_url"),
        "latitude": loc.get("latitude"),
        "longitude": loc.get("longitude"),
        "fips_state": geo.get("state_fips"),
        "fips_county": geo.get("county_fips"),
        "census_tract": geo.get("census_tract"),
        "display_name": geo.get("display_name"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Geocode scraped US datacenter JSONL → enriched JSONL + CSV"
    )
    parser.add_argument("input", help="Input JSONL file (output of scrape_usa.py)")
    parser.add_argument(
        "--output-jsonl", default="output/usa_geocoded.jsonl",
        help="Enriched JSONL output path",
    )
    parser.add_argument(
        "--output-csv", default="output/usa.csv",
        help="Final CSV output path",
    )
    parser.add_argument(
        "--failed", default="output/failed_geocode.txt",
        help="File to list detail_urls that couldn't be geocoded",
    )
    parser.add_argument(
        "--census-delay", type=float, default=0.5,
        help="Seconds between Census Geocoder requests (default: 0.5)",
    )
    args = parser.parse_args()

    in_path = pathlib.Path(args.input)
    out_jsonl = pathlib.Path(args.output_jsonl)
    out_csv = pathlib.Path(args.output_csv)
    failed_path = pathlib.Path(args.failed)

    for p in (out_jsonl, out_csv, failed_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    # Load input records
    records: list[dict] = []
    with in_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    print(f"Loaded {len(records)} records from {in_path}", file=sys.stderr)

    # Load already-geocoded URLs (for resume)
    done_urls: set[str] = set()
    enriched: list[dict] = []
    if out_jsonl.exists():
        with out_jsonl.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    done_urls.add(rec["source"]["detail_url"])
                    enriched.append(rec)
                except Exception:
                    pass
        if done_urls:
            print(f"Resuming: {len(done_urls)} already geocoded", file=sys.stderr)

    # Backfill FIPS for already-geocoded records that have coordinates but no
    # FIPS (address-match misses from before the coordinate fallback existed).
    backfill = [
        r for r in enriched
        if isinstance(r.get("geo"), dict)
        and r["geo"].get("state_fips") is None
        and (r.get("location") or {}).get("latitude") is not None
        and (r.get("location") or {}).get("longitude") is not None
    ]
    if backfill:
        print(
            f"Backfilling FIPS for {len(backfill)} records from coordinates ...",
            file=sys.stderr,
        )
        try:
            from tqdm import tqdm as _tqdm
            bf_iter = _tqdm(backfill, desc="fips-backfill", unit="dc")
        except ImportError:
            bf_iter = backfill
        filled = 0
        for rec in bf_iter:
            loc = rec["location"]
            time.sleep(args.census_delay)
            fips = _census_geocode_coords(loc["latitude"], loc["longitude"])
            if fips:
                geo = rec["geo"]
                geo["state_fips"] = fips.get("state_fips")
                geo["county_fips"] = fips.get("county_fips")
                geo["census_tract"] = fips.get("census_tract")
                if not geo.get("county_name"):
                    geo["county_name"] = fips.get("county_name")
                filled += 1
        print(f"Backfilled FIPS for {filled}/{len(backfill)} records", file=sys.stderr)

    failed_urls: list[str] = []

    with out_jsonl.open("a", encoding="utf-8") as jfh:
        todo = [
            r for r in records
            if r.get("source", {}).get("detail_url") not in done_urls
        ]
        print(f"Geocoding {len(todo)} records ...", file=sys.stderr)

        try:
            from tqdm import tqdm  # type: ignore[import]
            iterable = tqdm(todo, desc="geocoding", unit="dc")
        except ImportError:
            iterable = todo

        grand_total = len(records)
        for i, rec in enumerate(iterable, start=1):
            detail_url = rec.get("source", {}).get("detail_url", "")
            geocoded_total = len(done_urls) + i
            print(f"  [{geocoded_total}/{grand_total}] {detail_url}", file=sys.stderr)

            enriched_rec = enrich(rec, census_delay=args.census_delay)
            jfh.write(json.dumps(enriched_rec, ensure_ascii=False) + "\n")
            jfh.flush()
            enriched.append(enriched_rec)

            if not _geocoded(enriched_rec):
                failed_urls.append(detail_url)

    # Canonicalize the JSONL: rewrite the whole file from the in-memory set so
    # backfilled FIPS are persisted and any duplicate appended lines collapse.
    with out_jsonl.open("w", encoding="utf-8") as jfh:
        for rec in enriched:
            jfh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write CSV (all records, geocoded or not)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as cfh:
        writer = csv.DictWriter(cfh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for rec in enriched:
            writer.writerow(_record_to_row(rec))
    print(f"CSV written: {out_csv} ({len(enriched)} rows)", file=sys.stderr)

    # Write failed list
    if failed_urls:
        with failed_path.open("w", encoding="utf-8") as ffh:
            ffh.write("\n".join(failed_urls) + "\n")
        print(
            f"Failed to geocode: {len(failed_urls)} records → {failed_path}",
            file=sys.stderr,
        )
    else:
        print("All records geocoded successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
