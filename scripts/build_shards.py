#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            link = (row.get("link") or "").strip()
            if not link:
                continue
            rows.append(
                {
                    "link": link,
                    "datacenters": int(row.get("datacenters") or 0),
                }
            )
    rows.sort(key=lambda item: int(item["datacenters"]), reverse=True)
    return rows


def build_shards(rows: list[dict[str, int | str]], shard_count: int) -> list[dict]:
    shards = [
        {
            "name": f"shard_{index + 1:02d}",
            "total_datacenters": 0,
            "items": [],
        }
        for index in range(shard_count)
    ]
    for row in rows:
        target = min(shards, key=lambda item: item["total_datacenters"])
        target["items"].append(row)
        target["total_datacenters"] += int(row["datacenters"])
    return shards


def main() -> None:
    parser = argparse.ArgumentParser(description="Build balanced shard files from country counts.")
    parser.add_argument("countries_csv", type=Path)
    parser.add_argument("--shards", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    rows = load_rows(args.countries_csv)
    shards = build_shards(rows, args.shards)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"shard_count": args.shards, "shards": []}
    for shard in shards:
        shard_path = args.output_dir / f"{shard['name']}.txt"
        shard_path.write_text(
            "\n".join(str(item["link"]) for item in shard["items"]) + "\n",
            encoding="utf-8",
        )
        manifest["shards"].append(
            {
                "name": shard["name"],
                "file": str(shard_path),
                "total_datacenters": shard["total_datacenters"],
                "item_count": len(shard["items"]),
            }
        )
        print(f"{shard['name']}: {len(shard['items'])} items, ~{shard['total_datacenters']} records")

    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()

