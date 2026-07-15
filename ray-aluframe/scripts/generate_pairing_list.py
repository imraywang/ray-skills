#!/usr/bin/env python3
"""Generate a direct purchase pairing list from a ray-aluframe design."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = SKILL_DIR / "references" / "product-catalog.json"


def _member_length(member: dict[str, Any]) -> int:
    start = member.get("start") or []
    end = member.get("end") or []
    if len(start) != 3 or len(end) != 3:
        raise ValueError(f'构件 {member.get("id", "?")} 缺少三维起终点')
    length = math.sqrt(sum((float(end[i]) - float(start[i])) ** 2 for i in range(3)))
    return int(round(length))


def _round_up(value: int, step: int) -> int:
    return int(math.ceil(value / step) * step) if value else 0


def _profile_spec(profile: dict[str, Any]) -> tuple[int, int]:
    return int(profile.get("width_mm") or 0), int(profile.get("height_mm") or 0)


def _profile_slot_width(profile: dict[str, Any]) -> int | None:
    explicit = profile.get("slot_width_mm")
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return int(explicit)
    text = " ".join(
        str(profile.get(key) or "")
        for key in ("series", "part_number", "description")
    ).lower()
    match = re.search(r"(?:槽|slot(?:\s+width)?|groove)\s*[-:]?\s*(6|8|10)\b", text)
    return int(match.group(1)) if match else None


def _find_system(profile: dict[str, Any], systems: list[dict[str, Any]]) -> dict[str, Any] | None:
    width, height = _profile_spec(profile)
    slot_width = _profile_slot_width(profile)
    for system in systems:
        sizes = {
            tuple(int(value) for value in size)
            for size in system.get("profile_sizes_mm", system.get("common_profile_sizes_mm", []))
        }
        size_matches = (width, height) in sizes or (height, width) in sizes
        slot_matches = slot_width is None or slot_width == int(system.get("slot_width_mm") or 0)
        ambiguous_40 = int(system.get("series") or 0) == 40 and slot_width is None
        if size_matches and slot_matches and not ambiguous_40:
            return system
    return None


def _accessory_display(
    item: dict[str, Any], system: dict[str, Any] | None, products: dict[str, dict[str, Any]]
) -> tuple[str, str]:
    category = str(item.get("category") or "")
    description = str(item.get("description") or "")
    if category == "foot":
        if system:
            foot_id = f"RAF-A-FOOT-PLATE-{system['series']}"
            product = products.get(foot_id) or {}
            return product.get("name") or "调节脚", f"本目录编号 {foot_id}"
        return "调节脚", "型材体系未确定，暂不自动匹配"
    if category == "shelf":
        if "600x350x18" in description:
            return "木质层板 600×350×18 mm", "板厚和封边确认后加工；固定件另见层板固定套装"
        if "1200x350x18" in description:
            return "木质层板 1200×350×18 mm", "板厚和封边确认后加工；固定件另见层板固定套装"
        return "木质层板", "按净尺寸、板厚和封边要求加工"
    if category == "backing":
        if "peg" in description or "display" in description:
            return "右侧展示板 / 洞洞板", "按净尺寸开料，周边多点固定"
        return "左侧刚性背板", "按净尺寸开料，周边多点固定并参与抗侧摆"
    if category == "appearance_optional":
        product_id = f"RAF-A-CAP-ANGLE-{system['series']}" if system else ""
        return "角码装饰盖（可选）", f"本目录编号 {product_id}" if product_id else "随角码体系选择"
    if category == "bracing":
        return "后侧抗侧摆拉条或刚性背板套装", "二选一并明确固定点，不能只靠层板防侧摆"
    if system and category == "shelf_fastener":
        product_id = f"RAF-P-SHELF-BRACKET-{system['series']}"
        product = products[product_id]
        return product["name"], f"本目录编号 {product_id}；{product['profile_fastener']}；{product['board_fastener']}"
    if system and category == "panel_fastener":
        product_id = f"RAF-P-PANEL-CLIP-{system['series']}"
        product = products[product_id]
        low, high = product["panel_thickness_range_mm"]
        return product["name"], f"本目录编号 {product_id}；{product['fastener']}；适配 {low}–{high} mm 板"
    if system and category in {"panel_mount", "panel", "backing"}:
        kit_id = system.get("panel_kit_id")
        return "后装面板固定套装", f"本目录编号 {kit_id}"
    name = description or category or "附件"
    return name, "按本目录同槽系套装选择"


def generate(design: dict[str, Any], catalog: dict[str, Any]) -> str:
    systems = catalog.get("systems", [])
    catalog_profiles = {entry["designation"]: entry for entry in catalog.get("profiles", [])}
    catalog_profiles_by_id = {entry["id"]: entry for entry in catalog.get("profiles", [])}
    profiles: dict[str, dict[str, Any]] = {}
    for entry in design.get("profiles", []):
        profile = dict(entry)
        reference = catalog_profiles_by_id.get(profile.get("catalog_id")) or {}
        for key in ("width_mm", "height_mm", "slot_width_mm", "slot_depth_mm", "series"):
            if profile.get(key) is None and reference.get(key) is not None:
                profile[key] = reference[key]
        profiles[profile["id"]] = profile
    products = {entry["id"]: entry for entry in catalog.get("products", [])}
    kits = {entry["id"]: entry for entry in catalog.get("kits", [])}
    member_groups: dict[tuple[str, int], int] = defaultdict(int)
    used_systems: dict[str, dict[str, Any]] = {}

    for member in design.get("members", []):
        profile_id = member.get("profile_id")
        if profile_id not in profiles:
            raise ValueError(f"构件 {member.get('id')} 引用了未知型材 {profile_id}")
        member_groups[(profile_id, _member_length(member))] += 1
        system = _find_system(profiles[profile_id], systems)
        if system:
            used_systems[system["id"]] = system

    title = str((design.get("project") or {}).get("name") or "铝型材方案")
    lines = [f"# {title} · 直观搭配清单", "", "## 型材下料", ""]
    lines += ["| 本目录编号 | 型材采购规格 | 长度 | 数量 | 配套体系 |", "|---|---|---:|---:|---|"]
    for (profile_id, length), qty in sorted(member_groups.items()):
        profile = profiles[profile_id]
        width, height = _profile_spec(profile)
        system = _find_system(profile, systems)
        system_name = system["name"] if system else "未形成自动配套"
        designation = f"{width}{height}"
        catalog_id = catalog_profiles.get(designation, {}).get("id", f"RAF-P-{designation}")
        lines.append(f"| {catalog_id} | {designation} 型材 | {length} mm | {qty} 根 | {system_name} |")

    angle_count = sum(int((joint.get("connector") or {}).get("qty") or 0) for joint in design.get("joints", []))
    lines += ["", "## 连接紧固件", ""]
    selected_system = next(iter(used_systems.values())) if len(used_systems) == 1 else None
    if selected_system and angle_count:
        system = selected_system
        kit = kits[system["standard_joint_kit_id"]]
        lines += [
            "| 本目录编号 | 物料 | 净数量 | 建议购买量 |",
            "|---|---|---:|---:|",
        ]
        for component in kit["components"]:
            product = products[component["product_id"]]
            qty = angle_count * int(component["qty"])
            name = product["name"] + ("（可选）" if component.get("optional") else "")
            step = 5 if product["kind"] in {"connector", "appearance"} else 10
            lines.append(f"| {product['id']} | {name} | {qty} | {_round_up(qty, step)} |")
        lines += ["", f"节点套装：{kit['id']} · {kit['name']}。以上数量已经拆开计算，不需要再访问其他目录补参数。"]
    else:
        lines.append("当前方案包含多套槽系或没有可自动配套的连接节点，需先按节点拆分角码数量。")

    accessories = design.get("accessories", [])
    if accessories:
        lines += ["", "## 层板、面板和底脚", "", "| 物料 | 数量 | 选择说明 |", "|---|---:|---|"]
        for item in accessories:
            if selected_system and item.get("category") == "appearance_optional":
                continue
            name, selection = _accessory_display(item, selected_system, products)
            lines.append(f"| {name} | {int(item.get('qty') or 0)} | {selection} |")

    if selected_system:
        kit = kits[selected_system["standard_joint_kit_id"]]
        angle_product = products[kit["components"][0]["product_id"]]
        lines += [
            "",
            "## 本方案采用的关键参数",
            "",
            "| 项目 | 参数 |",
            "|---|---|",
            f"| 型材体系 | {selected_system['name']} |",
            f"| 实际槽宽 | {selected_system['slot_width_mm']} mm |",
            f"| 槽深参考 | {selected_system['slot_depth_reference_mm']} mm |",
            f"| 默认螺纹 | {selected_system['default_thread']} |",
            f"| 结构角码 | {angle_product['width_mm']} mm 宽，{angle_product['arm_a_mm']}×{angle_product['arm_b_mm']} mm，厚 {angle_product['thickness_mm']} mm |",
            f"| 角码孔径 | {angle_product['hole_diameter_mm']} mm |",
        ]
        used_designations = sorted({f"{_profile_spec(profile)[0]}{_profile_spec(profile)[1]}" for profile in profiles.values()})
        for designation in used_designations:
            catalog_profile = catalog_profiles.get(designation) or {}
            engineering = catalog_profile.get("engineering_reference") or {}
            if engineering:
                class_name = "轻型参考截面" if engineering.get("class") == "light_reference" else "标准参考截面"
                lines.append(
                    f"| {designation} {class_name} | 米重 {engineering['weight_kg_m']} kg/m；Ix {engineering['ix_mm4']} mm⁴；Iy {engineering['iy_mm4']} mm⁴ |"
                )

    lines += [
        "",
        "## 发给商家的一句话",
        "",
        "> 请按本清单编号和参数整套供货；如现货规格不同，请逐项标出实际槽宽、中心孔、角码孔径、螺栓长度和槽螺母螺纹的差异，不要自行替换。",
        "",
        "这张表解决配套和数量；承重、侧摆、防倾倒及板材强度仍以检查报告为准。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    design = json.loads(args.design.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    output = generate(design, catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
