#!/usr/bin/env python3
"""Generate an editable rack, workbench, or enclosure design from a small JSON config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TEMPLATES = {"rack", "workbench", "enclosure"}


def member(member_id: str, role: str, start: list[float], end: list[float], profile_id: str) -> dict[str, Any]:
    return {
        "id": member_id,
        "profile_id": profile_id,
        "role": role,
        "start": start,
        "end": end,
        "machining_status": "not_required",
        "machining": [],
        "evidence_basis": "confirmed",
        "evidence_confidence": "high",
        "evidence_note": "由用户确认的参数生成。",
    }


def point_on_member(point: list[float], item: dict[str, Any]) -> bool:
    for axis in range(3):
        low, high = sorted((float(item["start"][axis]), float(item["end"][axis])))
        if not low - 1e-6 <= float(point[axis]) <= high + 1e-6:
            return False
        if abs(high - low) < 1e-6 and abs(float(point[axis]) - low) > 1e-6:
            return False
    return True


def joints(members: list[dict[str, Any]], kit_id: str) -> list[dict[str, Any]]:
    unique_points = {tuple(item[side]) for item in members for side in ("start", "end")}
    result = []
    for index, point in enumerate(sorted(unique_points, key=lambda value: (value[2], value[1], value[0])), 1):
        member_ids = [item["id"] for item in members if point_on_member(list(point), item)]
        if len(member_ids) < 2:
            continue
        result.append(
            {
                "id": f"J{index:03d}",
                "at": list(point),
                "member_ids": member_ids,
                "connector": {
                    "catalog_kit_id": kit_id,
                    "description": "本目录标准直角节点套装",
                    "qty": max(1, len(member_ids) - 1),
                },
            }
        )
    return result


def panel(panel_id: str, corners: list[list[float]], fill: str, note: str) -> dict[str, Any]:
    return {
        "type": "panel",
        "id": panel_id,
        "corners": corners,
        "fill": fill,
        "edge": "#6d665e",
        "opacity": 0.76,
        "evidence_basis": "confirmed",
        "evidence_confidence": "high",
        "evidence_note": note,
    }


def generate(config: dict[str, Any]) -> dict[str, Any]:
    template = str(config.get("template") or "rack")
    if template not in TEMPLATES:
        raise ValueError(f"template 只能是 {', '.join(sorted(TEMPLATES))}")
    width = float(config.get("width_mm") or 1200)
    depth = float(config.get("depth_mm") or 500)
    height = float(config.get("height_mm") or 1800)
    bays = int(config.get("bay_count") or 1)
    levels = int(config.get("level_count") or (3 if template == "rack" else 2))
    if min(width, depth, height) <= 0 or not 1 <= bays <= 8 or not 1 <= levels <= 10:
        raise ValueError("宽、深、高必须大于 0；分格 1–8，层数 1–10")

    profile_catalog_id = str(config.get("profile_catalog_id") or "RAF-P-3030")
    profile_id = "P-MAIN"
    stock_length = float(config.get("stock_length_mm") or 6100)
    joint_kit = str(config.get("joint_kit_id") or "RAF-KIT-JOINT-30-8-M6")
    base_z = float(config.get("base_z_mm") or 0)
    x_positions = [width * index / bays for index in range(bays + 1)]
    z_positions = [base_z + (height - base_z) * index / levels for index in range(levels + 1)]

    members: list[dict[str, Any]] = []
    for xi, x in enumerate(x_positions):
        for yi, y in enumerate((0.0, depth)):
            members.append(member(f"POST-{xi}-{yi}", "post", [x, y, base_z], [x, y, height], profile_id))
    for zi, z in enumerate(z_positions):
        for yi, y in enumerate((0.0, depth)):
            for bay in range(bays):
                members.append(member(f"LEVEL-{zi}-{yi}-{bay}", "level beam", [x_positions[bay], y, z], [x_positions[bay + 1], y, z], profile_id))
        for xi, x in enumerate(x_positions):
            members.append(member(f"SIDE-{zi}-{xi}", "side beam", [x, 0.0, z], [x, depth, z], profile_id))

    visuals: list[dict[str, Any]] = []
    shelf_levels = z_positions[1:] if template == "rack" else [z_positions[1]]
    for index, z in enumerate(shelf_levels, 1):
        visuals.append(panel(f"SHELF-{index}", [[0, 0, z + 8], [width, 0, z + 8], [width, depth, z + 8], [0, depth, z + 8]], "#c99c65", "由层数参数生成。"))
    if template == "enclosure":
        visuals.extend(
            [
                panel("BACK", [[0, depth, base_z], [width, depth, base_z], [width, depth, height], [0, depth, height]], "#dbe9e7", "机罩背板。"),
                panel("LEFT", [[0, 0, base_z], [0, depth, base_z], [0, depth, height], [0, 0, height]], "#dbe9e7", "机罩左侧板。"),
                panel("RIGHT", [[width, 0, base_z], [width, depth, base_z], [width, depth, height], [width, 0, height]], "#dbe9e7", "机罩右侧板。"),
            ]
        )

    gross_mass = float(config.get("gross_mass_kg") or 0)
    horizontal_force = float(config.get("horizontal_force_n") or 0)
    load_per_level = float(config.get("load_per_level_kg") or 0)
    loads = []
    if load_per_level > 0:
        for zi in range(1, len(z_positions)):
            for bay in range(bays):
                for yi in (0, 1):
                    loads.append(
                        {
                            "id": f"LOAD-{zi}-{yi}-{bay}",
                            "member_id": f"LEVEL-{zi}-{yi}-{bay}",
                            "mass_kg": load_per_level / bays / 2,
                            "distribution": "uniform",
                            "support": "simply_supported",
                            "inertia_axis": "y",
                            "safety_factor": float(config.get("load_safety_factor") or 1.5),
                            "dynamic_factor": float(config.get("dynamic_factor") or 1.0),
                            "deflection_limit_ratio": float(config.get("deflection_limit_ratio") or 200),
                        }
                    )

    accessories = list(config.get("accessories") or [])
    if not accessories:
        accessories = [
            {"category": "foot", "catalog_kit_id": "RAF-KIT-FOOT-30", "description": "30 系调平底脚套装", "qty": 2 * (bays + 1)},
            {"category": "shelf", "description": "板材按当前尺寸制作", "qty": len(shelf_levels)},
        ]

    design = {
        "project": {
            "name": str(config.get("name") or f"{round(width)}×{round(depth)}×{round(height)} 参数化{ {'rack':'置物架','workbench':'工作台','enclosure':'机罩'}[template] }"),
            "revision": "A-generated",
            "risk_level": str(config.get("risk_level") or "medium"),
            "notes": ["尺寸按型材中心线生成；制作前复核外尺寸、净空和连接方式。"],
        },
        "settings": {"kerf_mm": float(config.get("kerf_mm") or 3), "end_trim_mm_each": float(config.get("end_trim_mm_each") or 5)},
        "checks": {
            "load_path": str(config.get("load_path") or "层板或台面 → 横梁 → 立柱 → 底脚 → 地面"),
            "lateral_stability": str(config.get("lateral_stability") or "待确认刚性背板或两向斜撑"),
            "tip_over": str(config.get("tip_over") or "按总重、重心、水平力与支撑面计算"),
        },
        "profiles": [{"id": profile_id, "catalog_id": profile_catalog_id, "stock_length_mm": stock_length}],
        "members": members,
        "joints": joints(members, joint_kit),
        "ground_points": [[x, y, base_z] for x in x_positions for y in (0.0, depth)],
        "loads": loads,
        "accessories": accessories,
        "visuals": visuals,
        "stability": {
            "gross_mass_kg": gross_mass or None,
            "center_of_mass_mm": config.get("center_of_mass_mm") or [width / 2, depth / 2, height * 0.45],
            "horizontal_force_n": horizontal_force or None,
            "force_height_mm": float(config.get("force_height_mm") or height * 0.75),
            "tip_safety_factor": float(config.get("tip_safety_factor") or 1.5),
            "required_bracing_planes": ["xz", "yz"],
            "bracing_planes": list(config.get("bracing_planes") or []),
        },
        "editable": {
            "enabled": True,
            "layout": "bay_frame_v1",
            "template": template,
            "profile_id": profile_id,
            "base_z_mm": base_z,
            "minimum_bay_width_mm": 250,
            "load_per_level_kg": load_per_level,
            "load_safety_factor": float(config.get("load_safety_factor") or 1.5),
            "dynamic_factor": float(config.get("dynamic_factor") or 1.0),
            "deflection_limit_ratio": float(config.get("deflection_limit_ratio") or 200),
            "anchors": {"width_mm": width, "depth_mm": depth, "height_mm": height},
            "fields": [
                {"id": "width_mm", "label": "总宽", "value": width, "min": 300, "max": 6000, "step": 10, "unit": "mm"},
                {"id": "depth_mm", "label": "深度", "value": depth, "min": 200, "max": 2000, "step": 10, "unit": "mm"},
                {"id": "height_mm", "label": "总高", "value": height, "min": 300, "max": 4000, "step": 10, "unit": "mm"},
                {"id": "bay_count", "label": "横向分格", "value": bays, "min": 1, "max": 8, "step": 1, "unit": "格"},
                {"id": "level_count", "label": "层数", "value": levels, "min": 1, "max": 10, "step": 1, "unit": "层"},
            ],
        },
    }
    return design


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path, help="输入 JSON 配置")
    parser.add_argument("output", type=Path, help="输出设计 JSON")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    design = generate(config)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {design['project']['name']}，{len(design['members'])} 根型材，{len(design['joints'])} 个节点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
