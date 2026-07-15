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

from quote_engine import build_quote_bundle, build_receipt_checklist, resolve_design

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
                "system_id",
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


def connection_result(joint: dict[str, Any]) -> dict[str, Any] | None:
    connector = joint.get("connector") or {}
    demand = connector.get("demand_n")
    capacity = connector.get("capacity_n")
    if demand is None and capacity is None:
        return None
    result = {
        "joint_id": joint.get("id"),
        "demand_n": float(demand) if demand is not None else None,
        "capacity_n": float(capacity) if capacity is not None else None,
        "utilization": None,
        "status": "INCOMPLETE",
    }
    if demand is not None and capacity is not None and float(capacity) > 0:
        result["utilization"] = float(demand) / float(capacity)
        result["status"] = "PASS" if result["utilization"] <= 1 + EPS else "FAIL"
    return result


def stability_results(
    data: dict[str, Any],
    ground_points: list[list[float]],
    products: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    stability = data.get("stability") or {}
    result: dict[str, Any] = {"lateral": [], "tip_over": [], "casters": []}
    required = {str(value).lower() for value in stability.get("required_bracing_planes", [])}
    provided = {str(value).lower() for value in stability.get("bracing_planes", [])}
    for plane in sorted(required):
        aliases = {plane, f"rear_{plane}", f"front_{plane}", f"left_{plane}", f"right_{plane}"}
        passed = bool(provided & aliases)
        result["lateral"].append({"plane": plane, "status": "PASS" if passed else "FAIL"})

    mass = stability.get("gross_mass_kg")
    com = stability.get("center_of_mass_mm")
    horizontal_force = stability.get("horizontal_force_n")
    force_height = stability.get("force_height_mm")
    tip_factor = float(stability.get("tip_safety_factor") or 1.5)
    valid_ground = [point for point in ground_points if isinstance(point, list) and len(point) == 3]
    if mass is not None and isinstance(com, list) and len(com) == 3 and horizontal_force is not None and force_height is not None and valid_ground:
        x_min, x_max = min(point[0] for point in valid_ground), max(point[0] for point in valid_ground)
        y_min, y_max = min(point[1] for point in valid_ground), max(point[1] for point in valid_ground)
        for axis, low, high, center in (("x", x_min, x_max, float(com[0])), ("y", y_min, y_max, float(com[1]))):
            lever = min(center - low, high - center)
            restoring = float(mass) * G * max(0.0, lever)
            overturning = float(horizontal_force) * float(force_height)
            ratio = restoring / overturning if overturning > EPS else math.inf
            result["tip_over"].append(
                {
                    "axis": axis,
                    "restoring_moment_n_mm": restoring,
                    "overturning_moment_n_mm": overturning,
                    "safety_ratio": ratio,
                    "required_ratio": tip_factor,
                    "status": "PASS" if ratio + EPS >= tip_factor else "FAIL",
                }
            )

    caster_items = [item for item in data.get("accessories", []) if item.get("category") == "caster"]
    for item in caster_items:
        product = products.get(str(item.get("catalog_id") or "")) or {}
        rating = item.get("rated_load_kg_each", product.get("rated_load_kg_each"))
        qty = int(item.get("qty") or 0)
        share = float(item.get("effective_load_share") or stability.get("caster_effective_load_share") or 0.75)
        row = {"item": item.get("description") or product.get("name") or item.get("catalog_id"), "qty": qty, "rated_load_kg_each": rating, "required_load_kg_each": None, "status": "INCOMPLETE"}
        if mass is not None and rating is not None and qty > 0 and share > 0:
            row["required_load_kg_each"] = float(mass) / (qty * share)
            row["status"] = "PASS" if row["required_load_kg_each"] <= float(rating) + EPS else "FAIL"
        result["casters"].append(row)
    return result


def door_results(data: dict[str, Any], products: dict[str, dict[str, Any]], catalog_ids: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for door in data.get("doors", []):
        label = str(door.get("label") or door.get("id") or "未命名门")
        bounds = door.get("bounds")
        issues: list[str] = []
        if not (isinstance(bounds, list) and len(bounds) == 4 and all(isinstance(value, (int, float)) for value in bounds)):
            issues.append("门框范围无效")
            width = height = 0.0
        else:
            width = float(bounds[1]) - float(bounds[0]) - 2 * float(door.get("gap_mm") or 0)
            height = float(bounds[3]) - float(bounds[2]) - 2 * float(door.get("gap_mm") or 0)
            if width <= 0 or height <= 0:
                issues.append("门板净尺寸小于等于 0")
        for key, name in (("panel_catalog_id", "门板"), ("hinge_catalog_id", "合页"), ("handle_catalog_id", "把手"), ("catch_catalog_id", "闭合件")):
            if door.get(key) not in catalog_ids:
                issues.append(f"{name}目录编号无效")
        hinge_qty = int(door.get("hinge_qty") or 0)
        minimum_hinges = 3 if height > 700 else 2
        if hinge_qty < minimum_hinges:
            issues.append(f"合页少于 {minimum_hinges} 只")
        if door.get("opening") == "drop_down":
            restraint = door.get("restraint_catalog_id")
            if restraint not in catalog_ids:
                issues.append("下翻门缺少有效限位链或支撑件")
        clearance = door.get("opening_clearance_mm")
        if clearance is None:
            issues.append("未确认开启净空")
        elif float(clearance) < max(width, height) * (0.9 if door.get("opening") == "drop_down" else 0.6):
            issues.append("开启净空可能不足")
        hardware_ids = [door.get(key) for key in ("hinge_catalog_id", "handle_catalog_id", "catch_catalog_id", "restraint_catalog_id") if door.get(key)]
        for hardware_id in hardware_ids:
            product = products.get(str(hardware_id)) or {}
            if not product.get("fastener_components"):
                issues.append(f"{product.get('name') or hardware_id}未展开紧固件")
        result.append({"door_id": door.get("id"), "label": label, "width_mm": width, "height_mm": height, "issues": issues, "status": "PASS" if not issues else "FAIL"})
    doors = data.get("doors", [])
    for index, first in enumerate(doors):
        first_bounds = first.get("bounds")
        if not (isinstance(first_bounds, list) and len(first_bounds) == 4):
            continue
        for second in doors[index + 1 :]:
            second_bounds = second.get("bounds")
            if not (isinstance(second_bounds, list) and len(second_bounds) == 4):
                continue
            overlap_x = min(float(first_bounds[1]), float(second_bounds[1])) - max(float(first_bounds[0]), float(second_bounds[0]))
            overlap_z = min(float(first_bounds[3]), float(second_bounds[3])) - max(float(first_bounds[2]), float(second_bounds[2]))
            same_plane = abs(float(first.get("front_y_mm") or 0) - float(second.get("front_y_mm") or 0)) <= EPS
            if same_plane and overlap_x > EPS and overlap_z > EPS:
                first_result = next(item for item in result if item["door_id"] == first.get("id"))
                second_result = next(item for item in result if item["door_id"] == second.get("id"))
                message = f"与 {second.get('label') or second.get('id')} 的门框范围重叠"
                first_result["issues"].append(message)
                second_result["issues"].append(f"与 {first.get('label') or first.get('id')} 的门框范围重叠")
                first_result["status"] = second_result["status"] = "FAIL"
    return result


def validate(data: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []

    if isinstance(data.get("design"), dict) and str(data.get("format") or "").startswith("ray-aluframe"):
        data = data["design"]
    catalog = load_catalog()
    data = resolve_design(data, catalog)
    catalog_profiles_by_id = {item["id"]: item for item in catalog.get("profiles", [])}
    systems_by_id = {item["id"]: item for item in catalog.get("systems", [])}
    catalog_ids = {
        item["id"] for group in ("profiles", "products", "kits") for item in catalog.get(group, [])
    }
    products_by_id = {item["id"]: item for item in catalog.get("products", [])}
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
    connection_results: list[dict[str, Any]] = []

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
        capacity_check = connection_result(joint)
        if capacity_check:
            connection_results.append(capacity_check)
            if capacity_check["status"] == "FAIL":
                blockers.append(f"{jid}: 连接件承载初查失败")
            elif capacity_check["status"] == "INCOMPLETE":
                blockers.append(f"{jid}: 连接件需求或额定能力缺失")

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

    topology_results: list[dict[str, Any]] = []
    reference_topology = data.get("reference_topology")
    if reference_topology:
        front_y = reference_topology.get("front_plane_y_mm")
        regions = reference_topology.get("regions", [])
        if not isinstance(front_y, (int, float)) or not isinstance(regions, list) or not regions:
            blockers.append("参考图拓扑信息不完整，无法核对正面分区")
        else:
            for region in regions:
                label = str(region.get("label") or region.get("id") or "未命名区域")
                x_range = region.get("x_range_mm")
                z_range = region.get("z_range_mm")
                expected_rows = region.get("expected_rows")
                valid_range = (
                    isinstance(x_range, list)
                    and isinstance(z_range, list)
                    and len(x_range) == len(z_range) == 2
                    and all(isinstance(value, (int, float)) for value in x_range + z_range)
                    and float(x_range[0]) < float(x_range[1])
                    and float(z_range[0]) < float(z_range[1])
                )
                if not valid_range or not isinstance(expected_rows, int) or expected_rows < 1:
                    blockers.append(f"参考图拓扑区域 {label}: 范围或格数无效")
                    continue
                x_min, x_max = map(float, x_range)
                z_min, z_max = map(float, z_range)
                intervals_by_level: defaultdict[float, list[tuple[float, float]]] = defaultdict(list)
                for item in members.values():
                    start, end = item.get("start"), item.get("end")
                    if not (isinstance(start, list) and isinstance(end, list)):
                        continue
                    axis, _ = axis_and_length(start, end)
                    if axis != "x":
                        continue
                    if abs(float(start[1]) - float(front_y)) > EPS or abs(float(end[1]) - float(front_y)) > EPS:
                        continue
                    if abs(float(start[2]) - float(end[2])) > EPS:
                        continue
                    level = float(start[2])
                    if not (z_min + EPS < level < z_max - EPS):
                        continue
                    member_x_min = min(float(start[0]), float(end[0]))
                    member_x_max = max(float(start[0]), float(end[0]))
                    if member_x_max > x_min + EPS and member_x_min < x_max - EPS:
                        intervals_by_level[round(level, 6)].append((max(x_min, member_x_min), min(x_max, member_x_max)))
                internal_levels: set[float] = set()
                for level, intervals in intervals_by_level.items():
                    merged_end = x_min
                    for start_x, end_x in sorted(intervals):
                        if start_x > merged_end + EPS:
                            break
                        merged_end = max(merged_end, end_x)
                    if merged_end >= x_max - EPS:
                        internal_levels.add(level)
                actual_rows = len(internal_levels) + 1
                passed = actual_rows == expected_rows
                topology_results.append(
                    {
                        "id": str(region.get("id") or label),
                        "label": label,
                        "expected_rows": expected_rows,
                        "actual_rows": actual_rows,
                        "internal_levels_mm": sorted(internal_levels),
                        "status": "PASS" if passed else "FAIL",
                        "confidence": str(region.get("confidence") or "未标注"),
                    }
                )
                if not passed:
                    blockers.append(f"参考图拓扑不符: {label}应为 {expected_rows} 格，模型为 {actual_rows} 格")

    evidence_summary: Counter[str] = Counter()
    references = ([data.get("reference_image")] if data.get("reference_image") else []) + list(data.get("reference_images") or [])
    if references:
        if not reference_topology:
            blockers.append("已提供参考图但没有 reference_topology，无法核对可见分区")
        labels = set()
        for index, reference in enumerate(references, 1):
            if not isinstance(reference, dict):
                blockers.append(f"第 {index} 张参考图格式无效")
                continue
            view = str(reference.get("view") or "")
            if view not in {"front", "rear", "left", "right", "top", "detail"}:
                blockers.append(f"第 {index} 张参考图缺少有效视角")
            if view in labels and view != "detail":
                warnings.append(f"参考图视角 {view} 重复，建议标明各自用途")
            labels.add(view)
            calibration = reference.get("calibration") or {}
            if calibration:
                known = float(calibration.get("known_length_mm") or 0)
                pixels = float(calibration.get("pixel_length") or 0)
                if known <= 0 or pixels <= 0:
                    blockers.append(f"第 {index} 张参考图尺度校准无效")
        allowed_basis = {"visible", "inferred", "confirmed"}
        allowed_confidence = {"high", "medium", "low"}
        evidence_items = [("构件", item) for item in members.values()]
        evidence_items.extend(("外观项", item) for item in data.get("visuals", []))
        evidence_items.extend(("门板", item) for item in data.get("doors", []))
        for kind, item in evidence_items:
            item_id = str(item.get("id") or item.get("type") or "未命名")
            basis = item.get("evidence_basis")
            confidence = item.get("evidence_confidence")
            if basis not in allowed_basis:
                blockers.append(f"{kind} {item_id}: 未标明原图可见、结构推测或用户确认")
                continue
            evidence_summary[str(basis)] += 1
            if confidence not in allowed_confidence:
                blockers.append(f"{kind} {item_id}: 识别置信度未按 high/medium/low 标明")
            if basis == "inferred" and is_tbd(item.get("evidence_note")):
                warnings.append(f"{kind} {item_id}: 结构推测缺少依据说明")

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

    stability_check = stability_results(data, ground_points, products_by_id)
    for row in stability_check["lateral"]:
        if row["status"] == "FAIL":
            blockers.append(f"缺少 {row['plane']} 平面的抗侧摆措施")
    if not stability_check["tip_over"]:
        blockers.append("缺少总重、重心、水平力或作用高度，无法做防倾倒初查")
    for row in stability_check["tip_over"]:
        if row["status"] == "FAIL":
            blockers.append(f"{row['axis'].upper()} 方向防倾倒安全余量不足")
    for row in stability_check["casters"]:
        if row["status"] == "INCOMPLETE":
            blockers.append(f"脚轮 {row['item']}: 缺总重、数量或额定载荷")
        elif row["status"] == "FAIL":
            blockers.append(f"脚轮 {row['item']}: 单轮额定载荷不足")

    doors_check = door_results(data, products_by_id, catalog_ids)
    for row in doors_check:
        for issue in row["issues"]:
            blockers.append(f"门板 {row['label']}: {issue}")

    cut_plans: dict[str, list[dict[str, Any]]] = {}
    for pid, lengths in lengths_by_profile.items():
        profile = profiles[pid]
        cut_plans[pid] = cut_plan(
            lengths,
            float(profile["stock_length_mm"]),
            float(settings.get("kerf_mm", 0)),
            float(settings.get("end_trim_mm_each", 0)),
        )

    quote = build_quote_bundle(data, catalog, cut_plans)
    receipt_checklist = build_receipt_checklist(data, catalog, cut_plans)
    if (data.get("costing") or {}).get("required") and quote["unknown_items"]:
        names = "、".join(item["item"] for item in quote["unknown_items"][:5])
        suffix = "等" if len(quote["unknown_items"]) > 5 else ""
        blockers.append(f"费用估算缺少 {len(quote['unknown_items'])} 项价格：{names}{suffix}")

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
        "connection_results": connection_results,
        "stability_results": stability_check,
        "door_results": doors_check,
        "machining_rows": machining_rows,
        "topology_results": topology_results,
        "evidence_summary": evidence_summary,
        "resolved_design": data,
        "quote": quote,
        "receipt_checklist": receipt_checklist,
        "assembly_plan": data.get("assembly_plan") or {},
    }


def markdown(data: dict[str, Any], result: dict[str, Any]) -> str:
    data = result.get("resolved_design") or data
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

    if result["topology_results"]:
        lines += [
            "## 参考图拓扑核对",
            "",
            "| 正面区域 | 参考图 | 当前模型 | 识别置信度 | 结果 |",
            "|---|---:|---:|---|---|",
        ]
        for item in result["topology_results"]:
            lines.append(
                f"| {item['label']} | {item['expected_rows']} 格 | {item['actual_rows']} 格 | {item['confidence']} | {item['status']} |"
            )
        lines.append("")

    if data.get("reference_image"):
        evidence = result["evidence_summary"]
        lines += [
            "## 参考图识别依据",
            "",
            f"- 原图可见: {evidence.get('visible', 0)} 项",
            f"- 结构推测: {evidence.get('inferred', 0)} 项",
            f"- 用户确认: {evidence.get('confirmed', 0)} 项",
            "",
            "结构推测项不能仅凭预览图视为已确认，进入制作前仍需尺寸或多角度照片复核。",
            "",
        ]

    lines += ["## 横梁初查", "", "| 载荷 | 构件 | 变形 mm | 筛查值 mm | 结果 | 强度 |", "|---|---|---:|---:|---|---|"]
    if result["beam_results"]:
        for item in result["beam_results"]:
            strength = item["strength_status"] or "未检查"
            lines.append(f"| {item['load_id']} | {item['member_id']} | {item['deflection_mm']:.2f} | {item['limit_mm']:.2f} | {item['status']} | {strength} |")
    else:
        state = "载荷已提供但参数不足" if data.get("loads") else "未提供载荷"
        lines.append(f"| — | — | — | — | {state} | 未检查 |")
    lines.append("")

    lines += ["## 连接与整架稳定", "", "| 项目 | 对象 | 结果 | 说明 |", "|---|---|---|---|"]
    if result["connection_results"]:
        for item in result["connection_results"]:
            detail = "参数不完整" if item["utilization"] is None else f"利用率 {item['utilization']:.2f}"
            lines.append(f"| 连接承载 | {item['joint_id']} | {item['status']} | {detail} |")
    for item in result["stability_results"]["lateral"]:
        lines.append(f"| 抗侧摆 | {item['plane'].upper()} 平面 | {item['status']} | {'已提供' if item['status'] == 'PASS' else '缺少明确措施'} |")
    for item in result["stability_results"]["tip_over"]:
        lines.append(f"| 防倾倒 | {item['axis'].upper()} 方向 | {item['status']} | 安全比 {item['safety_ratio']:.2f}，要求 {item['required_ratio']:.2f} |")
    for item in result["stability_results"]["casters"]:
        required = "未算出" if item["required_load_kg_each"] is None else f"需 {item['required_load_kg_each']:.1f} kg/只"
        rated = "额定值缺失" if item["rated_load_kg_each"] is None else f"额定 {float(item['rated_load_kg_each']):.1f} kg/只"
        lines.append(f"| 脚轮 | {item['item']} | {item['status']} | {required}；{rated} |")
    if not any((result["connection_results"], result["stability_results"]["lateral"], result["stability_results"]["tip_over"], result["stability_results"]["casters"])):
        lines.append("| — | — | 未检查 | 缺少输入 |")
    lines.append("")

    if result["door_results"]:
        lines += ["## 门板系统", "", "| 门板 | 净尺寸 mm | 结果 | 待处理 |", "|---|---:|---|---|"]
        for item in result["door_results"]:
            issues = "；".join(item["issues"]) if item["issues"] else "无"
            lines.append(f"| {item['label']} | {item['width_mm']:.0f}×{item['height_mm']:.0f} | {item['status']} | {issues} |")
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

    quote = result["quote"]
    lines += ["## 费用估算", "", f"- 状态: {quote['status']}", f"- 含预留后的预算区间: **¥{quote['total_range_cny'][0]:.2f}–¥{quote['total_range_cny'][1]:.2f}**", f"- 预留比例: {quote['contingency_percent']:.0f}%", "", "| 类别 | 物料 | 数量 | 单价区间 | 小计区间 | 依据 |", "|---|---|---:|---:|---:|---|"]
    for row in quote["rows"]:
        unit_price = row["unit_price_range_cny"]
        amount = row["amount_range_cny"]
        lines.append(f"| {row['section']} | {row['item']} | {row['qty']:g} {row['unit']} | {('¥%.2f–¥%.2f' % tuple(unit_price)) if unit_price else '缺失'} | {('¥%.2f–¥%.2f' % tuple(amount)) if amount else '缺失'} | {row['price_source']} |")
    if quote["unknown_items"]:
        lines += ["", "缺价项: " + "；".join(item["item"] for item in quote["unknown_items"])]
    lines += ["", *[f"- {note}" for note in quote["assumptions"]], ""]

    lines += ["## 收货核对", "", "| 类别 | 物料 | 应收到 | 怎么核对 |", "|---|---|---|---|"]
    for row in result["receipt_checklist"]:
        lines.append(f"| {row['category']} | {row['item']} | {row['expected']} | {row['check']} |")
    lines.append("")

    lines += ["## 装配顺序", ""]
    for index, step in enumerate(result["assembly_plan"].get("steps", []), 1):
        if index == 1 and step.get("name") == "完整结构":
            continue
        lines += [f"{index - 1}. **{step['name'].split('·')[-1].strip()}**：{step['copy']} 复核：{step['check']}"]
    lines += ["", f"装配可达性: {result['assembly_plan'].get('access_status', '未检查')}。本方案采用后装螺母，遗漏单个螺母时可从槽口补入。", ""]
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
    report = markdown(result.get("resolved_design") or data, result)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
