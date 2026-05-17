#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "name",
    "operator_name",
    "country",
    "city",
    "address",
    "latitude",
    "longitude",
    "external_website",
    "services",
    "power_mw",
    "whitespace",
    "detail_url",
]


def get_path(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(part)
    return value if value is not None else ""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                records.append(json.loads(text))
    return records


def row_from_record(record: dict[str, Any]) -> dict[str, Any]:
    services = get_path(record, "specs.services")
    if isinstance(services, list):
        services_text = " | ".join(str(item) for item in services)
    else:
        services_text = str(services or "")

    return {
        "name": get_path(record, "identity.name"),
        "operator_name": get_path(record, "identity.operator_name"),
        "country": get_path(record, "address.country"),
        "city": get_path(record, "address.city"),
        "address": get_path(record, "address.address"),
        "latitude": get_path(record, "location.latitude"),
        "longitude": get_path(record, "location.longitude"),
        "external_website": get_path(record, "links.external_website"),
        "services": services_text,
        "power_mw": get_path(record, "specs.capacity.power_mw"),
        "whitespace": get_path(record, "specs.capacity.whitespace"),
        "detail_url": get_path(record, "source.detail_url"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge DataCenterMap JSONL files into a CSV.")
    parser.add_argument("jsonl_paths", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for path in args.jsonl_paths:
        for record in load_jsonl(path):
            detail_url = str(get_path(record, "source.detail_url") or "")
            if detail_url and detail_url in seen_urls:
                continue
            if detail_url:
                seen_urls.add(detail_url)
            rows.append(row_from_record(record))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {args.output}")


if __name__ == "__main__":
    main()

