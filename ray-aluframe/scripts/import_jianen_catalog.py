#!/usr/bin/env python3
"""Import the curated Jianen Aluminum screenshot catalog into Ray Aluframe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CATALOG = Path(__file__).resolve().parents[1] / "references" / "product-catalog.json"
SUPPLIER_ID = "RAF-SUP-JIANEN"
CAPTURED_ON = "2026-07-15"
STOCK_LENGTH_MM = 6100


# image, page, vendor designation, width, height, wall, kg/m, finish, price CNY/m, nominal slot
ROWS = [
    (1305, 2, "欧标3030XQ-1.4", 30, 30, 1.4, 0.67, "页面未注明", 17.7, 8),
    (1306, 3, "欧标3030Q-1.5", 30, 30, 1.5, 0.67, "页面未注明", 16.7, 8),
    (1307, 4, "欧标3030Q-1.8", 30, 30, 1.8, 0.80, "页面未注明", None, 8),
    (1308, 5, "欧标3030JQ-1.8", 30, 30, 1.8, 0.75, "页面未注明", 19.2, 8),
    (1309, 6, "欧标3030Q-1.8喷砂银白", 30, 30, 1.8, 0.82, "喷砂银白", None, 8),
    (1310, 7, "欧标3030XL-2.0", 30, 30, 2.0, 0.86, "页面未注明", None, 8),
    (1311, 8, "欧标3030L-2.2", 30, 30, 2.2, 0.90, "页面未注明", None, 8),
    (1312, 9, "欧标3030Q-黑色", 30, 30, 1.8, 0.80, "黑色", None, 8),
    (1313, 10, "欧标3030LZ", 30, 30, 1.8, 0.82, "页面未注明", None, 8),
    (1314, 11, "欧标3030N1-单面封槽", 30, 30, 2.0, 0.95, "页面未注明", None, 8),
    (1315, 12, "欧标3030N2圆角", 30, 30, 2.2, 1.03, "页面未注明", None, 8),
    (1316, 13, "欧标3030N2直角", 30, 30, 1.6, 0.89, "页面未注明", 23.3, 8),
    (1317, 14, "欧标3030N2对面封槽", 30, 30, 2.0, 0.95, "页面未注明", 24.8, 8),
    (1318, 15, "欧标3030N3三面封槽", 30, 30, 2.0, 1.01, "页面未注明", None, 8),
    (1319, 16, "欧标3030R", 30, 30, 2.0, 0.93, "页面未注明", None, 8),
    (1320, 17, "欧标3060Q-1.6", 30, 60, 1.6, 1.29, "页面未注明", None, 8),
    (1321, 18, "欧标3060Q-1.8喷砂银白", 30, 60, 1.8, 1.48, "喷砂银白", None, 8),
    (1322, 19, "欧标3060L-2.2", 30, 60, 2.2, 1.62, "页面未注明", None, 8),
    (1323, 20, "欧标3060N1-60面封槽喷砂黑", 30, 60, 2.0, 1.64, "喷砂黑", None, 8),
    (1324, 21, "电白砂欧标3030Q-1.8", 30, 30, 1.8, 0.80, "电白砂", None, 8),
    (1325, 22, "欧标4040Q", 40, 40, 1.3, 0.94, "页面未注明", None, 8),
    (1326, 23, "欧标4040JQ-1.3", 40, 40, 1.3, 0.87, "页面未注明", None, 8),
    (1327, 24, "欧标4040A", 40, 40, 1.6, 1.00, "页面未注明", None, 8),
    (1328, 25, "欧标4040JL-2.0", 40, 40, 2.0, 1.09, "页面未注明", None, 8),
    (1329, 26, "欧标4040C", 40, 40, 2.0, 1.13, "页面未注明", None, 8),
    (1330, 27, "欧标4040L-1.5", 40, 40, 1.5, 0.98, "页面未注明", None, 8),
    (1331, 28, "欧标4040L", 40, 40, 2.0, 1.30, "页面未注明", None, 8),
    (1332, 29, "欧标4040JW", 40, 40, 3.0, 1.75, "页面未注明", None, 8),
    (1333, 30, "欧标4040JZ-2.5", 40, 40, 2.5, 1.53, "页面未注明", None, 8),
    (1334, 31, "欧标4040Z-2.5", 40, 40, 2.5, 1.69, "页面未注明", None, 8),
    (1335, 32, "欧标4040W", 40, 40, 3.0, 1.90, "页面未注明", None, 8),
    (1336, 33, "欧标4040W喷砂黑", 40, 40, 3.0, 1.90, "喷砂黑", None, 8),
    (1337, 34, "欧标4040DW-5.0", 40, 40, 5.0, 2.57, "页面未注明", None, 8),
    (1338, 35, "欧标4040LZ", 40, 40, 2.0, 1.33, "页面未注明", None, 8),
    (1339, 36, "欧标4040WZ直角", 40, 40, 2.5, 1.74, "页面未注明", None, 8),
    (1340, 37, "欧标4040Q喷砂黑", 40, 40, 1.3, 0.93, "喷砂黑", 26.7, 8),
    (1341, 38, "欧标4040C喷砂黑", 40, 40, 2.0, 1.08, "喷砂黑", None, 8),
    (1342, 39, "欧标4040L喷砂黑", 40, 40, 2.0, 1.30, "喷砂黑", None, 8),
    (1343, 40, "欧标4040R", 40, 40, 2.5, 1.42, "页面未注明", None, 8),
    (1344, 41, "欧标4040V双槽", 40, 40, 1.4, 1.33, "页面未注明", None, 6),
    (1345, 42, "欧标4040N1", 40, 40, 1.8, 1.24, "页面未注明", None, 8),
    (1346, 43, "欧标4040L-N2-6.8孔", 40, 40, 1.95, 1.28, "页面未注明", None, 8),
    (1347, 44, "欧标4040Z-N2-6.8孔", 40, 40, 2.5, 1.86, "页面未注明", None, 8),
    (1348, 45, "欧标4040N2-10.5", 40, 40, 1.95, 1.46, "页面未注明", None, 8),
    (1349, 46, "欧标4040N2对面封槽", 40, 40, 2.0, 1.29, "页面未注明", 33.8, 8),
    (1350, 47, "欧标4040N3-8.5孔", 40, 40, 3.0, 2.14, "页面未注明", 52.1, 8),
    (1351, 48, "欧标4080L-1.5", 40, 80, 1.5, 1.73, "页面未注明", 50.5, 8),
    (1352, 49, "欧标4080JL-2.0", 40, 80, 2.0, 2.05, "页面未注明", None, 8),
    (1353, 50, "欧标4080A-1.6", 40, 80, 1.6, 1.97, "页面未注明", None, 8),
    (1354, 51, "欧标4080C", 40, 80, 2.0, 2.18, "页面未注明", None, 8),
    (1355, 52, "欧标4080L", 40, 80, 2.0, 2.30, "页面未注明", None, 8),
    (1356, 53, "欧标4080Z-2.5", 40, 80, 2.5, 2.75, "页面未注明", None, 8),
    (1357, 54, "欧标4080W", 40, 80, 3.0, 3.35, "页面未注明", None, 8),
    (1358, 55, "欧标4080JW", 40, 80, 3.0, 3.17, "页面未注明", None, 8),
    (1359, 56, "欧标4080LZ直角", 40, 80, 2.0, 2.30, "页面未注明", None, 8),
    (1360, 57, "欧标4080L喷砂黑", 40, 80, 1.95, 2.25, "喷砂黑", None, 8),
    (1361, 58, "欧标4080WZ直角", 40, 80, 2.5, 2.91, "页面未注明", None, 8),
    (1362, 59, "欧标4080W喷砂黑", 40, 80, 2.8, 3.36, "喷砂黑", None, 8),
    (1363, 60, "欧标3560", 35, 60, 2.2, 1.771, "页面未注明", None, 8),
]


BORE_OVERRIDES = {
    1346: 6.8,
    1347: 6.8,
    1348: 10.5,
    1350: 8.5,
}


def build_profile(row: tuple[Any, ...]) -> dict[str, Any]:
    image_no, page, vendor_name, width, height, wall, weight, finish, price, slot = row
    full_stick_weight = round(weight * (STOCK_LENGTH_MM / 1000), 3)
    full_stick_price = round(price * (STOCK_LENGTH_MM / 1000), 2) if price is not None else None
    designation = vendor_name.removeprefix("欧标").removeprefix("电白砂欧标")
    return {
        "id": f"RAF-JN-{image_no}",
        "kind": "profile",
        "designation": designation,
        "name": vendor_name,
        "vendor_name": vendor_name,
        "supplier_id": SUPPLIER_ID,
        "system_id": None,
        "series": 30 if width == 30 else 40 if width == 40 else width,
        "width_mm": width,
        "height_mm": height,
        "diameter_mm": None,
        "slot_width_mm": slot,
        "slot_depth_mm": None,
        "center_bore_mm": BORE_OVERRIDES.get(image_no),
        "wall_thickness_mm": wall,
        "weight_kg_m": weight,
        "full_stick_weight_kg": full_stick_weight,
        "stock_length_options_mm": [STOCK_LENGTH_MM],
        "finish": finish,
        "price_cny_per_m": price,
        "full_stick_price_cny": full_stick_price,
        "price_unit": "CNY_per_meter",
        "price_status": "captured" if price is not None else "not_loaded_in_source_snapshot",
        "price_captured_on": CAPTURED_ON if price is not None else None,
        "source_snapshot": f"IMG_{image_no}.PNG",
        "source_page": page,
        "engineering_reference": None,
        "data_status": "supplier_geometry_and_mass",
        "engineering_use": "not_for_load_calculation",
    }


def main() -> None:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    catalog["profiles"] = [
        item for item in catalog["profiles"] if item.get("supplier_id") != SUPPLIER_ID
    ]
    catalog.setdefault("suppliers", [])
    catalog["suppliers"] = [
        item for item in catalog["suppliers"] if item.get("id") != SUPPLIER_ID
    ]
    catalog["suppliers"].append(
        {
            "id": SUPPLIER_ID,
            "name": "建恩铝业",
            "catalog_type": "saved_supplier_snapshot",
            "captured_on": CAPTURED_ON,
            "source_pages": "2-60",
            "source_snapshot_count": len(ROWS),
            "default_stock_length_mm": STOCK_LENGTH_MM,
            "price_unit": "CNY_per_meter",
            "price_note": "商品页价格按元/米记录；整支价按 6.1 米计算。未加载价格保持为空。",
            "compatibility_note": "商家后缀保留原样；未完成实物配合验证前，不自动绑定通用连接件套装。",
        }
    )
    catalog["profiles"].extend(build_profile(row) for row in ROWS)
    catalog["catalog_version"] = "2026.07.15-2"
    catalog["built_on"] = CAPTURED_ON
    catalog["coverage"]["profiles_and_shafts"] = len(catalog["profiles"])
    catalog["coverage"]["supplier_profiles"] = len(ROWS)
    rules = catalog.setdefault("data_rules", [])
    supplier_rule = "供应商价格是采集快照，统一按元/米保存；整支长度按 6100 mm 计算，未显示价格的页面不推测。"
    if supplier_rule not in rules:
        rules.append(supplier_rule)
    supplier_rule_2 = "供应商壁厚和米重可用于选型比较，但没有惯性参数时不得用于承载或挠度计算。"
    if supplier_rule_2 not in rules:
        rules.append(supplier_rule_2)
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(ROWS)} Jianen profiles into {CATALOG}")


if __name__ == "__main__":
    main()
