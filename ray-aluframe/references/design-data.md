# 设计数据格式

## 目录

1. 顶层结构
2. 型材
3. 构件
4. 节点
5. 载荷
6. 附件与加工
7. 参考图拓扑
8. 外观可视化
9. 可编辑尺寸与门板系统
10. 就绪判定

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
  "reference_image": {},
  "reference_topology": {},
  "visuals": []
}
```

坐标、长度统一用毫米;载荷由脚本把 kg 转为 N。坐标采用 `[x, y, z]`:从柜门侧正视时,x 从左到右,y 从柜门/台面外沿指向背板/墙面,z 从地面向上。默认正面为 y 的较小值一侧,常用 `front_plane_y_mm=0`;不得用相机镜像掩盖前后坐标写反。

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
  "evidence_basis": "visible",
  "evidence_confidence": "high",
  "evidence_note": "参考图正面可直接看到",
  "machining": [
    {"end": "A", "operation": "TBD after connector selection"}
  ]
}
```

脚本从坐标计算长度。首版只接受平行于 x/y/z 轴的直杆。斜撑可先作为附件说明,或在后续扩展中支持。

从参考图还原的设计还要为每个构件标注识别依据:`visible` 表示原图直接可见,`inferred` 表示为了形成完整结构而推测,`confirmed` 表示用户用尺寸、多角度照片或明确回复确认。置信度使用 `high`、`medium`、`low`;推测项必须在 `evidence_note` 说明依据。

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

## 7. 参考图拓扑

从参考图还原时,先把正面可见分区写成可核对数据。它约束“几列、每列几格”,避免整体轮廓相似但柜门、抽屉或层数认错:

```json
{
  "reference_image": {
    "path": "/absolute/path/reference.jpg",
    "label": "咖啡柜参考图",
    "default_opacity": 48,
    "object_fit": "contain",
    "mirror_x": false,
    "transform": {"scale": 1, "translate_x_pct": 0, "translate_y_pct": 0}
  },
  "reference_topology": {
    "front_plane_y_mm": 0,
    "regions": [
      {
        "id": "LOWER-LEFT",
        "label": "下柜左侧",
        "x_range_mm": [0, 780],
        "z_range_mm": [80, 900],
        "expected_rows": 3,
        "side_label": "参考图左侧",
        "confidence": "high"
      },
      {
        "id": "LOWER-RIGHT",
        "label": "下柜右侧",
        "x_range_mm": [780, 1200],
        "z_range_mm": [80, 900],
        "expected_rows": 1,
        "side_label": "参考图右侧",
        "confidence": "high"
      }
    ]
  }
}
```

`reference_image.path` 可用绝对路径,也可相对设计 JSON 所在目录。生成交互预览时图片会嵌入 HTML,成品文件不再依赖原路径。`default_opacity` 控制校对模式初始透明度;`mirror_x` 只在原图确实被镜像时使用。`transform` 用于轻微平移和缩放,不得用它伪装透视已经精确校准。

`x_range_mm` 和 `z_range_mm` 是该正面区域的边界。`expected_rows` 由参考图中明确可见的水平分格得到。脚本只统计位于正面、横跨整个区域、且处于上下边界之间的横向构件。无法看清时使用 `confidence=medium/low`,并在交付前请用户确认,不得把推测写成高置信度事实。

## 8. 外观可视化

为生成接近实物的装配效果图,可选填 `visuals`。它只描述外观,不能代替采购清单:

```json
{
  "type": "panel",
  "id": "SHELF-L1",
  "corners": [[0, 0, 150], [600, 0, 150], [600, 350, 150], [0, 350, 150]],
  "fill": "#d8c6a5",
  "edge": "#8d765b",
  "opacity": 0.95,
  "evidence_basis": "inferred",
  "evidence_confidence": "medium",
  "evidence_note": "原图显示门板边界,内部层板为结构推测"
}
```

调节脚使用 `{"type":"leveling_foot","at":[0,0,0],"stem_mm":35,"pad_diameter_mm":42}`。脚轮使用 `{"type":"caster","at":[0,0,80],"stem_mm":28,"wheel_diameter_mm":65,"wheel_width_mm":24}`。面板洞孔仅作效果时可加 `"pattern":"pegboard"`。`visuals` 中出现的物件仍必须在 `accessories` 中有对应采购项。

## 9. 可编辑尺寸与门板系统

需要用户在交互预览中直接改尺寸时,增加 `editable`。只有显式声明了可编辑规则的方案才显示修改入口,不要对任意结构做无依据的整体拉伸。首个支持布局是左右分区柜体:

```json
{
  "editable": {
    "enabled": true,
    "layout": "split_cabinet_v1",
    "fields": [
      {"id":"width_mm","label":"总宽","unit":"mm","value":1200,"min":800,"max":2400,"step":10},
      {"id":"depth_mm","label":"深度","unit":"mm","value":600,"min":300,"max":1000,"step":10},
      {"id":"height_mm","label":"总高","unit":"mm","value":1900,"min":1200,"max":2600,"step":10},
      {"id":"divider_mm","label":"左侧分隔宽","unit":"mm","value":780,"min":350,"max":900,"step":10},
      {"id":"level_count","label":"左侧层数","unit":"层","value":3,"min":1,"max":6,"step":1},
      {"id":"level_height_mm","label":"左侧层高","unit":"mm","value":273,"min":180,"max":500,"step":5}
    ],
    "anchors": {
      "base_z_mm": 80,
      "cabinet_top_z_mm": 900,
      "overall_height_mm": 1900,
      "front_y_mm": 0,
      "rear_y_mm": 600,
      "divider_x_mm": 780
    },
    "dynamic_member_group": "left_layers",
    "profile_id": "P-MAIN",
    "minimum_right_bay_mm": 300,
    "minimum_upper_zone_mm": 300
  }
}
```

可变层横梁必须写 `editable_group`,页面重算时删除旧层位并按层数和层高重新生成。页面同时重算节点、主体下料、门框下料、门板开料和门五金数量;承载、稳定性和正式采购就绪状态仍需把修改后的数据重新交给检查脚本,不得在浏览器里伪装为已经复核。

门板用独立的 `doors` 表达,不要继续把会开启的门当作普通固定面板:

```json
{
  "id": "DOOR-RIGHT",
  "label": "右侧通高侧开门",
  "bounds": [780, 1200, 80, 900],
  "front_y_mm": -10,
  "gap_mm": 4,
  "frame_profile_catalog_id": "RAF-P-2020",
  "frame_profile_mm": 20,
  "panel_catalog_id": "RAF-B-PC-FLUTED-5",
  "panel_thickness_mm": 5,
  "opening": "side_hinged",
  "hinge_edge": "right",
  "hinge_catalog_id": "RAF-D-HINGE-40X40",
  "hinge_qty": 3,
  "handle_catalog_id": "RAF-D-KNOB-25",
  "handle_position": "left_center",
  "catch_catalog_id": "RAF-D-MAGNET-45",
  "catch_position": "left_center",
  "evidence_basis": "confirmed",
  "evidence_confidence": "high",
  "evidence_note": "参考图右边缘可见合页"
}
```

`bounds` 依次为正视图的左、右、下、上边界。门板实际开料尺寸由边界、四周间隙和门框宽度共同计算。`opening` 首版支持 `drop_down` 和 `side_hinged`;必须同时给出合页边、合页数量、把手和闭合件。材料默认从本目录的 PC、亚克力或木板条目选择,不得只写“透明板”。

## 10. 就绪判定

- **草案**:数据或几何有错误,无法完成检查。
- **待复核**:结构可表达,但仍有本目录编号、连接、加工、强度、载荷或稳定措施未确认。
- **可询价**:几何完整、横梁初查未失败、型材/连接件/附件已绑定本目录、没有 TBD,下料与数量可汇总。
- **受限模式**:载人、吊装、护栏等高风险用途,仅供专业复核与沟通。

“可询价”不等于“已证明安全”或“可无人复核直接制作”。
