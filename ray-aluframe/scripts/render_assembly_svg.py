#!/usr/bin/env python3
"""Render a material-style isometric assembly preview from a frame design JSON."""

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


def valid_point(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(isinstance(v, (int, float)) for v in value)


def visual_points(item: dict[str, Any]) -> list[list[float]]:
    if item.get("type") == "panel":
        return [point for point in item.get("corners", []) if valid_point(point)]
    if item.get("type") == "leveling_foot" and valid_point(item.get("at")):
        at = item["at"]
        return [at, [at[0], at[1], at[2] - float(item.get("stem_mm", 35))]]
    if item.get("type") == "caster" and valid_point(item.get("at")):
        at = item["at"]
        drop = float(item.get("stem_mm", 28)) + float(item.get("wheel_diameter_mm", 65))
        return [at, [at[0], at[1], at[2] - drop]]
    return []


def polygon(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def svg(data: dict[str, Any], width: int = 1100, height: int = 980) -> str:
    members = data.get("members", [])
    visuals = data.get("visuals", [])
    profiles = {profile.get("id"): profile for profile in data.get("profiles", [])}
    all_points = [point for member in members for point in (member.get("start"), member.get("end")) if valid_point(point)]
    all_points += [point for item in visuals for point in visual_points(item)]
    if not all_points:
        raise ValueError("design has no valid geometry")

    projected = [project(point) for point in all_points]
    min_x, max_x = min(p[0] for p in projected), max(p[0] for p in projected)
    min_y, max_y = min(p[1] for p in projected), max(p[1] for p in projected)
    margin_x, margin_top, margin_bottom = 120, 135, 125
    scale = min(
        (width - 2 * margin_x) / max(max_x - min_x, 1),
        (height - margin_top - margin_bottom) / max(max_y - min_y, 1),
    )
    offset_x = margin_x + ((width - 2 * margin_x) - (max_x - min_x) * scale) / 2
    offset_y = margin_top + ((height - margin_top - margin_bottom) - (max_y - min_y) * scale) / 2

    def screen(point: list[float]) -> tuple[float, float]:
        px, py = project(point)
        return offset_x + (px - min_x) * scale, offset_y + (py - min_y) * scale

    project_name = html.escape(str(data.get("project", {}).get("name", "铝型材装配效果")))
    revision = html.escape(str(data.get("project", {}).get("revision", "未标注")))
    member_points = [point for member in members for point in (member.get("start"), member.get("end")) if valid_point(point)]
    xs, ys, zs = ([point[index] for point in member_points] for index in range(3))
    size_text = f"{max(xs)-min(xs):.0f} × {max(ys)-min(ys):.0f} × {max(zs)-min(zs):.0f} mm"

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f8fafc"/><stop offset="1" stop-color="#e9eef3"/></linearGradient>',
        '<linearGradient id="aluminum" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f8fafc"/><stop offset="0.35" stop-color="#b8c2cc"/><stop offset="0.62" stop-color="#eef2f5"/><stop offset="1" stop-color="#8d99a5"/></linearGradient>',
        '<filter id="shadow" x="-30%" y="-30%" width="160%" height="180%"><feDropShadow dx="4" dy="8" stdDeviation="7" flood-color="#334155" flood-opacity="0.22"/></filter>',
        '<filter id="smallShadow" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="2" dy="3" stdDeviation="2" flood-color="#334155" flood-opacity="0.28"/></filter>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans CJK SC",sans-serif}</style>',
        '</defs>',
        f'<rect width="{width}" height="{height}" fill="url(#bg)"/>',
        f'<text x="70" y="58" font-size="30" font-weight="700" fill="#17243a">{project_name}</text>',
        f'<text x="70" y="91" font-size="16" fill="#64748b">版本 {revision} · 材质与五金示意（非照片、非加工图）</text>',
    ]

    ground_z = min(point[2] for point in all_points)
    ground_members = [point for point in all_points if abs(point[2] - ground_z) < 1e-6]
    if ground_members:
        gx = [screen(point)[0] for point in ground_members]
        gy = [screen(point)[1] for point in ground_members]
        cx, cy = sum(gx) / len(gx), max(gy) + 22
        out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{max(gx)-min(gx)+170:.1f}" ry="42" fill="#64748b" opacity="0.12" filter="url(#shadow)"/>')

    panels = [item for item in visuals if item.get("type") == "panel" and len(visual_points(item)) >= 3]
    panels.sort(key=lambda item: (sum(point[1] for point in visual_points(item)) / len(visual_points(item)), -sum(point[2] for point in visual_points(item)) / len(visual_points(item))), reverse=True)
    for item in panels:
        points = [screen(point) for point in visual_points(item)]
        fill = html.escape(str(item.get("fill", "#d8c6a5")))
        edge = html.escape(str(item.get("edge", "#8d765b")))
        opacity = float(item.get("opacity", 0.92))
        out.append(f'<polygon points="{polygon(points)}" fill="{fill}" fill-opacity="{opacity:.2f}" stroke="{edge}" stroke-width="2.3" filter="url(#smallShadow)"/>')
        if item.get("pattern") == "pegboard":
            min_sx, max_sx = min(x for x, _ in points), max(x for x, _ in points)
            min_sy, max_sy = min(y for _, y in points), max(y for _, y in points)
            for ix in range(1, 12):
                for iy in range(1, 8):
                    x = min_sx + (max_sx - min_sx) * ix / 12
                    y = min_sy + (max_sy - min_sy) * iy / 8
                    out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.8" fill="#5f6368" opacity="0.52"/>')

    feet = [item for item in visuals if item.get("type") == "leveling_foot" and valid_point(item.get("at"))]
    for item in sorted(feet, key=lambda foot: screen(foot["at"])[1]):
        x, y = screen(item["at"])
        stem_px = max(8.0, float(item.get("stem_mm", 35)) * scale)
        pad_px = max(14.0, float(item.get("pad_diameter_mm", 42)) * scale)
        out += [
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y + stem_px:.1f}" stroke="#3f4650" stroke-width="5"/>',
            f'<ellipse cx="{x:.1f}" cy="{y + stem_px:.1f}" rx="{pad_px/2:.1f}" ry="{max(4.0, pad_px/6):.1f}" fill="#20252b" filter="url(#smallShadow)"/>',
            f'<ellipse cx="{x:.1f}" cy="{y + stem_px - 2:.1f}" rx="{pad_px/2.4:.1f}" ry="{max(2.5, pad_px/9):.1f}" fill="#5d6670" opacity="0.75"/>',
        ]

    casters = [item for item in visuals if item.get("type") == "caster" and valid_point(item.get("at"))]
    for item in sorted(casters, key=lambda caster: screen(caster["at"])[1]):
        x, y = screen(item["at"])
        stem_px = max(7.0, float(item.get("stem_mm", 28)) * scale)
        wheel_px = max(15.0, float(item.get("wheel_diameter_mm", 65)) * scale)
        wheel_width_px = max(6.0, float(item.get("wheel_width_mm", 24)) * scale)
        wheel_y = y + stem_px + wheel_px / 2
        out += [
            f'<rect x="{x-8:.1f}" y="{y-3:.1f}" width="16" height="6" rx="2" fill="#737d83" stroke="#3f474b"/>',
            f'<line x1="{x:.1f}" y1="{y+2:.1f}" x2="{x:.1f}" y2="{wheel_y-wheel_px/2+2:.1f}" stroke="#4a5358" stroke-width="6"/>',
            f'<path d="M {x-wheel_width_px/2-3:.1f} {wheel_y-wheel_px/3:.1f} L {x-wheel_width_px/2:.1f} {wheel_y:.1f} M {x+wheel_width_px/2+3:.1f} {wheel_y-wheel_px/3:.1f} L {x+wheel_width_px/2:.1f} {wheel_y:.1f}" stroke="#6e787d" stroke-width="4" fill="none"/>',
            f'<ellipse cx="{x:.1f}" cy="{wheel_y:.1f}" rx="{wheel_width_px/2:.1f}" ry="{wheel_px/2:.1f}" fill="#22272a" stroke="#59636a" stroke-width="2" filter="url(#smallShadow)"/>',
            f'<ellipse cx="{x:.1f}" cy="{wheel_y:.1f}" rx="{max(2.0,wheel_width_px/5):.1f}" ry="{max(2.0,wheel_px/7):.1f}" fill="#c5cbce"/>',
        ]

    def depth(member: dict[str, Any]) -> float:
        return sum(member["start"]) + sum(member["end"])

    for member in sorted(members, key=depth):
        x1, y1 = screen(member["start"])
        x2, y2 = screen(member["end"])
        profile = profiles.get(member.get("profile_id"), {})
        section = max(float(profile.get("width_mm") or 30), float(profile.get("height_mm") or 30))
        outer = 13 if section <= 30 else 18 if section <= 60 else 22
        out += [
            f'<line x1="{x1+3:.1f}" y1="{y1+5:.1f}" x2="{x2+3:.1f}" y2="{y2+5:.1f}" stroke="#475569" stroke-opacity="0.24" stroke-width="{outer+5}" stroke-linecap="square"/>',
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#7b8792" stroke-width="{outer+2}" stroke-linecap="square"/>',
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="url(#aluminum)" stroke-width="{outer}" stroke-linecap="square"/>',
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#4b5563" stroke-opacity="0.72" stroke-width="2.2"/>',
            f'<line x1="{x1-2:.1f}" y1="{y1-2:.1f}" x2="{x2-2:.1f}" y2="{y2-2:.1f}" stroke="#ffffff" stroke-opacity="0.72" stroke-width="2.4"/>',
        ]

    max_depth = max(point[1] for point in all_points)
    for joint in data.get("joints", []):
        point = joint.get("at")
        if not valid_point(point):
            continue
        x, y = screen(point)
        front = point[1] < max_depth / 2
        size = 14 if front else 9
        opacity = 0.96 if front else 0.66
        out.append(f'<rect x="{x-size/2:.1f}" y="{y-size/2:.1f}" width="{size}" height="{size}" rx="2" fill="#aeb8c2" stroke="#65717d" stroke-width="1.2" opacity="{opacity}" filter="url(#smallShadow)"/>')
        if front:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.1" fill="#424b55"/>')

    footer_y = height - 60
    out += [
        f'<rect x="55" y="{footer_y-24}" width="{width-110}" height="48" rx="8" fill="#ffffff" fill-opacity="0.88" stroke="#cbd5e1"/>',
        f'<text x="75" y="{footer_y+7}" font-size="16" fill="#334155">框架外形 {html.escape(size_text)} · 银色：阳极氧化铝型材 · 灰色节点：连接件 · 黑色：底脚 / 脚轮</text>',
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
        print(f"无法生成装配效果图: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
