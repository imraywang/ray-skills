#!/usr/bin/env python3
"""Validate Ray Aluframe catalog IDs, compatibility, and complete kits."""

from __future__ import annotations

import json
from pathlib import Path


CATALOG = Path(__file__).resolve().parents[1] / "references" / "product-catalog.json"


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    groups = [
        catalog.get("suppliers", []),
        catalog.get("systems", []),
        catalog.get("profiles", []),
        catalog.get("products", []),
        catalog.get("kits", []),
    ]
    ids = [item["id"] for group in groups for item in group]
    errors: list[str] = []
    if len(ids) != len(set(ids)):
        errors.append("目录编号存在重复")
    product_ids = {item["id"] for item in catalog.get("products", [])}
    kit_ids = {item["id"] for item in catalog.get("kits", [])}
    profile_ids = {item["id"] for item in catalog.get("profiles", [])}
    supplier_ids = {item["id"] for item in catalog.get("suppliers", [])}

    for kit in catalog.get("kits", []):
        for component in kit.get("components", []):
            if component.get("product_id") not in product_ids:
                errors.append(f"{kit['id']}: 引用了不存在的产品 {component.get('product_id')}")
            if int(component.get("qty") or 0) <= 0:
                errors.append(f"{kit['id']}: 组件数量无效")
    for product in catalog.get("products", []):
        for component in product.get("fastener_components", []):
            if component.get("product_id") not in product_ids:
                errors.append(f"{product['id']}: 紧固件引用无效 {component.get('product_id')}")
            if int(component.get("qty") or 0) <= 0:
                errors.append(f"{product['id']}: 紧固件数量无效")
    for system in catalog.get("systems", []):
        for key in ("standard_joint_kit_id", "shelf_kit_id", "panel_kit_id", "foot_kit_id"):
            if system.get(key) not in kit_ids:
                errors.append(f"{system['id']}: {key} 无效")
    for designation in ("2020", "2040", "3030", "3060", "3090", "4040", "4080"):
        if f"RAF-P-{designation}" not in profile_ids:
            errors.append(f"缺少常用型材 {designation}")
        else:
            profile = next(item for item in catalog["profiles"] if item["id"] == f"RAF-P-{designation}")
            if not profile.get("engineering_reference"):
                errors.append(f"常用型材 {designation} 缺少米重和惯性参数")
    serialized_runtime_data = json.dumps(groups, ensure_ascii=False)
    if "http://" in serialized_runtime_data or "https://" in serialized_runtime_data:
        errors.append("运行目录中不应包含外部链接")
    engineering_count = sum(bool(item.get("engineering_reference")) for item in catalog.get("profiles", []))
    if engineering_count != catalog.get("coverage", {}).get("engineering_reference_profiles"):
        errors.append("带计算参数的型材数量与覆盖摘要不一致")

    supplier_profiles = [item for item in catalog.get("profiles", []) if item.get("supplier_id")]
    if len(supplier_profiles) != catalog.get("coverage", {}).get("supplier_profiles"):
        errors.append("供应商型材数量与覆盖摘要不一致")
    source_snapshots: set[tuple[str, str]] = set()
    for profile in supplier_profiles:
        prefix = profile["id"]
        if profile.get("supplier_id") not in supplier_ids:
            errors.append(f"{prefix}: 供应商编号无效")
        if float(profile.get("wall_thickness_mm") or 0) <= 0:
            errors.append(f"{prefix}: 壁厚无效")
        if float(profile.get("weight_kg_m") or 0) <= 0:
            errors.append(f"{prefix}: 米重无效")
        if profile.get("stock_length_options_mm") != [6100]:
            errors.append(f"{prefix}: 整支长度不是 6100 mm")
        expected_weight = round(float(profile["weight_kg_m"]) * 6.1, 3)
        if profile.get("full_stick_weight_kg") != expected_weight:
            errors.append(f"{prefix}: 整支重量计算不一致")
        price = profile.get("price_cny_per_m")
        if price is not None:
            if profile.get("price_unit") != "CNY_per_meter":
                errors.append(f"{prefix}: 价格单位不是元/米")
            if profile.get("full_stick_price_cny") != round(float(price) * 6.1, 2):
                errors.append(f"{prefix}: 整支价格计算不一致")
            if profile.get("price_status") != "captured":
                errors.append(f"{prefix}: 已记录价格但状态不正确")
        elif profile.get("full_stick_price_cny") is not None:
            errors.append(f"{prefix}: 无米价却存在整支价格")
        if profile.get("engineering_reference") is not None:
            errors.append(f"{prefix}: 供应商页没有惯性参数，不应标记为承载参考")
        if profile.get("engineering_use") != "not_for_load_calculation":
            errors.append(f"{prefix}: 缺少不得用于承载计算的限制")
        source_snapshot = profile.get("source_snapshot")
        if not source_snapshot or not profile.get("source_page"):
            errors.append(f"{prefix}: 缺少来源页")
        else:
            source_key = (str(profile.get("supplier_id") or ""), str(source_snapshot))
            if source_key in source_snapshots:
                errors.append(f"{prefix}: 来源图片重复 {source_snapshot}")
            else:
                source_snapshots.add(source_key)
    for supplier in catalog.get("suppliers", []):
        expected = int(supplier.get("source_snapshot_count") or 0)
        actual = sum(profile.get("supplier_id") == supplier["id"] for profile in supplier_profiles)
        if expected != actual:
            errors.append(f"{supplier['id']}: 商品页数量 {expected} 与型号数量 {actual} 不一致")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        f"OK: {len(catalog['profiles'])} 型材/光轴（含 {len(supplier_profiles)} 个供应商型号），{len(catalog['products'])} 标准配件，"
        f"{len(catalog['kits'])} 完整套装，{len(catalog['systems'])} 个默认体系"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
