#!/usr/bin/env python3
"""Validate a simple axis-aligned T-slot frame design and emit a quote-prep report."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

G = 9.80665
EPS = 1e-6


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
    bars: list[dict[str, Any]] = []
    for member_id, length in sorted(lengths, key=lambda item: item[1], reverse=True):
        placed = False
        for bar in bars:
            extra = length + (kerf if bar["cuts"] else 0)
            if bar["used"] + extra <= usable + EPS:
                bar["cuts"].append((member_id, length))
                bar["used"] += extra
                placed = True
                break
        if not placed:
            bars.append({"cuts": [(member_id, length)], "used": length})
    for bar in bars:
        bar["remaining_usable"] = max(0.0, usable - bar["used"])
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

    profiles = {p.get("id"): p for p in data.get("profiles", []) if p.get("id")}
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

    if len(profiles) != len(data.get("profiles", [])):
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
        part = connector.get("part_number")
        source = connector.get("source_url")
        if is_tbd(part) or is_tbd(source):
            blockers.append(f"{jid}: 连接件货号或来源待厂商绑定")
        connector_counts[(str(connector.get("manufacturer", "")), str(part or ""), str(connector.get("description", "")))] += int(connector.get("qty", 1))

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
        required = ("manufacturer", "part_number", "stock_length_mm", "source_url", "verified_on")
        missing = [key for key in required if is_tbd(profile.get(key))]
        if missing:
            blockers.append(f"型材 {pid}: 缺少采购来源字段 {', '.join(missing)}")
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
    for item in data.get("accessories", []):
        part = item.get("part_number")
        source = item.get("source_url")
        if is_tbd(part) or is_tbd(source):
            blockers.append(f"附件 {item.get('description', '?')}: 货号或来源待厂商绑定")
        accessory_counts[(str(item.get("category", "")), str(item.get("manufacturer", "")), str(part or ""), str(item.get("description", "")))] += int(item.get("qty", 1))

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
        lines.append("| — | — | — | — | 未提供载荷 | 未检查 |")
    lines.append("")

    lines += ["## 型材汇总与下料", ""]
    for pid, bars in result["cut_plans"].items():
        profile = result["profiles"][pid]
        total = result["total_length_by_profile"][pid]
        lines += [
            f"### {pid} · {profile.get('manufacturer', '')} {profile.get('part_number', '')}",
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

    lines += ["## 连接件", "", "| 厂商 | 货号 | 名称 | 数量 |", "|---|---|---|---:|"]
    for (manufacturer, part, description), qty in sorted(result["connector_counts"].items()):
        lines.append(f"| {manufacturer or '待定'} | {part or '待定'} | {description} | {qty} |")
    if not result["connector_counts"]:
        lines.append("| — | — | 未提供 | — |")
    lines.append("")

    lines += ["## 加工清单", "", "| 构件 | 位置 | 加工 |", "|---|---|---|"]
    for member_id, location, operation in result["machining_rows"]:
        lines.append(f"| {member_id} | {location} | {operation} |")
    if not result["machining_rows"]:
        lines.append("| — | — | 未提供 |")
    lines.append("")

    lines += ["## 附件", "", "| 类别 | 厂商 | 货号 | 名称 | 数量 |", "|---|---|---|---|---:|"]
    for (category, manufacturer, part, description), qty in sorted(result["accessory_counts"].items()):
        lines.append(f"| {category} | {manufacturer or '待定'} | {part or '待定'} | {description} | {qty} |")
    if not result["accessory_counts"]:
        lines.append("| — | — | — | 未提供 | — |")
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
