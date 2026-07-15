#!/usr/bin/env python3
"""Validate a simple axis-aligned T-slot frame design and emit a quote-prep report."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

G = 9.80665
EPS = 1e-6
CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "product-catalog.json"


def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def hydrate_profiles(entries: list[dict[str, Any]], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    catalog_profiles = {item["id"]: item for item in catalog.get("profiles", [])}
    hydrated = []
    for entry in entries:
        profile = dict(entry)
        catalog_id = profile.get("catalog_id")
        if not catalog_id:
            width = int(profile.get("width_mm") or 0)
            height = int(profile.get("height_mm") or 0)
            candidate_id = f"RAF-P-{width}{height}"
            text = " ".join(str(profile.get(key) or "") for key in ("series", "description", "part_number"))
            slot_match = re.search(r"(?:槽|slot|groove)\s*[-:]?\s*(6|8|10)\b", text, re.I)
            slot_hint = int(profile.get("slot_width_mm") or (slot_match.group(1) if slot_match else 0))
            ambiguous_40 = width == height == 40 and not slot_hint
            candidate = catalog_profiles.get(candidate_id)
            if candidate and not ambiguous_40 and (not slot_hint or candidate.get("slot_width_mm") == slot_hint):
                catalog_id = candidate_id
                profile["catalog_id"] = catalog_id
        reference = catalog_profiles.get(catalog_id)
        if reference:
            for key in (
                "width_mm",
                "height_mm",
                "slot_width_mm",
                "slot_depth_mm",
                "wall_thickness_mm",
                "weight_kg_m",
                "supplier_id",
                "vendor_name",
                "price_cny_per_m",
            ):
                if profile.get(key) is None:
                    profile[key] = reference.get(key)
            profile.setdefault("part_number", reference.get("designation"))
            profile.setdefault("description", reference.get("name"))
            profile.setdefault("stock_length_mm", max(reference.get("stock_length_options_mm") or [6000]))
            engineering = reference.get("engineering_reference") or {}
            for key in ("weight_kg_m", "ix_mm4", "iy_mm4"):
                if profile.get(key) is None and engineering.get(key) is not None:
                    profile[key] = engineering[key]
            if engineering:
                profile.setdefault("e_mpa", 69000)
        hydrated.append(profile)
    return hydrated


def point_on_segment(point: list[float], start: list[float], end: list[float]) -> bool:
    if not all(min(a, b) - EPS <= p <= max(a, b) + EPS for p, a, b in zip(point, start, end)):
        return False
    return all(abs(p - a) <= EPS for p, a, b in zip(point, start, end) if abs(b - a) <= EPS)


def axis_and_length(start: list[float], end: list[float]) -> tuple[str | None, float]:
    diffs = [abs(b - a) for a, b in zip(start, end)]
    nonzero = [i for i, d in enumerate(diffs) if d > EPS]
    if len(nonzero) != 1:
        return None, math.dist(start, end)
    return "xyz"[nonzero[0]], diffs[nonzero[0]]


def is_tbd(value: Any) -> bool:
    return value is None or not str(value).strip() or "TBD" in str(value).upper()


def cut_plan(lengths: list[tuple[str, float]], stock: float, kerf: float, trim: float) -> list[dict[str, Any]]:
    usable = stock - 2 * trim
    capacity = usable + kerf
    pieces = sorted(lengths, key=lambda item: item[1], reverse=True)
    if any(length > usable + EPS for _, length in pieces):
        return [{"cuts": [(member_id, length)], "used": length, "remaining_usable": 0.0} for member_id, length in pieces]

    greedy: list[list[tuple[str, float]]] = []
    greedy_used: list[float] = []
    for member_id, length in pieces:
        size = length + kerf
        placed = False
        for index, used in enumerate(greedy_used):
            if used + size <= capacity + EPS:
                greedy[index].append((member_id, length))
                greedy_used[index] += size
                placed = True
                break
        if not placed:
            greedy.append([(member_id, length)])
            greedy_used.append(size)

    total_size = sum(length + kerf for _, length in pieces)
    lower_bound = max(1, math.ceil((total_size - EPS) / capacity))
    packed = greedy
    node_limit = 500_000

    for target in range(lower_bound, len(greedy)):
        bins: list[list[tuple[str, float]]] = [[] for _ in range(target)]
        used = [0.0] * target
        nodes = 0

        def place(index: int) -> bool:
            nonlocal nodes
            nodes += 1
            if nodes > node_limit:
                return False
            if index == len(pieces):
                return True
            remaining = sum(length + kerf for _, length in pieces[index:])
            if remaining > sum(capacity - value for value in used) + EPS:
                return False
            member_id, length = pieces[index]
            size = length + kerf
            seen_used: set[float] = set()
            for bin_index in range(target):
                marker = round(used[bin_index], 6)
                if marker in seen_used:
                    continue
                seen_used.add(marker)
                if used[bin_index] + size > capacity + EPS:
                    continue
                bins[bin_index].append((member_id, length))
                used[bin_index] += size
                if place(index + 1):
                    return True
                used[bin_index] -= size
                bins[bin_index].pop()
                if used[bin_index] <= EPS:
                    break
            return False

        if place(0):
            packed = bins
            break

    bars: list[dict[str, Any]] = []
    for cuts in packed:
        used_length = sum(length for _, length in cuts) + kerf * max(0, len(cuts) - 1)
        bars.append(
            {
                "cuts": cuts,
                "used": used_length,
                "remaining_usable": max(0.0, usable - used_length),
            }
        )
    return bars


def beam_result(load: dict[str, Any], member: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    _, length = axis_and_length(member["start"], member["end"])
    mass = float(load["mass_kg"])
    factor = float(load.get("safety_factor", 1.0)) * float(load.get("dynamic_factor", 1.0))
    force = mass * G * factor
    e = float(profile["e_mpa"])
    inertia_axis = load.get("inertia_axis", "y")
    inertia = float(profile[f"i{inertia_axis}_mm4"])
    support = load["support"]
    distribution = load["distribution"]

    if distribution == "center_point":
        formulas = {
            "simply_supported": (force * length**3 / (48 * e * inertia), force * length / 4),
            "fixed_fixed": (force * length**3 / (192 * e * inertia), force * length / 8),
            "cantilever": (force * length**3 / (3 * e * inertia), force * length),
        }
    else:
        w = force / length
        formulas = {
            "simply_supported": (5 * w * length**4 / (384 * e * inertia), w * length**2 / 8),
            "fixed_fixed": (w * length**4 / (384 * e * inertia), w * length**2 / 12),
            "cantilever": (w * length**4 / (8 * e * inertia), w * length**2 / 2),
        }
    deflection, moment = formulas[support]
    ratio = float(load.get("deflection_limit_ratio", 200))
    explicit = load.get("deflection_limit_mm")
    limit = float(explicit) if explicit is not None else length / ratio
    if deflection > limit + EPS:
        status = "FAIL"
    elif deflection > 0.75 * limit:
        status = "REVIEW"
    else:
        status = "PASS"

    section_modulus = profile.get(f"w{inertia_axis}_mm3")
    yield_mpa = profile.get("yield_mpa")
    stress = moment / float(section_modulus) if section_modulus else None
    strength_status = None
    if stress is not None and yield_mpa is not None:
        strength_status = "PASS" if stress <= float(yield_mpa) else "FAIL"

    return {
        "load_id": load["id"],
        "member_id": member["id"],
        "length_mm": length,
        "factored_force_n": force,
        "deflection_mm": deflection,
        "limit_mm": limit,
        "status": status,
        "stress_mpa": stress,
        "strength_status": strength_status,
    }


def validate(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []

    catalog = load_catalog()
    catalog_profiles_by_id = {item["id"]: item for item in catalog.get("profiles", [])}
    systems_by_id = {item["id"]: item for item in catalog.get("systems", [])}
    catalog_ids = {
        item["id"] for group in ("profiles", "products", "kits") for item in catalog.get(group, [])
    }
    profile_entries = hydrate_profiles(data.get("profiles", []), catalog)
    profiles = {p.get("id"): p for p in profile_entries if p.get("id")}
    members = {m.get("id"): m for m in data.get("members", []) if m.get("id")}
    joints = data.get("joints", [])
    settings = data.get("settings", {})
    ground_points = data.get("ground_points", [])
    project = data.get("project", {})
    risk_level = project.get("risk_level")
    if risk_level not in ("low", "medium", "high"):
        blockers.append("项目风险等级未按 low/medium/high 确认")
    checks = data.get("checks", {})
    for key, label in (("load_path", "载荷路径"), ("lateral_stability", "侧向稳定"), ("tip_over", "防倾倒")):
        if is_tbd(checks.get(key)):
            blockers.append(f"{label}措施未确认")

    if len(profiles) != len(profile_entries):
        errors.append("型材 id 缺失或重复")
    if len(members) != len(data.get("members", [])):
        errors.append("构件 id 缺失或重复")
    if not members:
        errors.append("没有构件")

    segments: dict[tuple[tuple[float, ...], tuple[float, ...]], str] = {}
    lengths_by_profile: dict[str, list[tuple[str, float]]] = defaultdict(list)
    total_length_by_profile: Counter[str] = Counter()
    total_weight = 0.0
    machining_rows: list[tuple[str, str, str]] = []

    for member in members.values():
        pid = member.get("profile_id")
        if pid not in profiles:
            errors.append(f"{member['id']}: 引用了不存在的型材 {pid}")
            continue
        start, end = member.get("start"), member.get("end")
        if not (isinstance(start, list) and isinstance(end, list) and len(start) == len(end) == 3):
            errors.append(f"{member['id']}: start/end 必须是三个坐标")
            continue
        axis, length = axis_and_length(start, end)
        if axis is None or length <= EPS:
            errors.append(f"{member['id']}: 首版只支持长度大于 0 的正交直杆")
            continue
        key = tuple(sorted((tuple(start), tuple(end))))
        if key in segments:
            errors.append(f"{member['id']}: 与 {segments[key]} 重复")
        segments[key] = member["id"]
        profile = profiles[pid]
        stock = float(profile.get("stock_length_mm") or 0)
        trim = float(settings.get("end_trim_mm_each", 0))
        if stock <= 2 * trim or length > stock - 2 * trim + EPS:
            errors.append(f"{member['id']}: {length:.1f} mm 超过型材可用原料长度")
        lengths_by_profile[pid].append((member["id"], length))
        total_length_by_profile[pid] += length
        if profile.get("weight_kg_m") is not None:
            total_weight += length / 1000 * float(profile["weight_kg_m"])
        machining_status = member.get("machining_status")
        operations = member.get("machining", [])
        if machining_status not in ("specified", "not_required"):
            blockers.append(f"{member['id']}: 加工状态未确认")
        elif machining_status == "specified" and not operations:
            blockers.append(f"{member['id']}: 标记为需要加工但没有加工项")
        if machining_status == "not_required":
            machining_rows.append((member["id"], "—", "无需加工（仍需商家按连接件复核）"))
        for operation in operations:
            description = str(operation.get("operation", ""))
            location = str(operation.get("location", operation.get("end", "")))
            machining_rows.append((member["id"], location, description))
            if is_tbd(description) or is_tbd(location):
                blockers.append(f"{member['id']}: 加工位置或内容待连接件确定")

    joint_ids: set[str] = set()
    endpoint_coverage: set[tuple[str, tuple[float, ...]]] = set()
    graph: dict[str, set[str]] = defaultdict(set)
    connector_counts: Counter[tuple[str, str, str]] = Counter()

    for joint in joints:
        jid = joint.get("id")
        if not jid or jid in joint_ids:
            errors.append("节点 id 缺失或重复")
            continue
        joint_ids.add(jid)
        at = joint.get("at")
        mids = joint.get("member_ids", [])
        if not (isinstance(at, list) and len(at) == 3):
            errors.append(f"{jid}: at 必须是三个坐标")
            continue
        valid_mids = []
        for mid in mids:
            member = members.get(mid)
            if not member:
                errors.append(f"{jid}: 引用了不存在的构件 {mid}")
                continue
            if not point_on_segment(at, member["start"], member["end"]):
                errors.append(f"{jid}: 坐标不在构件 {mid} 上")
                continue
            valid_mids.append(mid)
            if at == member["start"] or at == member["end"]:
                endpoint_coverage.add((mid, tuple(at)))
        for a in valid_mids:
            for b in valid_mids:
                if a != b:
                    graph[a].add(b)
        connector = joint.get("connector", {})
        catalog_id = connector.get("catalog_kit_id") or connector.get("catalog_id")
        if not catalog_id:
            system_ids = {
                catalog_profiles_by_id.get(profiles[members[mid]["profile_id"]].get("catalog_id"), {}).get("system_id")
                for mid in valid_mids
            }
            system_ids.discard(None)
            if len(system_ids) == 1:
                system = systems_by_id[next(iter(system_ids))]
                catalog_id = system["standard_joint_kit_id"]
                connector["catalog_kit_id"] = catalog_id
        if catalog_id not in catalog_ids:
            blockers.append(f"{jid}: 连接件缺少有效的本目录编号")
        connector_counts[(str(catalog_id or ""), str(connector.get("description", "")), "")] += int(connector.get("qty", 1))

    ground = {tuple(p) for p in ground_points if isinstance(p, list) and len(p) == 3}
    for member in members.values():
        if not (isinstance(member.get("start"), list) and isinstance(member.get("end"), list)):
            continue
        for point in (member["start"], member["end"]):
            covered = (member["id"], tuple(point)) in endpoint_coverage or tuple(point) in ground
            if not covered:
                errors.append(f"{member['id']}: 端点 {point} 没有节点或地面支撑")

    if members:
        start_id = next(iter(members))
        seen = {start_id}
        queue = deque([start_id])
        while queue:
            current = queue.popleft()
            for neighbor in graph[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        disconnected = set(members) - seen
        if disconnected:
            errors.append("存在未连通构件: " + ", ".join(sorted(disconnected)))

    for pid, profile in profiles.items():
        required = ("catalog_id", "stock_length_mm")
        missing = [key for key in required if is_tbd(profile.get(key))]
        if missing:
            blockers.append(f"型材 {pid}: 缺少本目录字段 {', '.join(missing)}")
        elif profile.get("catalog_id") not in catalog_ids:
            blockers.append(f"型材 {pid}: 本目录编号无效")
        if profile.get("assumptions"):
            warnings.append(f"型材 {pid}: 含假设数据,见 assumptions")

    beam_results: list[dict[str, Any]] = []
    loads = data.get("loads", [])
    if not loads:
        blockers.append("没有载荷数据,无法做横梁初查")
    for load in loads:
        member = members.get(load.get("member_id"))
        if not member:
            errors.append(f"载荷 {load.get('id', '?')}: 构件不存在")
            continue
        profile = profiles.get(member.get("profile_id"))
        inertia_axis = str(load.get("inertia_axis") or "y")
        missing_engineering = [
            key for key in ("e_mpa", f"i{inertia_axis}_mm4") if not profile or profile.get(key) is None
        ]
        if missing_engineering:
            blockers.append(
                f"{load.get('id', '?')}: 型材缺少弹性模量或 {inertia_axis.upper()} 向惯性参数，未做横梁变形初查"
            )
            continue
        try:
            result = beam_result(load, member, profile)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            errors.append(f"载荷 {load.get('id', '?')}: 无法计算 ({exc})")
            continue
        beam_results.append(result)
        if result["status"] == "FAIL":
            blockers.append(f"{result['load_id']}: 横梁变形超过筛查值")
        elif result["status"] == "REVIEW":
            warnings.append(f"{result['load_id']}: 横梁变形接近筛查值,需复核连接与实际载荷")
        if result["strength_status"] is None:
            warnings.append(f"{result['load_id']}: 缺截面模量或材料强度,未做强度初查")
        elif result["strength_status"] == "FAIL":
            blockers.append(f"{result['load_id']}: 弯曲应力初查失败")

    accessory_counts: Counter[tuple[str, str, str, str]] = Counter()
    design_system_ids = {
        catalog_profiles_by_id.get(profile.get("catalog_id"), {}).get("system_id") for profile in profiles.values()
    }
    design_system_ids.discard(None)
    design_system = systems_by_id[next(iter(design_system_ids))] if len(design_system_ids) == 1 else None
    for item in data.get("accessories", []):
        catalog_id = item.get("catalog_kit_id") or item.get("catalog_id")
        if not catalog_id and design_system:
            inferred_key = {
                "foot": "foot_kit_id",
                "shelf_fastener": "shelf_kit_id",
                "panel_fastener": "panel_kit_id",
            }.get(item.get("category"))
            if inferred_key:
                catalog_id = design_system[inferred_key]
                item["catalog_kit_id"] = catalog_id
        if catalog_id and catalog_id not in catalog_ids:
            blockers.append(f"附件 {item.get('description', '?')}: 本目录编号无效")
        accessory_counts[(str(item.get("category", "")), str(catalog_id or ""), "", str(item.get("description", "")))] += int(item.get("qty", 1))

    cut_plans: dict[str, list[dict[str, Any]]] = {}
    for pid, lengths in lengths_by_profile.items():
        profile = profiles[pid]
        cut_plans[pid] = cut_plan(
            lengths,
            float(profile["stock_length_mm"]),
            float(settings.get("kerf_mm", 0)),
            float(settings.get("end_trim_mm_each", 0)),
        )

    if errors:
        readiness = "草案"
    elif risk_level == "high":
        readiness = "受限模式"
    elif blockers or warnings:
        readiness = "待复核"
    else:
        readiness = "可询价"

    return {
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "blockers": sorted(set(blockers)),
        "readiness": readiness,
        "profiles": profiles,
        "members": members,
        "total_length_by_profile": total_length_by_profile,
        "total_profile_weight_kg": total_weight,
        "connector_counts": connector_counts,
        "accessory_counts": accessory_counts,
        "cut_plans": cut_plans,
        "beam_results": beam_results,
        "machining_rows": machining_rows,
    }


def markdown(data: dict[str, Any], result: dict[str, Any]) -> str:
    project = data.get("project", {})
    lines = [
        f"# {project.get('name', '铝型材方案')} · 检查报告",
        "",
        f"- 版本: {project.get('revision', '未标注')}",
        f"- 风险等级: {project.get('risk_level', '未标注')}",
        f"- 当前状态: **{result['readiness']}**",
        "- 状态含义: 可询价不等于已证明安全;仍需商家核对配件、加工与用途。",
        "",
    ]
    for title, key in (("错误", "errors"), ("询价阻断项", "blockers"), ("提醒", "warnings")):
        lines += [f"## {title}", ""]
        items = result[key]
        lines += [f"- {item}" for item in items] if items else ["- 无"]
        lines.append("")

    lines += ["## 横梁初查", "", "| 载荷 | 构件 | 变形 mm | 筛查值 mm | 结果 | 强度 |", "|---|---|---:|---:|---|---|"]
    if result["beam_results"]:
        for item in result["beam_results"]:
            strength = item["strength_status"] or "未检查"
            lines.append(f"| {item['load_id']} | {item['member_id']} | {item['deflection_mm']:.2f} | {item['limit_mm']:.2f} | {item['status']} | {strength} |")
    else:
        state = "载荷已提供但参数不足" if data.get("loads") else "未提供载荷"
        lines.append(f"| — | — | — | — | {state} | 未检查 |")
    lines.append("")

    lines += ["## 型材汇总与下料", ""]
    for pid, bars in result["cut_plans"].items():
        profile = result["profiles"][pid]
        total = result["total_length_by_profile"][pid]
        lines += [
            f"### {pid} · {profile.get('catalog_id', '未绑定')} {profile.get('part_number', '')}",
            "",
            f"- 成品总长: {total:.0f} mm",
            f"- 需要原料: {len(bars)} 根 × {float(profile['stock_length_mm']):.0f} mm",
            "",
            "| 原料 | 切割组合 | 可用余料 mm |",
            "|---|---|---:|",
        ]
        for index, bar in enumerate(bars, 1):
            cuts = ", ".join(f"{mid} {length:.0f}" for mid, length in bar["cuts"])
            lines.append(f"| {index} | {cuts} | {bar['remaining_usable']:.0f} |")
        lines.append("")
    lines.append(f"型材估算总重: {result['total_profile_weight_kg']:.2f} kg")
    lines.append("")

    lines += ["## 连接件", "", "| 本目录编号 | 名称 | 数量 |", "|---|---|---:|"]
    for (catalog_id, description, _), qty in sorted(result["connector_counts"].items()):
        lines.append(f"| {catalog_id or '待定'} | {description} | {qty} |")
    if not result["connector_counts"]:
        lines.append("| — | 未提供 | — |")
    lines.append("")

    lines += ["## 加工清单", "", "| 构件 | 位置 | 加工 |", "|---|---|---|"]
    for member_id, location, operation in result["machining_rows"]:
        lines.append(f"| {member_id} | {location} | {operation} |")
    if not result["machining_rows"]:
        lines.append("| — | — | 未提供 |")
    lines.append("")

    lines += ["## 附件", "", "| 类别 | 本目录编号 | 名称 | 数量 |", "|---|---|---|---:|"]
    for (category, catalog_id, _, description), qty in sorted(result["accessory_counts"].items()):
        lines.append(f"| {category} | {catalog_id or '按板材尺寸制作'} | {description} | {qty} |")
    if not result["accessory_counts"]:
        lines.append("| — | — | 未提供 | — |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.design.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"无法读取设计文件: {exc}", file=sys.stderr)
        return 2
    result = validate(data)
    report = markdown(data, result)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
