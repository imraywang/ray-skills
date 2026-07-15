#!/usr/bin/env python3
"""Generate a MayCAD-style construction PDF from a ray-aluframe design JSON."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_frame import axis_and_length, validate  # noqa: E402


BLUE = colors.HexColor("#1769AA")
DARK = colors.HexColor("#17324D")
TEXT = colors.HexColor("#243447")
MUTED = colors.HexColor("#66788A")
LIGHT = colors.HexColor("#EAF2F8")
PALE = colors.HexColor("#F6F9FC")
ORANGE = colors.HexColor("#D97706")
GREEN = colors.HexColor("#16805B")
RED = colors.HexColor("#B42318")


def register_fonts() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def project(point: list[float]) -> tuple[float, float]:
    x, y, z = point
    c = math.sqrt(3) / 2
    return (x - y) * c, (x + y) * 0.5 - z


def frame_drawing(data: dict[str, Any], width: float, height: float) -> Drawing:
    members = data.get("members", [])
    points = [p for m in members for p in (m.get("start"), m.get("end")) if isinstance(p, list) and len(p) == 3]
    drawing = Drawing(width, height)
    if not points:
        drawing.add(String(width / 2, height / 2, "没有可绘制构件", textAnchor="middle", fontName="STSong-Light"))
        return drawing

    projected = [project(p) for p in points]
    min_x, max_x = min(p[0] for p in projected), max(p[0] for p in projected)
    min_y, max_y = min(p[1] for p in projected), max(p[1] for p in projected)
    pad = 18
    scale = min((width - 2 * pad) / max(max_x - min_x, 1), (height - 2 * pad) / max(max_y - min_y, 1))

    def screen(point: list[float]) -> tuple[float, float]:
        px, py = project(point)
        return pad + (px - min_x) * scale, height - pad - (py - min_y) * scale

    for member in sorted(members, key=lambda m: sum(m["start"]) + sum(m["end"])):
        x1, y1 = screen(member["start"])
        x2, y2 = screen(member["end"])
        role = str(member.get("role", "")).lower()
        color = DARK if "post" in role else BLUE
        drawing.add(Line(x1, y1, x2, y2, strokeColor=colors.white, strokeWidth=4.8))
        drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=2.4))
    joint_points = {tuple(j["at"]) for j in data.get("joints", []) if isinstance(j.get("at"), list) and len(j["at"]) == 3}
    for point in joint_points:
        x, y = screen(list(point))
        drawing.add(Circle(x, y, 1.7, fillColor=ORANGE, strokeColor=colors.white, strokeWidth=0.5))
    return drawing


def p(text: Any, style: ParagraphStyle) -> Paragraph:
    parts = str(text).split("<br/>")
    value = "<br/>".join(part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") for part in parts)
    return Paragraph(value, style)


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title-cn", parent=base["Title"], fontName="STSong-Light", fontSize=23, leading=30, textColor=DARK, alignment=TA_LEFT, spaceAfter=5 * mm),
        "h1": ParagraphStyle("h1-cn", parent=base["Heading1"], fontName="STSong-Light", fontSize=17, leading=22, textColor=DARK, spaceAfter=4 * mm),
        "h2": ParagraphStyle("h2-cn", parent=base["Heading2"], fontName="STSong-Light", fontSize=12, leading=16, textColor=BLUE, spaceBefore=3 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body-cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=9, leading=14, textColor=TEXT),
        "small": ParagraphStyle("small-cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.5, leading=10.5, textColor=MUTED),
        "center": ParagraphStyle("center-cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=8, leading=11, alignment=TA_CENTER, textColor=TEXT),
        "table": ParagraphStyle("table-cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.2, leading=9, textColor=TEXT),
        "table_small": ParagraphStyle("table-small-cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=6.3, leading=8, textColor=TEXT),
        "warning": ParagraphStyle("warning-cn", parent=base["BodyText"], fontName="STSong-Light", fontSize=8.5, leading=13, textColor=RED),
    }


def styled_table(rows: list[list[Any]], widths: list[float], header: bool = True, small: bool = False) -> Table:
    cell_style = ParagraphStyle(
        "table-cell-small" if small else "table-cell",
        fontName="STSong-Light", fontSize=6.1 if small else 7.1,
        leading=7.5 if small else 9, textColor=TEXT,
    )
    converted = [rows[0]] if header else []
    start = 1 if header else 0
    converted.extend([[p(cell, cell_style) for cell in row] for row in rows[start:]])
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5 if small else 7.3),
        ("LEADING", (0, 0), (-1, -1), 8 if small else 9.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8D5E2")),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, PALE]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "STSong-Light"),
        ]
    table.setStyle(TableStyle(style))
    return table


def envelope(data: dict[str, Any]) -> tuple[float, float, float]:
    points = [p for m in data.get("members", []) for p in (m.get("start"), m.get("end")) if isinstance(p, list) and len(p) == 3]
    if not points:
        return 0, 0, 0
    return tuple(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3))  # type: ignore[return-value]


def status_color(status: str) -> colors.Color:
    return GREEN if status == "可询价" else ORANGE if status == "待复核" else RED


def header_footer(canvas: Any, doc: BaseDocTemplate) -> None:
    canvas.saveState()
    page_width, page_height = A4
    canvas.setStrokeColor(BLUE)
    canvas.setLineWidth(1.1)
    canvas.line(16 * mm, page_height - 14 * mm, page_width - 16 * mm, page_height - 14 * mm)
    canvas.setFont("STSong-Light", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(16 * mm, page_height - 11 * mm, "RAY ALUFRAME - 结构设计文档")
    canvas.drawRightString(page_width - 16 * mm, 9 * mm, f"第 {doc.page} 页")
    canvas.drawString(16 * mm, 9 * mm, "尺寸单位：mm - 生成文档不替代商家或专业人员复核")
    canvas.restoreState()


def build_pdf(data: dict[str, Any], output: Path) -> None:
    result = validate(data)
    styles = make_styles()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(output), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=19 * mm, bottomMargin=15 * mm, title=str(data.get("project", {}).get("name", "铝型材框架")),
        author="ray-aluframe",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="document", frames=[frame], onPage=header_footer)])
    story: list[Any] = []

    project = data.get("project", {})
    x_size, y_size, z_size = envelope(data)
    status = result["readiness"]
    story += [Spacer(1, 6 * mm), p(project.get("name", "铝型材框架"), styles["title"])]
    meta = Table([
        ["版本", project.get("revision", "未标注"), "当前状态", status],
        ["外形包络", f"{x_size:.0f} × {y_size:.0f} × {z_size:.0f}", "型材估重", f"{result['total_profile_weight_kg']:.2f} kg"],
    ], colWidths=[24 * mm, 60 * mm, 24 * mm, 60 * mm])
    meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT), ("BACKGROUND", (2, 0), (2, -1), LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D5E2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TEXTCOLOR", (3, 0), (3, 0), status_color(status)),
    ]))
    story += [meta, Spacer(1, 7 * mm), frame_drawing(data, doc.width, 105 * mm), Spacer(1, 4 * mm)]
    story += [p("等轴结构图", styles["h2"]), p("灰色为立柱，蓝色为横梁，橙点为连接节点。此图用于核对整体结构，不是加工图。", styles["small"])]
    checks = data.get("checks", {})
    cover_rows = [
        ["重量传递", checks.get("load_path", "待确定")],
        ["防侧摆", checks.get("lateral_stability", "待确定")],
        ["防倾倒", checks.get("tip_over", "待确定")],
    ]
    story += [Spacer(1, 4 * mm), styled_table(cover_rows, [27 * mm, 141 * mm], header=False)]
    story += [Spacer(1, 4 * mm), p("重要：只有当连接件、加工方式、板材固定和防倾倒措施都确定后，这份文档才可转为正式询价单。", styles["warning"])]

    story += [PageBreak(), p("材料清单", styles["h1"])]
    story += [p("同一型材、同一长度已合并。长度来自结构中心线；最终下料要按选定连接方式扣减。", styles["small"]), Spacer(1, 3 * mm)]
    grouped: Counter[tuple[str, float]] = Counter()
    roles_by_key: defaultdict[tuple[str, float], Counter[str]] = defaultdict(Counter)
    role_names = {"post": "立柱", "level beam": "层横梁", "side beam": "侧横梁"}
    for member in result["members"].values():
        _, length = axis_and_length(member["start"], member["end"])
        key = (member["profile_id"], length)
        grouped[key] += 1
        role = role_names.get(str(member.get("role", "")), str(member.get("role", "构件")))
        roles_by_key[key][role] += 1
    rows = [["序号", "厂家货号", "型材", "长度", "数量", "合计长度", "对应构件"]]
    for index, ((pid, length), qty) in enumerate(sorted(grouped.items(), key=lambda item: (item[0][0], -item[0][1])), 1):
        profile = result["profiles"][pid]
        rows.append([
            str(index), str(profile.get("part_number", "待确定")), f"{pid} / {profile.get('description', '')}",
            f"{length:.0f}", str(qty), f"{length * qty:.0f}", "，".join(f"{role} {count}" for role, count in roles_by_key[(pid, length)].items()),
        ])
    story += [styled_table(rows, [9 * mm, 29 * mm, 36 * mm, 16 * mm, 12 * mm, 21 * mm, 45 * mm], small=True)]

    story += [p("连接件", styles["h2"])]
    connector_rows = [["厂家", "货号", "名称", "数量", "状态"]]
    for (manufacturer, part, description), qty in sorted(result["connector_counts"].items()):
        connector_name = {
            "multi-way corner/tee connection kit": "多向角部/三通连接组件",
            "30-series slot-8 angle bracket set; P3060 beam end uses two brackets": "30 系列槽 8 角码套装；30x60 横梁每端双角码",
        }.get(description, description)
        connector_rows.append([manufacturer if manufacturer and "TBD" not in manufacturer.upper() else "待确定", part if part and "TBD" not in part.upper() else "待确定", connector_name, str(qty), "待绑定商家" if "TBD" in part.upper() else "已指定"])
    if len(connector_rows) == 1:
        connector_rows.append(["待确定", "待确定", "未提供", "-", "缺失"])
    story += [styled_table(connector_rows, [24 * mm, 37 * mm, 65 * mm, 16 * mm, 26 * mm])]

    story += [p("板材与附件", styles["h2"])]
    accessory_rows = [["类别", "名称", "数量", "货号", "状态"]]
    category_names = {"backing": "背板", "foot": "底脚", "shelf": "层板", "shelf_fastener": "层板固定", "panel_fastener": "面板固定", "appearance_optional": "外观选配"}
    accessory_names = {
        "left color-matched rigid back panel": "左侧同色刚性背板",
        "right display/peg board fixed around perimeter": "右侧展示/洞洞板（四周固定）",
        "adjustable foot": "调节脚",
        "left shelf panel about 600x350": "左侧层板，约 600x350",
        "right shelf panel about 1200x350": "右侧层板，约 1200x350",
        "adjustable foot with base plate": "带连接板的调节脚",
        "left wooden shelf panel about 600x350x18 with underside brackets": "左侧木层板，约 600x350x18，底部小角码固定",
        "right wooden shelf panel about 1200x350x18 with underside brackets": "右侧木层板，约 1200x350x18，底部小角码固定",
        "right display/peg board with perimeter panel holders": "右侧展示/洞洞板，周边面板夹固定",
        "left color-matched rigid back panel with multi-point fixing": "左侧同色刚性背板，周边多点固定",
        "underside shelf fixing bracket set": "层板底部固定小角码套装",
        "back/display panel perimeter holder set": "背板/展示板周边固定夹套装",
        "angle bracket cover, optional": "角码装饰盖，可选",
    }
    for (category, manufacturer, part, description), qty in sorted(result["accessory_counts"].items()):
        accessory_rows.append([category_names.get(category, category), accessory_names.get(description, description), str(qty), part if part and "TBD" not in part.upper() else "待确定", "待绑定商家" if "TBD" in part.upper() else "已指定"])
    if len(accessory_rows) == 1:
        accessory_rows.append(["-", "未提供", "-", "-", "缺失"])
    story += [styled_table(accessory_rows, [20 * mm, 72 * mm, 14 * mm, 37 * mm, 25 * mm])]

    story += [PageBreak(), p("下料与承重初查", styles["h1"])]
    story += [p("下料组合已计入设计中设置的锯缝和两端修整量，用来估算需要购买几根原料。", styles["small"]), Spacer(1, 3 * mm)]
    for pid, bars in result["cut_plans"].items():
        profile = result["profiles"][pid]
        story += [p(f"{pid} / {profile.get('part_number', '')}", styles["h2"])]
        cut_rows = [["原料", "切割组合", "可用余料"]]
        for index, bar in enumerate(bars, 1):
            length_counts = Counter(round(length) for _member_id, length in bar["cuts"])
            cuts = " + ".join(f"{length} x {count}" for length, count in sorted(length_counts.items(), reverse=True))
            cut_rows.append([f"第 {index} 根 / {float(profile['stock_length_mm']):.0f}", cuts, f"{bar['remaining_usable']:.0f}"])
        story += [styled_table(cut_rows, [31 * mm, 116 * mm, 21 * mm], small=True)]
    story += [Spacer(1, 3 * mm), p("横梁下弯初查", styles["h2"])]
    beam_grouped: defaultdict[tuple[str, float, float, str], int] = defaultdict(int)
    for item in result["beam_results"]:
        key = (item["member_id"].split("-")[0], round(item["deflection_mm"], 2), round(item["limit_mm"], 2), item["status"])
        beam_grouped[key] += 1
    beam_rows = [["位置组", "相同横梁数", "预计下弯", "筛查值", "结果", "强度"]]
    for (group, deflection, limit, status_value), qty in sorted(beam_grouped.items()):
        beam_rows.append([group, str(qty), f"{deflection:.2f}", f"{limit:.2f}", "通过" if status_value == "PASS" else "需复核", "未检查"])
    if len(beam_rows) == 1:
        beam_rows.append(["-", "-", "-", "-", "未提供载荷", "未检查"])
    story += [styled_table(beam_rows, [31 * mm, 24 * mm, 25 * mm, 25 * mm, 28 * mm, 35 * mm])]
    story += [Spacer(1, 3 * mm), p("“通过”只表示按当前假设估算的下弯量未超筛查值；连接强度、材料强度和防倾倒仍需另行确认。", styles["warning"])]

    story += [PageBreak(), p("装配顺序与待确认事项", styles["h1"])]
    assembly = [
        "1. 先组装底部框架，测量两条对角线，调整到方正。",
        "2. 安装六根立柱，临时拧紧，确认垂直。",
        "3. 从下往上安装各层横梁，每层再次核对对角线。",
        "4. 安装左侧刚性背板和右侧展示板，让它们参与防侧摆。",
        "5. 安装层板、调节脚与其他附件，空载复紧全部连接。",
        "6. 先放下层重书，再逐步加载；发现晃动、连接滑移或明显下弯应立即卸载。",
    ]
    story += [p("<br/>".join(assembly), styles["body"]), Spacer(1, 5 * mm)]

    notes = project.get("notes", [])
    if notes:
        story += [p("方案假设", styles["h2"]), p("<br/>".join(f"- {note}" for note in notes), styles["body"])]
    story += [p("当前必须确认", styles["h2"])]
    blockers = result["blockers"]
    blocker_summary = []
    if any("连接件" in item for item in blockers):
        blocker_summary.append("连接件的具体厂家、货号和每个节点的安装方式")
    if any("加工" in item for item in blockers):
        blocker_summary.append("各构件是否需要端面攻丝、通孔或其他加工")
    if any("附件" in item for item in blockers):
        blocker_summary.append("层板、背板、展示板和调节脚的具体产品与固定方式")
    if any("倾倒" in item for item in blockers):
        blocker_summary.append("2 米高、350 毫米深且不固定墙面时的防倾倒措施")
    if not blocker_summary:
        blocker_summary.append("没有阻断项，仍需商家做最终配套核对")
    story += [p("<br/>".join(f"- {item}" for item in blocker_summary), styles["warning"])]

    story += [p("发给商家的确认问题", styles["h2"])]
    questions = [
        "所列型材与连接件是否同一槽系，可直接配套？",
        "连接件是否包含螺栓和螺母，缺少哪些？",
        "请按最终连接方式给出精确下料扣减、孔位与加工要求。",
        "切割和孔位公差是多少，最长件如何包装运输？",
        "请复核满载书籍情况下的连接方式、底脚和防倾倒措施。",
    ]
    story += [p("<br/>".join(f"{i}. {item}" for i, item in enumerate(questions, 1)), styles["body"])]

    doc.build(story)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        register_fonts()
        data = json.loads(args.design.read_text(encoding="utf-8"))
        build_pdf(data, args.output)
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(f"无法生成施工文档: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
