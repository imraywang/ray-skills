#!/usr/bin/env python3
"""Validate Ray Aluframe catalog IDs, compatibility, and complete kits."""

from __future__ import annotations

import json
from pathlib import Path


CATALOG = Path(__file__).resolve().parents[1] / "references" / "product-catalog.json"


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    groups = [catalog.get("systems", []), catalog.get("profiles", []), catalog.get("products", []), catalog.get("kits", [])]
    ids = [item["id"] for group in groups for item in group]
    errors: list[str] = []
    if len(ids) != len(set(ids)):
        errors.append("目录编号存在重复")
    product_ids = {item["id"] for item in catalog.get("products", [])}
    kit_ids = {item["id"] for item in catalog.get("kits", [])}
    profile_ids = {item["id"] for item in catalog.get("profiles", [])}

    for kit in catalog.get("kits", []):
        for component in kit.get("components", []):
            if component.get("product_id") not in product_ids:
                errors.append(f"{kit['id']}: 引用了不存在的产品 {component.get('product_id')}")
            if int(component.get("qty") or 0) <= 0:
                errors.append(f"{kit['id']}: 组件数量无效")
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

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        f"OK: {len(catalog['profiles'])} 型材/光轴，{len(catalog['products'])} 标准配件，"
        f"{len(catalog['kits'])} 完整套装，{len(catalog['systems'])} 个默认体系"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
