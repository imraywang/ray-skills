#!/usr/bin/env python3
"""Render a simple isometric SVG preview from an axis-aligned frame design JSON."""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any


def project(point: list[float]) -> tuple[float, float]:
    x, y, z = point
    c = math.sqrt(3) / 2
    return (x - y) * c, (x + y) * 0.5 - z


def role_color(role: str) -> str:
    role = role.lower()
    if "post" in role or "立柱" in role:
        return "#475569"
    if "level" in role or "long" in role or "横梁" in role:
        return "#2563eb"
    if "side" in role or "短梁" in role:
        return "#0f766e"
    return "#7c3aed"


def svg(data: dict[str, Any], width: int = 1200, height: int = 820) -> str:
    members = data.get("members", [])
    points = [point for member in members for point in (member.get("start"), member.get("end")) if isinstance(point, list) and len(point) == 3]
    if not points:
        raise ValueError("design has no valid member coordinates")
    projected = [project(point) for point in points]
    min_x = min(p[0] for p in projected)
    max_x = max(p[0] for p in projected)
    min_y = min(p[1] for p in projected)
    max_y = max(p[1] for p in projected)
    margin_x, margin_top, margin_bottom = 100, 100, 150
    scale = min(
        (width - 2 * margin_x) / max(max_x - min_x, 1),
        (height - margin_top - margin_bottom) / max(max_y - min_y, 1),
    )

    def screen(point: list[float]) -> tuple[float, float]:
        px, py = project(point)
        return margin_x + (px - min_x) * scale, margin_top + (py - min_y) * scale

    title = html.escape(str(data.get("project", {}).get("name", "铝型材框架预览")))
    revision = html.escape(str(data.get("project", {}).get("revision", "未标注")))
    xs, ys, zs = ([p[index] for p in points] for index in range(3))
    size_text = f"坐标包络：{max(xs)-min(xs):.0f} × {max(ys)-min(ys):.0f} × {max(zs)-min(zs):.0f} mm"

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#f8fafc"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC",sans-serif}.label{font-size:13px;fill:#334155}.meta{fill:#475569;font-size:16px}</style>',
        f'<text x="60" y="48" text-anchor="start" font-family="PingFang SC, Helvetica, Arial, sans-serif" font-size="28" font-weight="700" fill="#0f172a">方案｜{title}</text>',
        f'<text x="60" y="76" class="meta">版本 {revision} · 结构核对预览（非加工图）</text>',
    ]

    labels: list[tuple[float, float, str]] = []
    sorted_members = sorted(members, key=lambda member: sum(member["start"]) + sum(member["end"]))
    for member in sorted_members:
        x1, y1 = screen(member["start"])
        x2, y2 = screen(member["end"])
        color = role_color(str(member.get("role", "")))
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#ffffff" stroke-width="11" stroke-linecap="round"/>')
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="6" stroke-linecap="round"/>')
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        label = html.escape(str(member.get("id", "")))
        labels.append((mid_x, mid_y, label))

    joint_points = {tuple(joint["at"]) for joint in data.get("joints", []) if isinstance(joint.get("at"), list) and len(joint["at"]) == 3}
    for point in joint_points:
        x, y = screen(list(point))
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#f59e0b" stroke="#ffffff" stroke-width="2"/>')

    occupied: list[tuple[float, float, float, float]] = []
    for mid_x, mid_y, label in labels:
        label_width = max(44.0, len(label) * 7.4 + 10)
        label_height = 20.0
        candidates = [
            (mid_x + 8, mid_y - 25),
            (mid_x + 8, mid_y + 8),
            (mid_x - label_width - 8, mid_y - 25),
            (mid_x - label_width - 8, mid_y + 8),
            (mid_x + 24, mid_y - 42),
            (mid_x - label_width - 24, mid_y + 25),
        ]
        chosen = candidates[0]
        for candidate_x, candidate_y in candidates:
            box = (candidate_x, candidate_y, candidate_x + label_width, candidate_y + label_height)
            inside = 20 <= box[0] and box[2] <= width - 20 and 90 <= box[1] and box[3] <= height - 120
            overlaps = any(not (box[2] < old[0] or box[0] > old[2] or box[3] < old[1] or box[1] > old[3]) for old in occupied)
            if inside and not overlaps:
                chosen = (candidate_x, candidate_y)
                occupied.append(box)
                break
        else:
            occupied.append((chosen[0], chosen[1], chosen[0] + label_width, chosen[1] + label_height))
        label_x, label_y = chosen
        out.append(f'<rect x="{label_x:.1f}" y="{label_y:.1f}" width="{label_width:.1f}" height="{label_height:.1f}" rx="4" fill="#f8fafc" fill-opacity="0.90"/>')
        out.append(f'<text x="{label_x + 5:.1f}" y="{label_y + 14:.1f}" class="label">{label}</text>')

    footer_y = height - 82
    out += [
        f'<text x="60" y="{footer_y}" class="meta">{html.escape(size_text)}</text>',
        f'<text x="60" y="{footer_y + 28}" font-size="14" fill="#64748b">蓝：层/长梁 · 绿：短梁 · 灰：立柱 · 橙点：节点。长度以设计清单为准。</text>',
        '</svg>',
    ]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.design.read_text(encoding="utf-8"))
        args.output.write_text(svg(data), encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(f"无法生成预览: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
