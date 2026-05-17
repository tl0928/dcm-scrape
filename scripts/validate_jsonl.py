#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def get_path(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid json: {exc}")
                continue
            if not isinstance(item, dict):
                errors.append(f"line {line_number}: record must be an object")
                continue
            records.append(item)
    return records, errors


def validate(records: list[dict[str, Any]]) -> tuple[Counter, list[str]]:
    stats: Counter = Counter()
    issues: list[str] = []
    seen_urls: set[str] = set()

    core_paths = {
        "detail_url": "source.detail_url",
        "name": "identity.name",
        "operator_name": "identity.operator_name",
        "country": "address.country",
        "city": "address.city",
        "latitude": "location.latitude",
        "longitude": "location.longitude",
        "external_website": "links.external_website",
    }

    for index, record in enumerate(records, start=1):
        stats["records"] += 1
        detail_url = get_path(record, "source.detail_url")
        name = get_path(record, "identity.name")

        if not detail_url:
            stats["missing_detail_url"] += 1
            issues.append(f"record {index}: missing source.detail_url")
        elif detail_url in seen_urls:
            stats["duplicate_detail_url"] += 1
            issues.append(f"record {index}: duplicate detail_url {detail_url}")
        else:
            seen_urls.add(str(detail_url))

        if not name:
            stats["missing_name"] += 1
            issues.append(f"record {index}: missing identity.name")

        for stat_key, path in core_paths.items():
            value = get_path(record, path)
            if value not in (None, ""):
                stats[f"has_{stat_key}"] += 1

    return stats, issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate DataCenterMap JSONL records.")
    parser.add_argument("jsonl_path", type=Path)
    parser.add_argument("--max-issues", type=int, default=30)
    args = parser.parse_args()

    records, load_errors = load_jsonl(args.jsonl_path)
    stats, issues = validate(records)
    all_issues = load_errors + issues

    print("Validation summary")
    for key in (
        "records",
        "has_detail_url",
        "has_name",
        "has_operator_name",
        "has_country",
        "has_city",
        "has_latitude",
        "has_longitude",
        "has_external_website",
        "missing_detail_url",
        "missing_name",
        "duplicate_detail_url",
    ):
        print(f"- {key}: {stats[key]}")

    if all_issues:
        print("\nIssues")
        for issue in all_issues[: args.max_issues]:
            print(f"- {issue}")
        if len(all_issues) > args.max_issues:
            print(f"- ... {len(all_issues) - args.max_issues} more")
        raise SystemExit(1)

    print("\nOK: no blocking issues found")


if __name__ == "__main__":
    main()

