#!/usr/bin/env python3
"""Idempotently add the common connection, base, caster, and door product families."""

from __future__ import annotations

import json
from pathlib import Path


CATALOG = Path(__file__).resolve().parents[1] / "references" / "product-catalog.json"


def product(product_id: str, name: str, category: str, **fields: object) -> dict[str, object]:
    return {
        "id": product_id,
        "name": name,
        "category": category,
        "data_status": "functional_spec_supplier_confirm",
        "purchase_note": "按本目录规格询价；下单前让商家确认槽系、螺纹、安装空间和实际额定值。",
        **fields,
    }


PRODUCTS = [
    product("RAF-F-BOLT-M4X12", "M4×12 内六角螺栓", "fastener", thread="M4", length_mm=12),
    product("RAF-F-BOLT-M5X10", "M5×10 内六角螺栓", "fastener", thread="M5", length_mm=10),
    product("RAF-F-TNUT-6-M4", "槽 6 后装螺母 M4", "fastener", thread="M4", slot_width_mm=6),
    product("RAF-F-TNUT-8-M5", "槽 8 后装螺母 M5", "fastener", thread="M5", slot_width_mm=8),
    product("RAF-C-ANCHOR-20-6", "20 系槽 6 内置锚式连接件", "internal_connector", series=20, slot_width_mm=6, machining="端面中心孔攻丝并按连接件要求开工艺孔"),
    product("RAF-C-ANCHOR-30-8", "30 系槽 8 内置锚式连接件", "internal_connector", series=30, slot_width_mm=8, machining="端面中心孔攻丝并按连接件要求开工艺孔"),
    product("RAF-C-ANCHOR-40-8", "40 系槽 8 内置锚式连接件", "internal_connector", series=40, slot_width_mm=8, machining="端面中心孔攻丝并按连接件要求开工艺孔"),
    product("RAF-C-END-20-6", "20 系槽 6 端面连接件", "end_connector", series=20, slot_width_mm=6, machining="端面中心孔攻丝"),
    product("RAF-C-END-30-8", "30 系槽 8 端面连接件", "end_connector", series=30, slot_width_mm=8, machining="端面中心孔攻丝"),
    product("RAF-C-END-40-8", "40 系槽 8 端面连接件", "end_connector", series=40, slot_width_mm=8, machining="端面中心孔攻丝"),
    product("RAF-C-FLAT-20", "20 系两孔平连接片", "flat_plate", series=20, fastener_components=[{"product_id": "RAF-F-BOLT-M5X8", "qty": 2}, {"product_id": "RAF-F-TNUT-6-M5", "qty": 2}]),
    product("RAF-C-FLAT-30", "30 系两孔平连接片", "flat_plate", series=30, fastener_components=[{"product_id": "RAF-F-BOLT-M6X12", "qty": 2}, {"product_id": "RAF-F-TNUT-8-M6", "qty": 2}]),
    product("RAF-C-FLAT-40", "40 系两孔平连接片", "flat_plate", series=40, fastener_components=[{"product_id": "RAF-F-BOLT-M6X12", "qty": 2}, {"product_id": "RAF-F-TNUT-8-M6", "qty": 2}]),
    product("RAF-A-LEVEL-M8", "M8 橡胶调节脚", "leveling_foot", thread="M8"),
    product("RAF-A-LEVEL-M10", "M10 橡胶调节脚", "leveling_foot", thread="M10"),
    product("RAF-A-LEVEL-M12", "M12 橡胶调节脚", "leveling_foot", thread="M12"),
    product("RAF-A-FLOOR-ANCHOR-30", "30 系落地固定片", "floor_anchor", series=30, installation="型材槽固定；地面锚栓按地面材质另选"),
    product("RAF-A-FLOOR-ANCHOR-40", "40 系落地固定片", "floor_anchor", series=40, installation="型材槽固定；地面锚栓按地面材质另选"),
    product("RAF-A-CASTER-50-BRAKE", "50 mm 平板刹车脚轮", "caster", wheel_diameter_mm=50, rated_load_kg_each=None, rating_status="supplier_required"),
    product("RAF-A-CASTER-75-BRAKE", "75 mm 平板刹车脚轮", "caster", wheel_diameter_mm=75, rated_load_kg_each=None, rating_status="supplier_required"),
    product("RAF-A-CASTER-100-BRAKE", "100 mm 平板刹车脚轮", "caster", wheel_diameter_mm=100, rated_load_kg_each=None, rating_status="supplier_required"),
    product("RAF-A-CASTER-PLATE-30", "30 系脚轮转接板", "caster_adapter", series=30, bolt_pattern="按所选脚轮底板复核"),
    product("RAF-A-CASTER-PLATE-40", "40 系脚轮转接板", "caster_adapter", series=40, bolt_pattern="按所选脚轮底板复核"),
    product("RAF-D-CAM-LOCK", "柜门转舌锁", "door_lock", panel_thickness_range_mm=[3, 12], fastener_components=[{"product_id": "RAF-F-BOLT-M4X12", "qty": 2}]),
    product("RAF-D-ROLLER-CATCH", "柜门滚轮碰珠", "door_catch", fastener_components=[{"product_id": "RAF-F-BOLT-M4X12", "qty": 2}, {"product_id": "RAF-F-TNUT-6-M4", "qty": 2}]),
    product("RAF-D-LIMIT-CHAIN", "下翻门双侧限位链", "door_restraint", configuration="左右各一条", fastener_components=[{"product_id": "RAF-F-BOLT-M4X12", "qty": 4}, {"product_id": "RAF-F-TNUT-6-M4", "qty": 4}]),
    product("RAF-D-GAS-STRUT-ADJ", "下翻门可调支撑杆", "door_restraint", force_selection="按门板重量与支点位置计算后选型", fastener_components=[{"product_id": "RAF-F-BOLT-M4X12", "qty": 4}, {"product_id": "RAF-F-TNUT-6-M4", "qty": 4}]),
    product("RAF-D-SLIDE-RAIL", "双槽推拉门导轨", "sliding_door_rail", length="按门洞净宽裁切", panel_thickness_range_mm=[4, 6]),
    product("RAF-D-PANEL-GASKET-6", "槽 6 板材嵌条", "panel_gasket", slot_width_mm=6, panel_thickness_range_mm=[3, 6]),
    product("RAF-D-PANEL-GASKET-8", "槽 8 板材嵌条", "panel_gasket", slot_width_mm=8, panel_thickness_range_mm=[4, 8]),
    product("RAF-D-BRUSH-SEAL", "柜门防尘毛条", "door_seal", length="按门周长裁切"),
]


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in catalog.get("products", [])}
    for item in PRODUCTS:
        items[item["id"]] = item

    door_updates = {
        "RAF-D-HINGE-40X40": [{"product_id": "RAF-F-BOLT-M5X8", "qty": 4}, {"product_id": "RAF-F-TNUT-6-M5", "qty": 4}],
        "RAF-D-KNOB-25": [{"product_id": "RAF-F-BOLT-M4X12", "qty": 1}],
        "RAF-D-MAGNET-45": [{"product_id": "RAF-F-BOLT-M4X12", "qty": 2}, {"product_id": "RAF-F-TNUT-6-M4", "qty": 2}],
    }
    for product_id, components in door_updates.items():
        if product_id in items:
            items[product_id]["fastener_components"] = components
            items[product_id].setdefault("data_status", "catalog_geometry")

    catalog["products"] = sorted(items.values(), key=lambda item: item["id"])
    catalog["catalog_version"] = "2026.07.15-5"
    catalog["coverage"]["standard_products"] = len(catalog["products"])
    rule = "脚轮和支撑杆等额定能力不得按外形推测；目录给出选型位置，但最终额定值必须来自具体商品并写入方案。"
    if rule not in catalog["data_rules"]:
        catalog["data_rules"].append(rule)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: 标准产品扩充为 {len(catalog['products'])} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
