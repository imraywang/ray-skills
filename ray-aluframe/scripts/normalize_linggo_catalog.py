#!/usr/bin/env python3
"""Normalize a Linggo designer catalog export for ray-aluframe.

The input is the catalog-only JSON captured from an authenticated Linggo
designer page. This script deliberately drops account/session data, asset URLs,
textures, and 3D model files. The output is a compact design reference containing
names, dimensions, compatibility, placement hints, and bounding-box sizes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


CANONICAL_SOURCE_URL = "https://linggo.online/"
CANONICAL_DESIGNER_URL = "https://linggo.online/designer"


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _numbers(values: Any) -> list[int | float]:
    if not isinstance(values, list):
        return []
    return [value for value in values if _number(value) is not None]


def _strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _bbox_size(collision: dict[str, Any]) -> list[int | float] | None:
    bounds = collision.get("effectiveAabb")
    if not isinstance(bounds, list) or len(bounds) != 6:
        return None
    nums = [_number(value) for value in bounds]
    if any(value is None for value in nums):
        return None
    return [round(nums[1] - nums[0], 3), round(nums[3] - nums[2], 3), round(nums[5] - nums[4], 3)]


def _profile(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "label": entry.get("label"),
        "category_id": entry.get("categoryId"),
        "family": entry.get("family"),
        "system": entry.get("system"),
        "series": _number(entry.get("series")),
        "width_mm": _number(entry.get("width")),
        "height_mm": _number(entry.get("height")),
        "diameter_mm": _number(entry.get("diameter")),
        "slot_width_mm": _number(entry.get("slotWidth")),
        "slot_depth_mm": _number(entry.get("slotDepth")),
        "connector_compat_series": _numbers(entry.get("connectorCompatSeries")),
        "cross_section_quarter_turns": _number(entry.get("crossSectionQuarterTurns")) or 0,
        "aliases": _strings(entry.get("aliases")),
        "model_format": (entry.get("asset") or {}).get("format"),
        "model_source": (entry.get("asset") or {}).get("source"),
    }


GEOMETRY_FIELDS = (
    "armA",
    "armB",
    "cornerR",
    "csDepth",
    "csOuterD",
    "edgeOffset",
    "holeD",
    "holePitch",
    "thickness",
    "webInset",
    "webOffsetY",
    "webThickness",
    "width",
)


def _mountable(entry: dict[str, Any]) -> dict[str, Any]:
    style = entry.get("connectorStyle") or {}
    placement = entry.get("placement") or {}
    compat = placement.get("compat") or {}
    geometry = style.get("geometry") or {}
    capabilities = entry.get("capabilities") or {}
    asset = entry.get("asset") or {}
    ui = entry.get("ui") or {}
    item = {
        "id": entry.get("id"),
        "label": entry.get("label"),
        "category_id": entry.get("categoryId"),
        "kind": entry.get("kind"),
        "source": entry.get("source"),
        "model_format": asset.get("format"),
        "model_bbox_mm": _bbox_size(entry.get("collision") or {}),
        "manual_place": bool(capabilities.get("manualPlace")),
        "smart_place": bool(capabilities.get("smartPlace")),
        "placement_mode": placement.get("mode"),
        "placement_targets": _strings(placement.get("targets")),
        "compatible_series": _numbers(style.get("compatSeries") or compat.get("series")),
        "compatible_slot_width_mm": _numbers(style.get("compatSlot") or compat.get("slotWidth")),
        "search_terms": _strings(ui.get("search")),
    }
    if entry.get("kind") == "connector":
        item.update(
            {
                "subtype": style.get("subtype"),
                "nominal_size_mm": _number(style.get("size")),
                "geometry_mm": {
                    key: value
                    for key in GEOMETRY_FIELDS
                    if (value := _number(geometry.get(key))) is not None
                },
                "countersunk": bool(geometry.get("countersink")),
            }
        )
    return item


def _category_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        category_id = str(entry.get("categoryId") or "uncategorized")
        counts[category_id] = counts.get(category_id, 0) + 1
    return counts


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    profile_catalog = raw.get("profileCatalog") or {}
    mountable_catalog = raw.get("mountableCatalog") or {}
    panel_catalog = raw.get("panelMaterialCatalog") or {}

    profiles_raw = profile_catalog.get("profiles") or []
    mountables_raw = mountable_catalog.get("assets") or []
    panels_raw = panel_catalog.get("items") or []
    if not profiles_raw or not mountables_raw or not panels_raw:
        raise ValueError("Input must contain profileCatalog, mountableCatalog, and panelMaterialCatalog")

    profile_counts = _category_counts(profiles_raw)
    mountable_counts = _category_counts(mountables_raw)
    profiles = sorted((_profile(entry) for entry in profiles_raw), key=lambda item: str(item["id"]))
    mountables = [_mountable(entry) for entry in mountables_raw]
    connectors = sorted(
        (item for item in mountables if item["kind"] == "connector"),
        key=lambda item: str(item["id"]),
    )
    accessories = sorted(
        (item for item in mountables if item["kind"] == "accessory"),
        key=lambda item: str(item["id"]),
    )

    source_meta = profile_catalog.get("source") or {}
    return {
        "schema_version": 1,
        "source": {
            "name": "灵构 Linggo",
            "url": CANONICAL_SOURCE_URL,
            "designer_url": CANONICAL_DESIGNER_URL,
            "catalog_generated_at": source_meta.get("generatedAt"),
            "retrieved_at": raw.get("retrievedAt"),
            "scope": "目录名称、尺寸、兼容关系、放置提示与外形包围尺寸；不含账号、画布、价格、三维文件和纹理文件",
        },
        "usage_limits": [
            "用于结构表达、目录检索、兼容性初筛和效果图外形参考",
            "不包含每米重量、惯性矩、截面模量、材料强度或连接承载，不能直接用于承重结论",
            "目录货号不等于淘宝商家的可采购货号，下单前仍需由同一商家确认型材、槽宽、螺纹和连接件",
            "板材条目只代表外观材质，不代表厚度、强度、封边或加工能力",
        ],
        "summary": {
            "profiles_total": len(profiles),
            "aluminum_profiles": sum(item["family"] == "aluminum" for item in profiles),
            "shafts": sum(item["family"] == "shaft" for item in profiles),
            "connectors": len(connectors),
            "accessories": len(accessories),
            "panel_finishes": len(panels_raw),
        },
        "profile_categories": [
            {
                "id": entry.get("id"),
                "label": entry.get("label"),
                "family": entry.get("family"),
                "system": entry.get("system"),
                "series": _number(entry.get("series")),
                "slot_width_mm": _number(entry.get("slotWidth")),
                "slot_depth_mm": _number(entry.get("slotDepth")),
                "connector_compat_series": _numbers(entry.get("connectorCompatSeries")),
                "item_count": profile_counts.get(str(entry.get("id")), 0),
            }
            for entry in profile_catalog.get("categories") or []
        ],
        "profiles": profiles,
        "mountable_categories": [
            {
                "id": entry.get("id"),
                "label": entry.get("label"),
                "entry_points": _strings(entry.get("entryPoints")),
                "item_count": mountable_counts.get(str(entry.get("id")), 0),
            }
            for entry in mountable_catalog.get("categories") or []
        ],
        "connectors": connectors,
        "accessories": accessories,
        "panel_families": [
            {"id": entry.get("id"), "label": entry.get("label")}
            for entry in panel_catalog.get("families") or []
        ],
        "panel_finishes": [
            {
                "id": entry.get("id"),
                "label": entry.get("label"),
                "family": entry.get("family"),
                "finish_id": (entry.get("backend") or {}).get("finishId"),
                "base_color": (entry.get("frontend") or {}).get("color"),
                "metalness": _number((entry.get("frontend") or {}).get("metalness")),
                "roughness": _number((entry.get("frontend") or {}).get("roughness")),
            }
            for entry in panels_raw
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Catalog-only Linggo JSON export")
    parser.add_argument("output", type=Path, help="Normalized ray-aluframe catalog JSON")
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    normalized = normalize(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(normalized["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
