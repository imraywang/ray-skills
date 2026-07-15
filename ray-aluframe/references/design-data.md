# 设计数据格式

## 目录

1. 顶层结构
2. 型材
3. 构件
4. 节点
5. 载荷
6. 附件与加工
7. 就绪判定

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
  "accessories": []
}
```

坐标、长度统一用毫米;载荷由脚本把 kg 转为 N。坐标采用 `[x, y, z]`,z 轴向上。

`checks` 不能省略。它分别说明重量如何传到地面、如何防止矩形框侧摆、如何防止高架或带轮结构倾倒。写 `TBD` 可以保存草案,但会阻止“可询价”。`risk_level=high` 时报告固定进入受限模式。

## 2. 型材

```json
{
  "id": "P3030",
  "manufacturer": "MayTec",
  "series": "PG30",
  "part_number": "1.11.030030.43LP",
  "description": "30x30 4F light plain",
  "width_mm": 30,
  "height_mm": 30,
  "weight_kg_m": 0.9,
  "stock_length_mm": 6000,
  "e_mpa": 69000,
  "ix_mm4": 33000,
  "iy_mm4": 33000,
  "wx_mm3": null,
  "wy_mm3": null,
  "yield_mpa": null,
  "source_url": "https://...",
  "verified_on": "2026-07-14",
  "assumptions": ["e_mpa is a screening assumption; alloy/temper not stated on product page"]
}
```

`I` 从 cm^4 换算到 mm^4 时乘 `10,000`。若产品页未给 `E` 或屈服强度,可以为变形比较显式填入假设,但强度必须保持未检查。

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
    "manufacturer": "TBD",
    "part_number": "TBD_VENDOR_SELECTION",
    "description": "3-way corner connection",
    "qty": 1,
    "source_url": ""
  }
}
```

节点坐标必须落在所引用构件上。`TBD` 允许概念设计继续,但会阻止“可询价”判定。

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
  "manufacturer": "TBD",
  "part_number": "TBD_VENDOR_SELECTION",
  "description": "adjustable foot",
  "qty": 4,
  "source_url": ""
}
```

层板、脚轮、端盖、槽盖、把手和墙地固定件都放在附件。孔位必须绑定到构件编号,包含距端面、所在面、孔径、深度/贯穿和螺纹规格。

## 7. 就绪判定

- **草案**:数据或几何有错误,无法完成检查。
- **待复核**:结构可表达,但仍有厂商货号、连接、加工、强度、载荷或稳定措施未确认。
- **可询价**:几何完整、横梁初查未失败、型材/连接件/附件有来源、没有 TBD,下料与数量可汇总。
- **受限模式**:载人、吊装、护栏等高风险用途,仅供专业复核与沟通。

“可询价”不等于“已证明安全”或“可无人复核直接制作”。
