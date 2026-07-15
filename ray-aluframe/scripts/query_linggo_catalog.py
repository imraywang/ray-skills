#!/usr/bin/env python3
"""Search the normalized Linggo material index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "references" / "linggo-catalog-index.json"


def _haystack(item: dict[str, Any]) -> str:
    values = [
        item.get("id"),
        item.get("label"),
        item.get("category_id"),
        *item.get("aliases", []),
        *item.get("search_terms", []),
    ]
    return " ".join(str(value) for value in values if value is not None).casefold()


def _records(catalog: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if kind in {"all", "profile", "shaft"}:
        for item in catalog.get("profiles", []):
            actual_kind = "shaft" if item.get("family") == "shaft" else "profile"
            if kind in {"all", actual_kind}:
                records.append({"kind": actual_kind, **item})
    if kind in {"all", "connector"}:
        records.extend({"kind": "connector", **item} for item in catalog.get("connectors", []))
    if kind in {"all", "accessory"}:
        records.extend({"kind": "accessory", **item} for item in catalog.get("accessories", []))
    if kind in {"all", "panel"}:
        records.extend(
            {
                "kind": "panel",
                "id": item.get("id"),
                "label": item.get("label"),
                "category_id": item.get("family"),
                **item,
            }
            for item in catalog.get("panel_finishes", [])
        )
    return records


def _matches(item: dict[str, Any], query: str, series: int | None, slot: int | None) -> bool:
    if query and query.casefold() not in _haystack(item):
        return False
    if series is not None:
        compatible = item.get("compatible_series") or item.get("connector_compat_series") or []
        if item.get("series") != series and series not in compatible:
            return False
    if slot is not None:
        compatible_slots = item.get("compatible_slot_width_mm") or []
        if item.get("slot_width_mm") != slot and slot not in compatible_slots:
            return False
    return True


def _detail(item: dict[str, Any]) -> str:
    if item["kind"] == "profile":
        return f'{item.get("width_mm")}x{item.get("height_mm")} mm / 槽{item.get("slot_width_mm")}'
    if item["kind"] == "shaft":
        return f'直径 {item.get("diameter_mm")} mm'
    if item["kind"] == "connector":
        series = ",".join(str(value) for value in item.get("compatible_series", [])) or "待确认"
        slots = ",".join(str(value) for value in item.get("compatible_slot_width_mm", [])) or "待确认"
        return f"{series} 系 / 槽{slots} / {item.get('subtype') or '连接件'}"
    if item["kind"] == "accessory":
        size = item.get("model_bbox_mm")
        return f"外形约 {size} mm" if size else str(item.get("category_id") or "")
    return str(item.get("family") or item.get("category_id") or "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="", help="ID、名称或搜索词")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument(
        "--kind",
        choices=["all", "profile", "shaft", "connector", "accessory", "panel"],
        default="all",
    )
    parser.add_argument("--series", type=int)
    parser.add_argument("--slot", type=int)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    results = [
        item
        for item in _records(catalog, args.kind)
        if _matches(item, args.query, args.series, args.slot)
    ][: max(args.limit, 0)]

    if args.as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f'{item["kind"]:<9} {item.get("id", ""):<28} {item.get("label", "")} | {_detail(item)}')
        print(f"共 {len(results)} 条")

    if not results:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
