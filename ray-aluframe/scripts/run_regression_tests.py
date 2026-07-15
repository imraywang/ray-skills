#!/usr/bin/env python3
"""Run deterministic regression checks for the self-contained skill."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from check_frame import load_catalog, validate
from generate_parametric_frame import generate
from render_interactive_html import html_document, _payload


def base_config(template: str) -> dict:
    return {
        "template": template,
        "width_mm": 1200,
        "depth_mm": 500,
        "height_mm": 1500,
        "bay_count": 2,
        "level_count": 3,
        "load_per_level_kg": 30,
        "gross_mass_kg": 140,
        "center_of_mass_mm": [600, 250, 550],
        "horizontal_force_n": 100,
        "force_height_mm": 900,
        "bracing_planes": ["xz", "yz"],
        "lateral_stability": "XZ 和 YZ 平面都有刚性板",
        "tip_over": "按输入总重、重心与水平力检查",
    }


def main() -> int:
    catalog = load_catalog()
    products = {item["id"]: item for item in catalog["products"]}
    assert len(products) >= 56
    for product_id in ("RAF-C-ANCHOR-30-8", "RAF-A-CASTER-75-BRAKE", "RAF-D-LIMIT-CHAIN", "RAF-D-SLIDE-RAIL"):
        assert product_id in products
    for product_id in ("RAF-D-HINGE-40X40", "RAF-D-KNOB-25", "RAF-D-MAGNET-45", "RAF-D-LIMIT-CHAIN"):
        assert products[product_id].get("fastener_components"), product_id

    designs = {}
    for template in ("rack", "workbench", "enclosure"):
        design = generate(base_config(template))
        result = validate(design)
        assert not result["errors"], (template, result["errors"])
        assert all(row["status"] == "PASS" for row in result["stability_results"]["lateral"])
        assert all(row["status"] == "PASS" for row in result["stability_results"]["tip_over"])
        designs[template] = design

    door_design = copy.deepcopy(designs["workbench"])
    door_design["doors"] = [
        {
            "id": "D1",
            "label": "测试下翻门",
            "bounds": [0, 600, 0, 500],
            "front_y_mm": -10,
            "gap_mm": 4,
            "frame_profile_catalog_id": "RAF-P-2020",
            "frame_profile_mm": 20,
            "panel_catalog_id": "RAF-B-PC-FLUTED-5",
            "panel_thickness_mm": 5,
            "opening": "drop_down",
            "hinge_edge": "bottom",
            "hinge_catalog_id": "RAF-D-HINGE-40X40",
            "hinge_qty": 2,
            "handle_catalog_id": "RAF-D-KNOB-25",
            "catch_catalog_id": "RAF-D-MAGNET-45",
            "restraint_catalog_id": "RAF-D-LIMIT-CHAIN",
            "opening_clearance_mm": 600,
        }
    ]
    good_door = validate(door_design)
    assert good_door["door_results"][0]["status"] == "PASS", good_door["door_results"]
    assert any(row["section"] == "门系统紧固件" for row in good_door["quote"]["rows"])

    bad_door = copy.deepcopy(door_design)
    bad_door["doors"][0]["restraint_catalog_id"] = None
    bad_door["doors"][0]["opening_clearance_mm"] = 100
    bad_result = validate(bad_door)
    assert any("限位" in item for item in bad_result["blockers"])
    assert any("开启净空" in item for item in bad_result["blockers"])

    moving = copy.deepcopy(designs["rack"])
    moving["accessories"].append({"category": "caster", "catalog_id": "RAF-A-CASTER-75-BRAKE", "description": "测试脚轮", "qty": 4})
    moving_result = validate(moving)
    assert any("额定载荷" in item for item in moving_result["blockers"])

    connection = copy.deepcopy(designs["rack"])
    connection["joints"][0]["connector"].update({"demand_n": 2000, "capacity_n": 1000})
    connection_result = validate(connection)
    assert any("连接件承载初查失败" in item for item in connection_result["blockers"])

    reference = copy.deepcopy(designs["rack"])
    tiny_svg = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnIHdpZHRoPScxMCcgaGVpZ2h0PScxMCcvPg=="
    reference["reference_image"] = {"id": "front", "data_uri": tiny_svg, "view": "front", "label": "正面"}
    reference["reference_images"] = [{"id": "detail", "data_uri": tiny_svg, "view": "detail", "label": "节点细节", "calibration": {"known_length_mm": 100, "pixel_length": 50, "mm_per_pixel": 2}}]
    reference["reference_topology"] = {"front_plane_y_mm": 0, "regions": [{"id": "ALL", "label": "正面", "x_range_mm": [0, 1200], "z_range_mm": [0, 1500], "expected_rows": 3, "confidence": "high"}]}
    reference_result = validate(reference)
    assert not any("参考图" in item for item in reference_result["blockers"]), reference_result["blockers"]

    exported = {"format": "ray-aluframe-package-v1", "design": door_design}
    exported_result = validate(exported)
    assert not exported_result["errors"]

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "design.json"
        path.write_text(json.dumps(reference, ensure_ascii=False), encoding="utf-8")
        payload = _payload(reference, path.parent)
        document = html_document(payload)
        for marker in ("下载方案", "两点定尺度", "reference-view-select", "reference-calibration-layer", "reference-known-length", "bay_frame_v1"):
            assert marker in document, marker

    print("OK: 目录、三类参数化结构、整架稳定、连接、门板、参考图、下载包均通过回归检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
