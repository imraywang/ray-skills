# 设计数据格式

## 目录

1. 顶层结构
2. 型材
3. 构件
4. 节点
5. 载荷
6. 附件与加工
7. 外观可视化
8. 就绪判定

## 1. 顶层结构

```json
{
  "project": {"name": "...", "revision": "A", "risk_level": "medium"},
  "settings": {"kerf_mm": 3, "end_trim_mm_each": 5},
  "checks": {"load_path": "...", "lateral_stability": "...", "tip_over": "..."},
  "profiles": [],
  "members": [],
  "joints": [],
  "ground_points": [],
  "loads": [],
  "accessories": [],
  "visuals": []
}
```

坐标、长度统一用毫米;载荷由脚本把 kg 转为 N。坐标采用 `[x, y, z]`,z 轴向上。

`checks` 不能省略。它分别说明重量如何传到地面、如何防止矩形框侧摆、如何防止高架或带轮结构倾倒。写 `TBD` 可以保存草案,但会阻止“可询价”。`risk_level=high` 时报告固定进入受限模式。

## 2. 型材

```json
{
  "id": "P3030",
  "catalog_id": "RAF-P-3030",
  "stock_length_mm": 6000,
  "wx_mm3": null,
  "wy_mm3": null,
  "yield_mpa": null,
  "assumptions": ["米重和惯性使用本目录的轻型参考截面；收到实际商品截面参数后覆盖"]
}
```

脚本根据 `catalog_id` 补齐外形、槽宽、米重和已有的惯性参考。若实际商品参数不同,在设计内覆盖对应字段并写入 `assumptions`。没有截面模量或材料强度时,强度必须保持未检查。

## 3. 构件

```json
{
  "id": "L1-FRONT",
  "profile_id": "P3030",
  "role": "level beam",
  "start": [0, 0, 150],
  "end": [1200, 0, 150],
  "machining": [
    {"end": "A", "operation": "TBD after connector selection"}
  ]
}
```

脚本从坐标计算长度。首版只接受平行于 x/y/z 轴的直杆。斜撑可先作为附件说明,或在后续扩展中支持。

## 4. 节点

```json
{
  "id": "J-L1-FL",
  "at": [0, 0, 150],
  "member_ids": ["POST-FL", "L1-FRONT", "L1-LEFT"],
  "connector": {
    "catalog_kit_id": "RAF-KIT-JOINT-30-8-M6",
    "description": "30 系槽 8 标准直角节点套装",
    "qty": 1
  }
}
```

节点坐标必须落在所引用构件上。本目录编号无效或缺失会阻止“可询价”判定。

## 5. 载荷

```json
{
  "id": "LOAD-L1-FRONT",
  "member_id": "L1-FRONT",
  "mass_kg": 25,
  "distribution": "uniform",
  "support": "simply_supported",
  "inertia_axis": "y",
  "safety_factor": 1.5,
  "dynamic_factor": 1.0,
  "deflection_limit_ratio": 200
}
```

一层重量由前后两根长梁平均承担时,每根梁填一半。不能确定分担比例时采用更不利分配并写入假设。支持:

- `distribution`: `center_point` / `uniform`
- `support`: `simply_supported` / `fixed_fixed` / `cantilever`
- `inertia_axis`: `x` / `y`

## 6. 附件与加工

```json
{
  "category": "foot",
  "catalog_kit_id": "RAF-KIT-FOOT-30",
  "description": "30 系调平底脚套装",
  "qty": 4
}
```

层板、脚轮、端盖、槽盖、把手和墙地固定件都放在附件。孔位必须绑定到构件编号,包含距端面、所在面、孔径、深度/贯穿和螺纹规格。

## 7. 外观可视化

为生成接近实物的装配效果图,可选填 `visuals`。它只描述外观,不能代替采购清单:

```json
{
  "type": "panel",
  "id": "SHELF-L1",
  "corners": [[0, 0, 150], [600, 0, 150], [600, 350, 150], [0, 350, 150]],
  "fill": "#d8c6a5",
  "edge": "#8d765b",
  "opacity": 0.95
}
```

调节脚使用 `{"type":"leveling_foot","at":[0,0,0],"stem_mm":35,"pad_diameter_mm":42}`。脚轮使用 `{"type":"caster","at":[0,0,80],"stem_mm":28,"wheel_diameter_mm":65,"wheel_width_mm":24}`。面板洞孔仅作效果时可加 `"pattern":"pegboard"`。`visuals` 中出现的物件仍必须在 `accessories` 中有对应采购项。

## 8. 就绪判定

- **草案**:数据或几何有错误,无法完成检查。
- **待复核**:结构可表达,但仍有本目录编号、连接、加工、强度、载荷或稳定措施未确认。
- **可询价**:几何完整、横梁初查未失败、型材/连接件/附件已绑定本目录、没有 TBD,下料与数量可汇总。
- **受限模式**:载人、吊装、护栏等高风险用途,仅供专业复核与沟通。

“可询价”不等于“已证明安全”或“可无人复核直接制作”。
