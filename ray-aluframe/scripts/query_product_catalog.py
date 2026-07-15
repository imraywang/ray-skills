#!/usr/bin/env python3
"""Query the self-contained Ray Aluframe product catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CATALOG = Path(__file__).resolve().parents[1] / "references" / "product-catalog.json"


def _text(item: dict[str, Any]) -> str:
    return " ".join(str(value) for value in item.values() if value is not None).lower()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--kind", choices=["system", "profile", "shaft", "product", "kit"])
    parser.add_argument("--series", type=int)
    parser.add_argument("--slot", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    groups = {
        "system": catalog["systems"],
        "profile": [item for item in catalog["profiles"] if item["kind"] == "profile"],
        "shaft": [item for item in catalog["profiles"] if item["kind"] == "shaft"],
        "product": catalog["products"],
        "kit": catalog["kits"],
    }
    kinds = [args.kind] if args.kind else list(groups)
    query = args.query.lower().strip()
    results: list[dict[str, Any]] = []
    for kind in kinds:
        for item in groups[kind]:
            if query and query not in _text(item):
                continue
            if args.series is not None and item.get("series") != args.series:
                system_id = str(item.get("system_id") or "")
                item_id = str(item.get("id") or "")
                if not system_id.startswith(f"RAF-S{args.series}-") and f"-{args.series}-" not in item_id:
                    continue
            if args.slot is not None and item.get("slot_width_mm") != args.slot:
                system_id = str(item.get("system_id") or "")
                item_id = str(item.get("id") or "")
                if f"-{args.slot}-" not in system_id and f"-{args.slot}-" not in item_id:
                    continue
            results.append({"kind": kind, **item})

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    for item in results:
        details = []
        for key in ("designation", "series", "slot_width_mm", "default_thread", "data_status"):
            if item.get(key) is not None:
                details.append(f"{key}={item[key]}")
        print(f"{item['id']}\t{item.get('name', '')}\t{' '.join(details)}")


if __name__ == "__main__":
    main()
