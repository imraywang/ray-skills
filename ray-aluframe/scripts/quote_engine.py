#!/usr/bin/env python3
"""Resolve standard pairings and build a self-contained quote package."""

from __future__ import annotations

import copy
import math
from collections import Counter, defaultdict
from typing import Any


def resolve_design(data: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Bind known Euro-series supplier profiles to catalog kits without hiding uncertainty."""
    result = copy.deepcopy(data)
    profiles_by_catalog = {item["id"]: item for item in catalog.get("profiles", [])}
    systems = {item["id"]: item for item in catalog.get("systems", [])}
    kits = {item["id"]: item for item in catalog.get("kits", [])}
    design_profiles: dict[str, dict[str, Any]] = {}
    for profile in result.get("profiles", []):
        reference = profiles_by_catalog.get(profile.get("catalog_id")) or {}
        for key in ("system_id", "width_mm", "height_mm", "slot_width_mm", "wall_thickness_mm", "weight_kg_m", "price_cny_per_m", "vendor_name", "designation"):
            if profile.get(key) is None and reference.get(key) is not None:
                profile[key] = reference[key]
        design_profiles[profile["id"]] = profile

    member_map = {item["id"]: item for item in result.get("members", [])}
    for joint in result.get("joints", []):
        connector = joint.setdefault("connector", {})
        if not connector.get("catalog_kit_id") and not connector.get("catalog_id"):
            system_ids = {
                design_profiles.get(member_map.get(mid, {}).get("profile_id"), {}).get("system_id")
                for mid in joint.get("member_ids", [])
            }
            system_ids.discard(None)
            if len(system_ids) == 1:
                system = systems[next(iter(system_ids))]
                kit_id = system["standard_joint_kit_id"]
                kit = kits[kit_id]
                connector.update(
                    catalog_kit_id=kit_id,
                    description=kit["name"],
                    connection_method=kit.get("connection_method", "exposed_angle_bracket"),
                    machining_required=bool(kit.get("machining_required", False)),
                    install_access=kit.get("install_access", "post_install"),
                    assembly_note=kit.get("assembly_note", "先定位，校方后复紧。"),
                )
        kit_id = connector.get("catalog_kit_id")
        kit = kits.get(kit_id) or {}
        if kit and not kit.get("machining_required", False):
            for mid in joint.get("member_ids", []):
                member = member_map.get(mid)
                if member and any("TBD" in str(op).upper() for op in member.get("machining", [])):
                    member["machining_status"] = "not_required"
                    member["machining"] = []

    system_ids = {profile.get("system_id") for profile in design_profiles.values() if profile.get("system_id")}
    selected_system = systems[next(iter(system_ids))] if len(system_ids) == 1 else None
    if selected_system:
        for item in result.get("accessories", []):
            if item.get("catalog_id") or item.get("catalog_kit_id"):
                continue
            key = {"foot": "foot_kit_id", "shelf_fastener": "shelf_kit_id", "panel_fastener": "panel_kit_id"}.get(item.get("category"))
            if key:
                item["catalog_kit_id"] = selected_system[key]
    result.setdefault("assembly_plan", build_assembly_plan(result, catalog))
    return result


def _range(table: dict[str, Any], key: str) -> tuple[float, float] | None:
    value = table.get(key)
    if isinstance(value, list) and len(value) == 2 and all(isinstance(x, (int, float)) for x in value):
        return float(value[0]), float(value[1])
    return None


def _add(rows: list[dict[str, Any]], section: str, item: str, qty: float, unit: str, price: tuple[float, float] | None, source: str, catalog_id: str = "") -> None:
    rows.append({
        "section": section, "item": item, "catalog_id": catalog_id, "qty": round(qty, 3), "unit": unit,
        "unit_price_range_cny": list(price) if price else None,
        "amount_range_cny": [round(qty * price[0], 2), round(qty * price[1], 2)] if price else None,
        "price_source": source,
    })


def build_quote_bundle(data: dict[str, Any], catalog: dict[str, Any], cut_plans: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    costing = data.get("costing") or {}
    profiles_by_id = {item["id"]: item for item in catalog.get("profiles", [])}
    products = {item["id"]: item for item in catalog.get("products", [])}
    kits = {item["id"]: item for item in catalog.get("kits", [])}
    design_profiles = {item["id"]: item for item in data.get("profiles", [])}
    profile_prices = costing.get("profile_unit_cost_ranges_cny_per_m") or {}
    item_prices = costing.get("catalog_unit_cost_ranges_cny_each") or {}
    area_prices = costing.get("panel_unit_cost_ranges_cny_m2") or {}
    category_prices = costing.get("category_unit_cost_ranges_cny_each") or {}
    processing_prices = costing.get("processing_unit_cost_ranges_cny") or {}
    rows: list[dict[str, Any]] = []

    for profile_id, bars in cut_plans.items():
        profile = design_profiles.get(profile_id) or {}
        reference = profiles_by_id.get(profile.get("catalog_id")) or {}
        stock_mm = float(profile.get("stock_length_mm") or max(reference.get("stock_length_options_mm") or [6000]))
        meters = len(bars) * stock_mm / 1000
        catalog_id = str(profile.get("catalog_id") or profile_id)
        price = _range(profile_prices, catalog_id)
        source = "方案预算区间"
        if price is None and reference.get("price_cny_per_m") is not None:
            value = float(reference["price_cny_per_m"])
            price, source = (value, value), f"目录快照 {reference.get('price_captured_on') or ''}".strip()
        _add(rows, "型材", reference.get("vendor_name") or reference.get("name") or catalog_id, meters, "米", price, source, catalog_id)

    joint_kits: Counter[str] = Counter()
    for joint in data.get("joints", []):
        connector = joint.get("connector") or {}
        kit_id = connector.get("catalog_kit_id")
        if kit_id:
            joint_kits[kit_id] += int(connector.get("qty") or 1)
    for kit_id, kit_qty in joint_kits.items():
        for component in (kits.get(kit_id) or {}).get("components", []):
            if component.get("optional"):
                continue
            product_id = component["product_id"]
            product = products.get(product_id) or {}
            qty = kit_qty * int(component.get("qty") or 1)
            _add(rows, "连接紧固件", product.get("name") or product_id, qty, "件", _range(item_prices, product_id), "方案预算区间", product_id)

    door_catalog_counts: Counter[str] = Counter()
    for door in data.get("doors", []):
        width = max(0.0, float(door["bounds"][1]) - float(door["bounds"][0]) - 2 * float(door.get("gap_mm") or 0))
        height = max(0.0, float(door["bounds"][3]) - float(door["bounds"][2]) - 2 * float(door.get("gap_mm") or 0))
        frame = float(door.get("frame_profile_mm") or 20)
        frame_id = str(door.get("frame_profile_catalog_id") or "")
        frame_m = (2 * width + 2 * max(0, height - 2 * frame)) / 1000
        if frame_id:
            price = _range(profile_prices, frame_id)
            reference = profiles_by_id.get(frame_id) or {}
            if price is None and reference.get("price_cny_per_m") is not None:
                value = float(reference["price_cny_per_m"]); price = (value, value)
            _add(rows, "门系统", f"{door.get('label', door.get('id'))}门框型材", frame_m, "米", price, "方案预算区间", frame_id)
        panel_id = str(door.get("panel_catalog_id") or "")
        panel_area = max(0, width - 2 * frame) * max(0, height - 2 * frame) / 1_000_000
        _add(rows, "门系统", f"{door.get('label', door.get('id'))}门板", panel_area, "平方米", _range(area_prices, panel_id), "方案预算区间", panel_id)
        for key, qty in (("hinge_catalog_id", int(door.get("hinge_qty") or 0)), ("handle_catalog_id", 1), ("catch_catalog_id", 1)):
            if door.get(key): door_catalog_counts[str(door[key])] += qty
    for catalog_id, qty in door_catalog_counts.items():
        _add(rows, "门系统", (products.get(catalog_id) or {}).get("name") or catalog_id, qty, "件", _range(item_prices, catalog_id), "方案预算区间", catalog_id)

    door_categories = {"door_panel", "door_hinge", "door_handle", "door_catch"}
    for item in data.get("accessories", []):
        category = str(item.get("category") or "accessory")
        if category in door_categories:
            continue
        catalog_id = str(item.get("catalog_id") or item.get("catalog_kit_id") or "")
        price = _range(item_prices, catalog_id) if catalog_id else _range(category_prices, category)
        _add(rows, "板材与附件", str(item.get("description") or category), float(item.get("qty") or 0), "件", price, "方案预算区间", catalog_id)

    body_cuts = sum(len(bar.get("cuts", [])) for bars in cut_plans.values() for bar in bars)
    door_cuts = len(data.get("doors", [])) * 4
    for key, qty, label in (("profile_cut", body_cuts, "主体型材切割"), ("door_frame_cut", door_cuts, "门框型材切割")):
        _add(rows, "加工", label, qty, "刀", _range(processing_prices, key), "方案预算区间")
    explicit_ops = sum(len(item.get("machining", [])) for item in data.get("members", []) if item.get("machining_status") == "specified")
    if explicit_ops:
        _add(rows, "加工", "钻孔/攻丝等明确加工", explicit_ops, "处", _range(processing_prices, "machining_operation"), "方案预算区间")

    shipping = _range(costing, "shipping_cost_range_cny")
    if shipping:
        _add(rows, "物流", "包装与运输", 1, "批", shipping, "方案预算区间")
    known = [row for row in rows if row["amount_range_cny"]]
    unknown = [row for row in rows if not row["amount_range_cny"]]
    subtotal = [round(sum(row["amount_range_cny"][i] for row in known), 2) for i in (0, 1)]
    contingency = float(costing.get("contingency_percent") or 0) / 100
    total = [round(value * (1 + contingency), 2) for value in subtotal]
    return {
        "currency": "CNY", "status": "complete_budget_range" if not unknown else "incomplete",
        "captured_on": costing.get("captured_on"), "rows": rows, "subtotal_range_cny": subtotal,
        "contingency_percent": contingency * 100, "total_range_cny": total,
        "unknown_items": [{"section": row["section"], "item": row["item"], "catalog_id": row["catalog_id"]} for row in unknown],
        "assumptions": costing.get("notes") or ["区间用于询价准备，不代替商家最终报价。"],
    }


def build_receipt_checklist(data: dict[str, Any], catalog: dict[str, Any], cut_plans: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    profiles = {item["id"]: item for item in catalog.get("profiles", [])}
    products = {item["id"]: item for item in catalog.get("products", [])}
    rows: list[dict[str, Any]] = []
    for design_profile in data.get("profiles", []):
        reference = profiles.get(design_profile.get("catalog_id")) or {}
        bars = (cut_plans or {}).get(design_profile.get("id"), [])
        rows.append({"category": "型材", "item": reference.get("vendor_name") or reference.get("name") or design_profile.get("catalog_id"), "catalog_id": design_profile.get("catalog_id"), "expected": f"{len(bars)} 根原料；{reference.get('width_mm')}×{reference.get('height_mm')} mm；槽 {reference.get('slot_width_mm')}；壁厚 {reference.get('wall_thickness_mm')} mm", "check": "卡尺核对外形、槽宽与壁厚；逐根核长度、划伤、压伤、弯曲和毛刺。"})
    kit_counts: Counter[str] = Counter()
    kits = {item["id"]: item for item in catalog.get("kits", [])}
    for joint in data.get("joints", []):
        connector = joint.get("connector") or {}
        if connector.get("catalog_kit_id"): kit_counts[connector["catalog_kit_id"]] += int(connector.get("qty") or 1)
    for kit_id, qty in kit_counts.items():
        rows.append({"category": "节点套装", "item": kits.get(kit_id, {}).get("name") or kit_id, "catalog_id": kit_id, "expected": f"{qty} 套；角码、螺栓、后装螺母数量成套", "check": "先拿一套与型材试装，确认定位凸台进槽、孔径和螺纹吻合。"})
    for door in data.get("doors", []):
        width = float(door["bounds"][1]) - float(door["bounds"][0]) - 2 * float(door.get("gap_mm") or 0)
        height = float(door["bounds"][3]) - float(door["bounds"][2]) - 2 * float(door.get("gap_mm") or 0)
        frame = float(door.get("frame_profile_mm") or 20)
        rows.append({"category": "门板", "item": door.get("label") or door.get("id"), "catalog_id": door.get("panel_catalog_id"), "expected": f"{round(width-2*frame)}×{round(height-2*frame)}×{door.get('panel_thickness_mm', 5)} mm，1 块", "check": "钢尺核对长宽，卡尺核厚度；检查崩边、翘曲与保护膜。"})
    rows.append({"category": "整批", "item": "数量与配套抽检", "catalog_id": "", "expected": "按清单分袋并标注", "check": "逐类点数；螺栓与螺母抽装；型材切口去毛刺；门板与框架先干装一扇。"})
    return rows


def build_assembly_plan(data: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    return {"access_status": "pass_post_install", "steps": [
        {"name": "完整结构", "copy": "先核对全部型材、板材、门件和五金，按编号分区摆放。", "check": "数量齐全，试装的一套角码、螺栓和后装螺母能够顺利配合。"},
        {"name": "第 1 步 · 底框", "copy": "拼装底部框架，螺栓只拧到能定位；量两条对角线校方。", "check": "两条对角线差不超过 2 mm，四角落地。"},
        {"name": "第 2 步 · 立柱", "copy": "安装外侧与分隔立柱；后装螺母可从槽口补入，不会因漏放而返工。", "check": "立柱垂直，分隔位置正确，连接件仍保留微调余量。"},
        {"name": "第 3 步 · 层梁与上框", "copy": "从下到上装层梁、台面框和上部框，每完成一层重新校方。", "check": "左右分格、层高和台面高度与确认尺寸一致。"},
        {"name": "第 4 步 · 板材与抗侧摆", "copy": "安装侧板、背板、台面和洞洞板；先固定四角，再由中间向外固定。", "check": "柜体无明显侧摆，板材不顶弯框架。"},
        {"name": "第 5 步 · 门板与脚轮", "copy": "先装合页再挂门，调四周缝；最后装把手、磁吸和脚轮。", "check": "门缝均匀、开启无干涉；至少两只脚轮带刹车且方向便于操作。"},
        {"name": "第 6 步 · 复紧与试载", "copy": "空载复紧所有节点，再从下到上逐步加载并观察。", "check": "结构不晃、连接不松、横梁无异常变形；移动前清空上部重物。"},
    ]}
