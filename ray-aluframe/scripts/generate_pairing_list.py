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
DEFAULT_PAIRINGS = SKILL_DIR / "references" / "standard-pairings.json"


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
        sizes = {tuple(int(value) for value in size) for size in system.get("common_profile_sizes_mm", [])}
        size_matches = (width, height) in sizes or (height, width) in sizes
        slot_matches = slot_width is None or slot_width == int(system.get("slot_width_mm") or 0)
        ambiguous_40 = int(system.get("series") or 0) == 40 and slot_width is None
        if size_matches and slot_matches and not ambiguous_40:
            return system
    return None


def _accessory_display(
    item: dict[str, Any], defaults: dict[str, dict[str, str]]
) -> tuple[str, str]:
    category = str(item.get("category") or "")
    description = str(item.get("description") or "")
    if category == "foot":
        candidate = defaults.get("F-BASE-PLATE") or {}
        return (
            candidate.get("name") or "调节脚",
            candidate.get("selection") or "按同一商家、同一槽系配套",
        )
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
        return "角码装饰盖（可选）", "与结构角码同系列、同尺寸"
    if category == "bracing":
        return "后侧抗侧摆拉条或刚性背板套装", "二选一并明确固定点，不能只靠层板防侧摆"
    candidate = defaults.get(item.get("candidate_id")) or {}
    name = candidate.get("name") or description or category or "附件"
    selection = candidate.get("selection") or "按同一商家、同一槽系配套"
    return name, selection


def generate(design: dict[str, Any], pairings: dict[str, Any]) -> str:
    profiles = {entry["id"]: entry for entry in design.get("profiles", [])}
    systems = pairings.get("default_systems", [])
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
    lines += ["| 型材采购规格 | 长度 | 数量 | 配套体系 |", "|---|---:|---:|---|"]
    for (profile_id, length), qty in sorted(member_groups.items()):
        profile = profiles[profile_id]
        width, height = _profile_spec(profile)
        system = _find_system(profile, systems)
        system_name = system["name"] if system else "未形成自动配套"
        lines.append(f"| {width}{height} 型材 | {length} mm | {qty} 根 | {system_name} |")

    angle_count = sum(int((joint.get("connector") or {}).get("qty") or 0) for joint in design.get("joints", []))
    lines += ["", "## 连接紧固件", ""]
    if len(used_systems) == 1 and angle_count:
        system = next(iter(used_systems.values()))
        angle = system["standard_angle"]
        bolts = angle_count * int(angle.get("bolts_per_piece") or 0)
        nuts = angle_count * int(angle.get("t_nuts_per_piece") or 0)
        thread = system["default_thread"]
        slot = system["slot_width_mm"]
        lines += [
            "| 物料 | 统一采购规格 | 净数量 | 建议购买量 |",
            "|---|---|---:|---:|",
            f"| 结构角码 | {angle['name']}，孔约 {angle['hole_diameter_mm']} mm | {angle_count} | {_round_up(angle_count, 5)} |",
            f"| 角码螺栓 | {thread} 内六角，长度随角码厚度 | {bolts} | {_round_up(bolts, 10)} |",
            f"| 槽螺母 | 槽 {slot} 后装弹片螺母 {thread} | {nuts} | {_round_up(nuts, 10)} |",
            f"| 角码盖 | 对应 {system['series']} 系角码，可选 | {angle_count} | {_round_up(angle_count, 5)} |",
            "",
            f"淘宝搜索词：{'；'.join(system.get('market_search_terms', []))}",
            "",
            "优先购买已含螺栓和槽螺母的角码套装；若套装已含，不要重复购买单独紧固件。",
        ]
    else:
        lines.append("当前方案包含多套槽系或没有可自动配套的连接节点，需先按节点拆分角码数量。")

    defaults = pairings.get("accessory_defaults", {})
    accessories = design.get("accessories", [])
    if accessories:
        lines += ["", "## 层板、面板和底脚", "", "| 物料 | 数量 | 选择说明 |", "|---|---:|---|"]
        for item in accessories:
            name, selection = _accessory_display(item, defaults)
            lines.append(f"| {name} | {int(item.get('qty') or 0)} | {selection} |")

    lines += [
        "",
        "## 发给商家的一句话",
        "",
        "> 请按同一槽系整套确认型材截面、实际槽宽、中心孔/攻丝、角码定位凸台、螺栓长度和槽螺母外形；如任一项不匹配，不要跨店替换。",
        "",
        "这张表解决配套和数量；承重、侧摆、防倾倒及板材强度仍以检查报告为准。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--pairings", type=Path, default=DEFAULT_PAIRINGS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    design = json.loads(args.design.read_text(encoding="utf-8"))
    pairings = json.loads(args.pairings.read_text(encoding="utf-8"))
    output = generate(design, pairings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
