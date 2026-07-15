#!/usr/bin/env python3
"""Generate a self-contained interactive frame preview as a single HTML file."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import math
import mimetypes
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from check_frame import load_catalog, validate


def _member_length(member: dict[str, Any]) -> int:
    return int(round(math.dist(member["start"], member["end"])))


def _compact_issues(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    untouched: list[dict[str, str]] = []
    for issue in issues:
        text = issue["text"]
        if ":" not in text:
            untouched.append(issue)
            continue
        prefix, detail = text.split(":", 1)
        grouped[(issue["severity"], detail.strip())].append(prefix.strip())

    compacted = list(untouched)
    for (severity, detail), prefixes in grouped.items():
        if len(prefixes) < 3:
            compacted.extend(
                {"severity": severity, "text": f"{prefix}: {detail}"} for prefix in prefixes
            )
            continue
        examples = "、".join(prefixes[:3])
        compacted.append(
            {
                "severity": severity,
                "text": f"{len(prefixes)} 项：{detail}（例如 {examples}）",
            }
        )
    order = {"error": 0, "blocker": 1, "warning": 2}
    return sorted(compacted, key=lambda issue: (order[issue["severity"]], issue["text"]))


def _embed_one_reference(reference: dict[str, Any], design_dir: Path) -> None:
    if reference.get("data_uri"):
        reference.pop("path", None)
        return
    raw_path = reference.get("path")
    if not raw_path:
        raise ValueError("reference_image 需要 path 或 data_uri")
    image_path = Path(str(raw_path)).expanduser()
    if not image_path.is_absolute():
        image_path = design_dir / image_path
    if not image_path.is_file():
        raise ValueError(f"参考图不存在: {image_path}")
    mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        raise ValueError(f"参考图格式不受支持: {image_path.name}")
    reference["data_uri"] = f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"
    reference["source_name"] = image_path.name
    reference.pop("path", None)


def _embed_reference_image(working: dict[str, Any], design_dir: Path) -> None:
    references = []
    if isinstance(working.get("reference_image"), dict):
        references.append(working["reference_image"])
    references.extend(item for item in working.get("reference_images", []) if isinstance(item, dict))
    for reference in references:
        _embed_one_reference(reference, design_dir)


def _payload(data: dict[str, Any], design_dir: Path) -> dict[str, Any]:
    working = copy.deepcopy(data)
    _embed_reference_image(working, design_dir)
    result = validate(working)
    working = result.get("resolved_design") or working
    working["profiles"] = list(result["profiles"].values())

    profiles = result["profiles"]
    groups: Counter[tuple[str, int]] = Counter()
    group_members: defaultdict[tuple[str, int], list[str]] = defaultdict(list)
    for member in working.get("members", []):
        length = _member_length(member)
        key = (member["profile_id"], length)
        groups[key] += 1
        group_members[key].append(member["id"])
    bom = []
    for (profile_id, length), qty in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        profile = profiles[profile_id]
        bom.append(
            {
                "profile_id": profile_id,
                "catalog_id": profile.get("catalog_id") or "未绑定",
                "designation": profile.get("part_number") or f"{profile.get('width_mm', '')}{profile.get('height_mm', '')}",
                "length_mm": length,
                "qty": qty,
                "member_ids": group_members[(profile_id, length)],
            }
        )

    issues = []
    for severity, key in (("error", "errors"), ("blocker", "blockers"), ("warning", "warnings")):
        issues.extend({"severity": severity, "text": text} for text in result[key])
    return {
        "design": working,
        "catalog": load_catalog(),
        "bom": bom,
        "issues": _compact_issues(issues),
        "readiness": result["readiness"],
        "quote": result["quote"],
        "receipt_checklist": result["receipt_checklist"],
        "assembly_plan": result["assembly_plan"],
    }


def html_document(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    title = str(payload["design"].get("project", {}).get("name") or "铝型材交互预览")
    asset_dir = Path(__file__).resolve().parent.parent / "assets"
    three_runtime = (asset_dir / "three-runtime.min.js").read_text(encoding="utf-8").replace("</", "<\\/")
    viewer_runtime = (asset_dir / "interactive-viewer.js").read_text(encoding="utf-8").replace("</", "<\\/")
    reference_review_runtime = (asset_dir / "reference-review.js").read_text(encoding="utf-8").replace("</", "<\\/")
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%231c2b38'/%3E%3Cpath d='M16 46V18h18c9 0 14 4 14 12 0 5-3 9-8 11l9 5H36l-7-4v4zm11-17h7c2 0 3-1 3-3s-1-3-3-3h-7z' fill='%23f08a36'/%3E%3C/svg%3E">
<title>{title} · 交互预览</title>
<style>
:root {{
  color-scheme: light;
  --ink: oklch(24% .035 248);
  --muted: oklch(49% .025 248);
  --paper: oklch(96.5% .012 84);
  --surface: oklch(99% .008 84);
  --line: oklch(85% .018 248);
  --blue: oklch(48% .13 244);
  --blue-deep: oklch(36% .10 244);
  --orange: oklch(69% .16 53);
  --green: oklch(58% .12 155);
  --red: oklch(58% .19 28);
  --shadow: 0 18px 50px oklch(29% .03 248 / .12);
  --ease: cubic-bezier(.22,1,.36,1);
}}
* {{ box-sizing: border-box; }}
[hidden] {{ display: none !important; }}
html, body {{ margin: 0; min-height: 100%; background: var(--paper); color: var(--ink); }}
body {{ font-family: "Avenir Next", "Futura", "PingFang SC", "Microsoft YaHei", sans-serif; font-size: 16px; line-height: 1.5; }}
button, input, select {{ font: inherit; }}
button {{ color: inherit; }}
button:focus-visible, input:focus-visible, select:focus-visible, canvas:focus-visible {{ outline: 3px solid var(--orange); outline-offset: 2px; }}
.skip {{ position: fixed; left: 12px; top: -60px; z-index: 20; background: var(--ink); color: var(--surface); padding: 10px 14px; }}
.skip:focus {{ top: 12px; }}
.app {{ height: 100dvh; min-height: 640px; display: grid; grid-template-rows: auto auto minmax(0,1fr); }}
.masthead {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 20px clamp(18px,3vw,42px) 16px; border-bottom: 1px solid var(--line); background: var(--surface); }}
.eyebrow {{ margin: 0 0 4px; color: var(--orange); font-size: .75rem; font-weight: 800; letter-spacing: .16em; text-transform: uppercase; }}
h1 {{ margin: 0; font-size: clamp(1.35rem,2.2vw,2.25rem); line-height: 1.1; letter-spacing: -.035em; }}
.meta {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; color: var(--muted); font-size: .875rem; }}
.status {{ display: inline-flex; align-items: center; gap: 7px; padding: 5px 10px; border: 1px solid var(--line); border-radius: 999px; color: var(--ink); font-weight: 700; background: var(--paper); }}
.status::before {{ content: ""; width: 8px; height: 8px; border-radius: 50%; background: var(--orange); }}
.toolbar {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; padding: 10px clamp(18px,3vw,42px); border-bottom: 1px solid var(--line); background: var(--surface); overflow-x: visible; scrollbar-width: thin; }}
.tool-group {{ display: flex; align-items: center; gap: 6px; white-space: nowrap; }}
.tool-label {{ color: var(--muted); font-size: .75rem; font-weight: 800; letter-spacing: .08em; margin-right: 2px; }}
.tool-button, .step-button {{ min-height: 42px; border: 1px solid transparent; background: transparent; padding: 8px 12px; cursor: pointer; white-space: nowrap; transition: background 130ms var(--ease), color 130ms var(--ease), transform 130ms var(--ease); }}
.tool-button:hover, .step-button:hover {{ background: var(--paper); }}
.tool-button:active, .step-button:active {{ transform: translateY(1px); }}
.tool-button[aria-pressed="true"] {{ background: var(--ink); color: var(--surface); }}
.mode-note {{ color: var(--muted); font-size: .7rem; padding-left: 2px; }}
.toggle {{ min-height: 42px; display: inline-flex; align-items: center; gap: 8px; cursor: pointer; padding: 0 4px; }}
.toggle input {{ width: 18px; height: 18px; accent-color: var(--blue); }}
.reference-tools {{ display: flex; flex: 0 0 auto; align-items: center; gap: 8px; padding-left: 10px; border-left: 1px solid var(--line); }}
.reference-tools .tool-button, .reference-slider {{ flex: 0 0 auto; white-space: nowrap; }}
.reference-slider {{ display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: .72rem; font-weight: 750; }}
.reference-slider input {{ width: 112px; accent-color: var(--orange); }}
.reference-select {{ max-width: 130px; min-height: 34px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); padding: 4px 8px; }}
.reference-calibration {{ color: var(--muted); font-size: .72rem; white-space: nowrap; }}
.reference-known {{ display: inline-flex; align-items: center; gap: 5px; color: var(--muted); font-size: .72rem; font-weight: 750; white-space: nowrap; }}
.reference-known input {{ width: 86px; min-height: 34px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); padding: 4px 7px; font-variant-numeric: tabular-nums; }}
.workspace {{ min-height: 0; display: grid; grid-template-columns: minmax(0,1fr) minmax(320px,390px); }}
.viewer {{ position: relative; min-height: 560px; overflow: hidden; background: #202428; }}
.viewer::before {{ content: ""; position: absolute; inset: 0; pointer-events: none; z-index: 2; background: radial-gradient(circle at 54% 40%,transparent 38%,rgba(0,0,0,.22) 100%); }}
canvas {{ position: absolute; z-index: 0; inset: 0; width: 100%; height: 100%; touch-action: none; cursor: grab; }}
canvas.dragging {{ cursor: grabbing; }}
.reference-layer {{ position: absolute; z-index: 1; inset: 0; pointer-events: none; overflow: hidden; }}
.reference-layer img {{ width: 100%; height: 100%; object-fit: contain; transform-origin: 50% 50%; display: block; }}
.reference-calibration-layer {{ position: absolute; z-index: 7; inset: 0; cursor: crosshair; background: transparent; touch-action: none; }}
.reference-calibration-point {{ position: absolute; width: 18px; height: 18px; transform: translate(-50%,-50%); border: 3px solid white; border-radius: 50%; background: var(--orange); box-shadow: 0 0 0 2px rgba(0,0,0,.55); pointer-events: none; }}
.reference-calibration-point::after {{ content: ""; position: absolute; left: 50%; top: 50%; width: 5px; height: 5px; transform: translate(-50%,-50%); border-radius: 50%; background: #202428; }}
.reference-regions {{ position: absolute; z-index: 4; left: 24px; right: 24px; bottom: 76px; display: flex; align-items: stretch; pointer-events: auto; }}
.reference-region {{ min-width: 0; padding: 9px 11px; border: 1px solid oklch(91% .025 84 / .9); background: oklch(20% .035 248 / .82); color: var(--surface); cursor: pointer; }}
.reference-region[data-confirmed="true"] {{ background: oklch(42% .09 155 / .9); }}
.reference-region + .reference-region {{ border-left: 0; }}
.reference-region strong {{ display: block; font-size: .78rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.reference-region span {{ display: block; color: oklch(87% .07 84); font-size: .68rem; margin-top: 2px; }}
.reference-note {{ position: absolute; z-index: 4; top: 16px; right: 18px; max-width: min(360px,calc(100% - 36px)); padding: 8px 10px; background: oklch(20% .035 248 / .84); color: var(--surface); font-size: .72rem; pointer-events: none; }}
.view-help {{ position: absolute; z-index: 4; left: 18px; bottom: 16px; margin: 0; color: var(--muted); font-size: .8rem; background: var(--surface); border: 1px solid var(--line); padding: 8px 11px; }}
.export-status {{ position: absolute; z-index: 9; right: 18px; bottom: 18px; max-width: 360px; padding: 10px 14px; background: oklch(42% .09 155 / .96); color: white; box-shadow: var(--shadow); font-size: .8rem; font-weight: 700; }}
.dimensions {{ position: absolute; z-index: 4; top: 16px; left: 18px; display: flex; flex-wrap: wrap; gap: 6px; max-width: calc(100% - 36px); pointer-events: none; }}
.dimension {{ padding: 6px 9px; background: var(--surface); border: 1px solid var(--line); font-size: .78rem; font-variant-numeric: tabular-nums; box-shadow: 0 5px 18px oklch(29% .03 248 / .08); }}
.dimension-editor {{ position: absolute; z-index: 8; top: 16px; right: 18px; width: min(360px,calc(100% - 36px)); max-height: calc(100% - 32px); overflow: auto; background: color-mix(in oklch,var(--surface) 97%,transparent); border: 1px solid var(--line); box-shadow: 0 18px 60px rgba(0,0,0,.28); }}
.editor-head {{ display: flex; justify-content: space-between; gap: 14px; padding: 15px 16px 12px; border-bottom: 1px solid var(--line); }}
.editor-head strong {{ display: block; }}
.editor-head span {{ display: block; margin-top: 2px; color: var(--muted); font-size: .72rem; }}
.editor-fields {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 14px 16px; }}
.editor-field {{ display: grid; gap: 5px; color: var(--muted); font-size: .72rem; font-weight: 750; }}
.editor-input {{ display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 6px; }}
.editor-input input {{ width: 100%; min-height: 40px; padding: 7px 9px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); font-variant-numeric: tabular-nums; }}
.editor-input small {{ min-width: 24px; color: var(--muted); font-size: .68rem; }}
.editor-foot {{ display: grid; gap: 9px; padding: 0 16px 15px; }}
.editor-status {{ min-height: 34px; margin: 0; padding: 7px 9px; background: var(--paper); color: var(--muted); font-size: .72rem; }}
.editor-status[data-state="error"] {{ background: color-mix(in oklch,var(--red) 10%,var(--surface)); color: var(--red); }}
.editor-status[data-state="changed"] {{ background: color-mix(in oklch,var(--green) 10%,var(--surface)); color: oklch(39% .10 155); }}
.editor-note {{ margin: 0; color: var(--muted); font-size: .68rem; }}
.editor-reset {{ min-height: 38px; border: 1px solid var(--line); background: transparent; cursor: pointer; font-weight: 750; }}
.bom-section {{ margin-top: 24px; }}
.render-failure {{ position: absolute; z-index: 4; inset: 50% auto auto 50%; translate: -50% -50%; width: min(420px,calc(100% - 36px)); padding: 18px 20px; display: grid; gap: 6px; color: #fff; background: #762d20; border: 1px solid #ff9b72; box-shadow: 0 18px 60px rgba(0,0,0,.35); }}
.render-failure span {{ color: #ffe3d8; font-size: .86rem; }}
.inspector {{ min-height: 0; display: grid; grid-template-rows: auto minmax(0,1fr); background: var(--surface); border-left: 1px solid var(--line); }}
.selection {{ padding: 22px 22px 18px; border-bottom: 1px solid var(--line); }}
.selection-kicker {{ margin: 0 0 6px; color: var(--blue); font-size: .75rem; font-weight: 800; letter-spacing: .11em; }}
.selection h2 {{ margin: 0; font-size: 1.35rem; letter-spacing: -.02em; }}
.selection-empty {{ color: var(--muted); margin: 8px 0 0; }}
.facts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px 16px; margin: 16px 0 0; }}
.fact dt {{ color: var(--muted); font-size: .75rem; }}
.fact dd {{ margin: 2px 0 0; font-weight: 700; font-variant-numeric: tabular-nums; }}
.inline-action {{ width: 100%; border: 1px solid var(--blue); background: color-mix(in oklch,var(--blue) 9%,var(--surface)); color: var(--blue-deep); padding: 8px 10px; text-align: left; cursor: pointer; font: inherit; font-weight: 800; }}
.inline-action:hover {{ background: color-mix(in oklch,var(--blue) 16%,var(--surface)); }}
.inline-action:focus-visible {{ outline: 3px solid color-mix(in oklch,var(--orange) 55%,transparent); outline-offset: 2px; }}
.location-note {{ display: block; margin-top: 5px; color: var(--orange); font-size: .72rem; font-weight: 800; }}
.hardware-locations {{ margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }}
.tabs {{ min-height: 0; display: grid; grid-template-rows: auto minmax(0,1fr); }}
.tablist {{ display: grid; grid-template-columns: repeat(6,1fr); border-bottom: 1px solid var(--line); }}
.tab {{ min-height: 48px; border: 0; border-bottom: 3px solid transparent; background: transparent; cursor: pointer; font-weight: 700; color: var(--muted); }}
.tab[aria-selected="true"] {{ color: var(--ink); border-bottom-color: var(--orange); }}
.tab-panel {{ min-height: 0; overflow: auto; padding: 18px 22px 30px; }}
.tab-panel[hidden] {{ display: none; }}
.section-title {{ margin: 0 0 12px; font-size: .75rem; color: var(--muted); font-weight: 800; letter-spacing: .1em; }}
.member-list, .bom-list, .issue-list {{ display: grid; gap: 2px; }}
.list-row {{ width: 100%; border: 0; border-bottom: 1px solid var(--line); background: transparent; padding: 11px 2px; text-align: left; cursor: pointer; display: grid; grid-template-columns: minmax(0,1fr) auto; gap: 12px; align-items: center; }}
.list-row:hover, .list-row.active {{ color: var(--blue-deep); background: color-mix(in oklch,var(--blue) 7%,transparent); }}
.list-main {{ min-width: 0; }}
.list-name {{ display: block; font-weight: 750; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.list-sub {{ display: block; color: var(--muted); font-size: .75rem; margin-top: 2px; }}
.list-value {{ font-weight: 800; font-variant-numeric: tabular-nums; }}
.evidence-badge {{ display: inline-flex; align-items: center; margin-left: 6px; padding: 1px 6px; border-radius: 999px; font-size: .64rem; font-weight: 800; vertical-align: 1px; }}
.evidence-visible {{ color: oklch(39% .11 53); background: oklch(92% .07 77); }}
.evidence-inferred {{ color: oklch(37% .10 244); background: oklch(92% .04 244); }}
.evidence-confirmed {{ color: oklch(34% .11 155); background: oklch(91% .05 155); }}
.evidence-legend {{ display: flex; flex-wrap: wrap; gap: 6px; margin: -2px 0 12px; }}
.assembly-head {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 18px; }}
.step-controls {{ display: flex; gap: 4px; }}
.step-button {{ border-color: var(--line); min-width: 44px; padding-inline: 10px; }}
.step-name {{ font-size: 1.2rem; font-weight: 800; margin: 0; }}
.step-copy {{ color: var(--muted); margin: 6px 0 18px; }}
.progress {{ display: grid; grid-template-columns: repeat(6,1fr); gap: 4px; }}
.progress span {{ height: 5px; background: var(--line); }}
.progress span.done {{ background: var(--orange); }}
.issue {{ padding: 12px 0 12px 18px; border-bottom: 1px solid var(--line); position: relative; }}
.issue::before {{ content: ""; position: absolute; left: 1px; top: 19px; width: 8px; height: 8px; border-radius: 50%; background: var(--orange); }}
.issue.error::before {{ background: var(--red); }}
.issue.warning::before {{ background: var(--blue); }}
.issue-label {{ font-size: .7rem; font-weight: 800; color: var(--muted); letter-spacing: .08em; }}
.issue p {{ margin: 3px 0 0; font-size: .875rem; }}
.empty {{ color: var(--muted); padding: 24px 0; }}
@media (max-width: 900px) {{
  .app {{ height: auto; min-height: 100vh; }}
  .masthead {{ align-items: flex-start; flex-direction: column; gap: 10px; }}
  .workspace {{ grid-template-columns: 1fr; grid-template-rows: minmax(480px,62vh) auto; }}
  .inspector {{ border-left: 0; border-top: 1px solid var(--line); min-height: 560px; }}
  .toolbar {{ flex-wrap: nowrap; overflow-x: auto; }}
}}
@media (max-width: 560px) {{
  .toolbar {{ padding-inline: 12px; }}
  .viewer {{ min-height: 430px; }}
  .workspace {{ grid-template-rows: 54vh auto; }}
  .view-help {{ display: none; }}
  .facts {{ grid-template-columns: 1fr; }}
  .selection, .tab-panel {{ padding-inline: 16px; }}
  .reference-slider input {{ width: 88px; }}
  .reference-regions {{ left: 12px; right: 12px; bottom: 58px; }}
  .reference-note {{ top: 62px; left: 18px; right: 18px; max-width: none; }}
  .dimension-editor {{ top: 10px; right: 10px; width: calc(100% - 20px); }}
  .editor-fields {{ grid-template-columns: 1fr; }}
}}
@media (prefers-reduced-motion: reduce) {{ *,*::before,*::after {{ transition-duration: .01ms !important; animation-duration: .01ms !important; }} }}
</style>
</head>
<body>
<a class="skip" href="#model">跳到模型</a>
<main class="app">
  <header class="masthead">
    <div><p class="eyebrow">Ray Aluframe / Interactive Preview</p><h1 id="project-title"></h1></div>
    <div class="meta"><span id="revision"></span><span id="envelope"></span><span class="status" id="readiness"></span></div>
  </header>
  <nav class="toolbar" aria-label="预览工具">
    <div class="tool-group" role="group" aria-label="显示模式"><span class="tool-label">模式</span>
      <button class="tool-button" data-mode="structure" aria-pressed="false">结构</button>
      <button class="tool-button" data-mode="realistic" aria-pressed="true">真实</button>
      <span class="mode-note" id="mode-note">真实槽口三维型材</span>
    </div>
    <div class="tool-group" role="group" aria-label="视角"><span class="tool-label">视角</span>
      <button class="tool-button" data-view="iso" aria-pressed="true">等轴</button>
      <button class="tool-button" data-view="front" aria-pressed="false">正面·柜门侧</button>
      <button class="tool-button" data-view="side" aria-pressed="false">右侧</button>
      <button class="tool-button" data-view="top" aria-pressed="false">顶面</button>
    </div>
    <div class="tool-group" role="group" aria-label="显示内容"><span class="tool-label">显示</span>
      <label class="toggle"><input id="show-panels" type="checkbox" checked>层板</label>
      <label class="toggle"><input id="show-hardware" type="checkbox" checked>五金</label>
      <label class="toggle"><input id="show-dimensions" type="checkbox" checked>尺寸</label>
    </div>
    <div class="reference-tools" id="reference-tools" role="group" aria-label="参考图校对" hidden>
      <button class="tool-button" id="reference-review-toggle" aria-pressed="false">参考图校对</button>
      <select class="reference-select" id="reference-view-select" aria-label="选择参考图" hidden></select>
      <label class="reference-slider" id="reference-opacity-control" hidden>原图
        <input id="reference-opacity" type="range" min="0" max="100" value="48" aria-label="参考图透明度">
      </label>
      <label class="reference-slider" id="reference-scale-control" hidden>缩放
        <input id="reference-scale" type="range" min="25" max="400" value="100" aria-label="参考图缩放">
      </label>
      <label class="reference-slider" id="reference-x-control" hidden>水平
        <input id="reference-x" type="range" min="-100" max="100" value="0" aria-label="参考图水平移动">
      </label>
      <label class="reference-slider" id="reference-y-control" hidden>垂直
        <input id="reference-y" type="range" min="-100" max="100" value="0" aria-label="参考图垂直移动">
      </label>
      <button class="tool-button" id="reference-calibrate" hidden>两点定尺度</button>
      <label class="reference-known" id="reference-known-control" hidden>实际
        <input id="reference-known-length" type="number" min="0.1" step="1" value="1000" aria-label="两点之间的实际长度，毫米">mm
      </label>
      <button class="tool-button" id="reference-save-scale" hidden>保存尺度</button>
      <span class="reference-calibration" id="reference-calibration" hidden></span>
    </div>
    <button class="tool-button" id="edit-layout" aria-pressed="false">修改尺寸</button>
    <button class="tool-button" id="export-design">下载方案</button>
    <button class="tool-button" id="reset-view">复位视角</button>
  </nav>
  <section class="workspace">
    <section class="viewer" id="model" aria-label="可旋转的铝型材结构模型">
      <canvas id="canvas" tabindex="0" aria-label="拖动旋转，滚轮缩放，点击型材或五金查看参数"></canvas>
      <div class="reference-layer" id="reference-layer" hidden><img id="reference-image" alt=""></div>
      <div class="reference-calibration-layer" id="reference-calibration-layer" aria-label="参考图定尺度区域" hidden></div>
      <div class="reference-regions" id="reference-regions" hidden></div>
      <div class="reference-note" id="reference-note" hidden>请选择对应视角，调节缩放与位置后核对分区；“两点定尺度”可记录图中已知长度。</div>
      <div class="dimensions" id="dimensions"></div>
      <section class="dimension-editor" id="dimension-editor" aria-label="修改结构尺寸" hidden>
        <div class="editor-head"><div><strong>直接修改方案</strong><span>离开输入框或按回车后自动更新</span></div></div>
        <div class="editor-fields"></div>
        <div class="editor-foot">
          <p class="editor-status">修改后会同步更新模型、主体下料、门框和门板尺寸。</p>
          <p class="editor-note">页面修改不会覆盖原始设计文件；正式询价前仍需重新运行承载与稳定性检查。</p>
          <button class="editor-reset" id="reset-layout" type="button">恢复原方案</button>
        </div>
      </section>
      <div class="export-status" id="export-status" role="status" aria-live="polite" hidden></div>
      <p class="view-help">拖动旋转 · 滚轮缩放 · 点击型材或五金查看参数 · 方向键微调</p>
    </section>
    <aside class="inspector" aria-label="结构信息">
      <section class="selection" id="selection"></section>
      <section class="tabs">
        <div class="tablist" role="tablist" aria-label="结构详情">
          <button class="tab" role="tab" aria-selected="true" aria-controls="members-panel" id="members-tab">构件</button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="hardware-panel" id="hardware-tab" tabindex="-1">五金</button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="bom-panel" id="bom-tab" tabindex="-1">清单</button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="quote-panel" id="quote-tab" tabindex="-1">询价</button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="assembly-panel" id="assembly-tab" tabindex="-1">装配</button>
          <button class="tab" role="tab" aria-selected="false" aria-controls="issues-panel" id="issues-tab" tabindex="-1">问题</button>
        </div>
        <div class="tab-panel" role="tabpanel" id="members-panel" aria-labelledby="members-tab"></div>
        <div class="tab-panel" role="tabpanel" id="hardware-panel" aria-labelledby="hardware-tab" hidden></div>
        <div class="tab-panel" role="tabpanel" id="bom-panel" aria-labelledby="bom-tab" hidden></div>
        <div class="tab-panel" role="tabpanel" id="quote-panel" aria-labelledby="quote-tab" hidden></div>
        <div class="tab-panel" role="tabpanel" id="assembly-panel" aria-labelledby="assembly-tab" hidden></div>
        <div class="tab-panel" role="tabpanel" id="issues-panel" aria-labelledby="issues-tab" hidden></div>
      </section>
    </aside>
  </section>
</main>
<script id="payload" type="application/json">{encoded}</script>
<script type="text/plain" id="legacy-viewer">
const payload = JSON.parse(document.getElementById('payload').textContent);
const design = payload.design;
const members = design.members || [];
const memberMap = Object.fromEntries(members.map(m => [m.id,m]));
const profiles = Object.fromEntries((design.profiles || []).map(p => [p.id,p]));
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const state = {{ yaw:-Math.PI/4, pitch:Math.PI/7, zoom:1, selected:null, hoverIds:new Set(), dragging:false, last:null, dragDistance:0, renderMode:'realistic', showPanels:true, showHardware:true, showDimensions:true, step:0, hit:[] }};
const presets = {{ iso:[-Math.PI/4,Math.PI/7], front:[0,0], side:[-Math.PI/2,0], top:[0,Math.PI/2] }};
const roleNames = {{post:'立柱','level beam':'层横梁','side beam':'侧横梁'}};
const evidenceNames = {{visible:'原图可见',inferred:'结构推测',confirmed:'用户确认'}};
const confidenceNames = {{high:'高',medium:'中',low:'低'}};
const allPoints = members.flatMap(m => [m.start,m.end]);
const bounds = [0,1,2].map(i => [Math.min(...allPoints.map(p=>p[i])),Math.max(...allPoints.map(p=>p[i]))]);
const center = bounds.map(([a,b]) => (a+b)/2);
const envelope = bounds.map(([a,b]) => Math.round(b-a));
document.getElementById('project-title').textContent = design.project?.name || '铝型材交互预览';
document.getElementById('revision').textContent = `版本 ${{design.project?.revision || '未标注'}}`;
document.getElementById('envelope').textContent = `${{envelope[0]}} × ${{envelope[1]}} × ${{envelope[2]}} mm`;
document.getElementById('readiness').textContent = payload.readiness;

function rotated(p) {{
  const dx=p[0]-center[0], dy=p[1]-center[1], dz=p[2]-center[2];
  const cy=Math.cos(state.yaw), sy=Math.sin(state.yaw), cp=Math.cos(state.pitch), sp=Math.sin(state.pitch);
  const x=dx*cy-dy*sy, ry=dx*sy+dy*cy;
  return [x, -(dz*cp-ry*sp), dz*sp+ry*cp];
}}
function projection() {{
  const rect=canvas.getBoundingClientRect();
  const projected=allPoints.map(rotated);
  const xs=projected.map(p=>p[0]), ys=projected.map(p=>p[1]);
  const spanX=Math.max(...xs)-Math.min(...xs)||1, spanY=Math.max(...ys)-Math.min(...ys)||1;
  const margin=state.showDimensions?(rect.width<560?130:190):110;
  const scale=Math.min(Math.max(80,rect.width-margin)/spanX,Math.max(80,rect.height-margin)/spanY)*state.zoom;
  return {{scale,cx:rect.width/2,cy:rect.height/2}};
}}
function screen(p,proj) {{ const r=rotated(p); return [proj.cx+r[0]*proj.scale,proj.cy+r[1]*proj.scale,r[2]]; }}
function lineDistance(px,py,a,b) {{
  const vx=b[0]-a[0], vy=b[1]-a[1], wx=px-a[0], wy=py-a[1];
  const t=Math.max(0,Math.min(1,(wx*vx+wy*vy)/(vx*vx+vy*vy||1)));
  return Math.hypot(px-(a[0]+t*vx),py-(a[1]+t*vy));
}}
function memberLength(m) {{ return Math.round(Math.hypot(m.end[0]-m.start[0],m.end[1]-m.start[1],m.end[2]-m.start[2])); }}
function currentStepKind(m) {{
  const horizontal=Math.abs(m.end[2]-m.start[2])<.001;
  const minZ=Math.min(...members.filter(x=>Math.abs(x.end[2]-x.start[2])<.001).map(x=>x.start[2]));
  if (state.step===1) return horizontal && Math.abs(m.start[2]-minZ)<.001;
  if (state.step===2) return (m.role||'').toLowerCase().includes('post');
  if (state.step===3) return horizontal && Math.abs(m.start[2]-minZ)>=.001;
  return false;
}}
function memberColor(m) {{
  if (state.selected===m.id || state.hoverIds.has(m.id)) return '#e47726';
  if (state.step>0 && state.step<4 && !currentStepKind(m)) return '#bfc6c8';
  if ((m.role||'').toLowerCase().includes('post')) return '#33485d';
  return '#2172a8';
}}
function polygonDepth(item) {{ return item.corners.reduce((sum,p)=>sum+rotated(p)[2],0)/item.corners.length; }}
function drawDimensionLine(start,end,label,proj) {{
  const a=screen(start,proj), b=screen(end,proj), dx=b[0]-a[0], dy=b[1]-a[1], length=Math.hypot(dx,dy);
  if (length<34) return;
  const mid=[(a[0]+b[0])/2,(a[1]+b[1])/2];
  let ox=mid[0]-proj.cx, oy=mid[1]-proj.cy, outward=Math.hypot(ox,oy);
  if (outward<1) {{ ox=-dy; oy=dx; outward=length; }}
  const ux=ox/outward, uy=oy/outward, gap=canvas.getBoundingClientRect().width<560?20:28;
  const oa=[a[0]+ux*gap,a[1]+uy*gap], ob=[b[0]+ux*gap,b[1]+uy*gap];
  const tx=-dy/length*6, ty=dx/length*6;
  ctx.save(); ctx.globalAlpha=1; ctx.lineCap='butt'; ctx.lineWidth=1.5; ctx.strokeStyle='#8a5a2f';
  ctx.setLineDash([4,4]);
  ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(oa[0],oa[1]);ctx.moveTo(b[0],b[1]);ctx.lineTo(ob[0],ob[1]);ctx.stroke();
  ctx.setLineDash([]); ctx.lineWidth=2;
  ctx.beginPath();ctx.moveTo(oa[0],oa[1]);ctx.lineTo(ob[0],ob[1]);
  ctx.moveTo(oa[0]-tx,oa[1]-ty);ctx.lineTo(oa[0]+tx,oa[1]+ty);
  ctx.moveTo(ob[0]-tx,ob[1]-ty);ctx.lineTo(ob[0]+tx,ob[1]+ty);ctx.stroke();
  const lx=(oa[0]+ob[0])/2+ux*13, ly=(oa[1]+ob[1])/2+uy*13;
  ctx.font='700 12px "Avenir Next", "PingFang SC", sans-serif'; ctx.textAlign='center'; ctx.textBaseline='middle';
  const tw=ctx.measureText(label).width;
  ctx.fillStyle='#fbf8f1';ctx.fillRect(lx-tw/2-6,ly-10,tw+12,20);
  ctx.strokeStyle='#d4c4b3';ctx.lineWidth=1;ctx.strokeRect(lx-tw/2-6,ly-10,tw+12,20);
  ctx.fillStyle='#4d3421';ctx.fillText(label,lx,ly+.5);ctx.restore();
}}
function drawDimensions(proj) {{
  if (!state.showDimensions) return;
  const minX=bounds[0][0], maxX=bounds[0][1], minY=bounds[1][0], maxY=bounds[1][1], minZ=bounds[2][0], maxZ=bounds[2][1];
  drawDimensionLine([minX,minY,minZ],[maxX,minY,minZ],`宽 ${{envelope[0]}} mm`,proj);
  drawDimensionLine([maxX,minY,minZ],[maxX,maxY,minZ],`深 ${{envelope[1]}} mm`,proj);
  drawDimensionLine([maxX,maxY,minZ],[maxX,maxY,maxZ],`高 ${{envelope[2]}} mm`,proj);
}}
function memberWidth(m) {{
  const profile=profiles[m.profile_id]||{{}}, section=Math.max(profile.width_mm||30,profile.height_mm||30);
  return Math.max(6,Math.min(16,section/5))*Math.min(1.25,Math.max(.75,state.zoom));
}}
function drawStructureMember(m,a,b,width) {{
  ctx.strokeStyle='#f5f1e9';ctx.lineWidth=width+5;ctx.lineCap='square';ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
  ctx.strokeStyle=memberColor(m);ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
  ctx.strokeStyle='rgba(255,255,255,.7)';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(a[0]-2,a[1]-2);ctx.lineTo(b[0]-2,b[1]-2);ctx.stroke();
}}
function drawRealMember(m,a,b,width) {{
  const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy)||1,nx=-dy/length,ny=dx/length;
  const highlighted=state.selected===m.id||state.hoverIds.has(m.id);
  ctx.lineCap='square';
  if (highlighted) {{
    ctx.strokeStyle='#e47726';ctx.lineWidth=width+10;ctx.globalAlpha=.92;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();ctx.globalAlpha=1;
  }}
  ctx.strokeStyle='#4d575d';ctx.lineWidth=width+5;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
  const metal=ctx.createLinearGradient(a[0]+nx*width/2,a[1]+ny*width/2,a[0]-nx*width/2,a[1]-ny*width/2);
  metal.addColorStop(0,'#727d83');metal.addColorStop(.16,'#c4cbce');metal.addColorStop(.42,'#f4f6f5');metal.addColorStop(.7,'#aab3b7');metal.addColorStop(1,'#667178');
  ctx.strokeStyle=metal;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
  ctx.strokeStyle='#515d63';ctx.lineWidth=Math.max(1.2,width*.12);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();
  ctx.strokeStyle='rgba(255,255,255,.82)';ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(a[0]+nx*width*.28,a[1]+ny*width*.28);ctx.lineTo(b[0]+nx*width*.28,b[1]+ny*width*.28);ctx.stroke();
  if (width>10) {{
    ctx.strokeStyle='rgba(70,82,89,.7)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(a[0]-nx*width*.27,a[1]-ny*width*.27);ctx.lineTo(b[0]-nx*width*.27,b[1]-ny*width*.27);ctx.stroke();
  }}
}}
function panelPath(pts) {{ ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath(); }}
function drawPanel(panel,proj) {{
  const pts=panel.corners.map(p=>screen(p,proj));
  panelPath(pts);
  if (state.renderMode==='structure') {{
    ctx.fillStyle=panel.pattern==='pegboard'?'#d5d0bf':'#d9c89e';ctx.globalAlpha=state.step===4?1:.72;ctx.fill();
    ctx.globalAlpha=1;ctx.strokeStyle='#897d63';ctx.lineWidth=1.5;ctx.stroke();return;
  }}
  const xs=pts.map(p=>p[0]),ys=pts.map(p=>p[1]),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  const material=ctx.createLinearGradient(minX,minY,maxX,maxY);
  if (panel.pattern==='pegboard') {{ material.addColorStop(0,'#bbb5a6');material.addColorStop(.55,'#d7d2c5');material.addColorStop(1,'#9f9a8e'); }}
  else {{ material.addColorStop(0,'#b99768');material.addColorStop(.45,'#dec89f');material.addColorStop(1,'#a88459'); }}
  ctx.fillStyle=material;ctx.globalAlpha=state.step===4?1:.9;ctx.fill();ctx.globalAlpha=1;
  ctx.save();panelPath(pts);ctx.clip();
  if (panel.pattern==='pegboard') {{
    ctx.fillStyle='rgba(50,52,50,.5)';
    for(let x=minX+9;x<maxX;x+=16)for(let y=minY+9;y<maxY;y+=16){{ctx.beginPath();ctx.arc(x,y,1.15,0,Math.PI*2);ctx.fill();}}
  }} else {{
    ctx.strokeStyle='rgba(105,70,38,.16)';ctx.lineWidth=.8;
    for(let y=minY+8;y<maxY;y+=13){{ctx.beginPath();ctx.moveTo(minX-8,y);ctx.bezierCurveTo(minX+(maxX-minX)*.3,y-2,maxX-(maxX-minX)*.25,y+2,maxX+8,y);ctx.stroke();}}
  }}
  ctx.restore();panelPath(pts);ctx.strokeStyle=panel.pattern==='pegboard'?'#716e65':'#7b5e3e';ctx.lineWidth=2;ctx.stroke();
}}
function jointDirections(j,proj) {{
  const p=screen(j.at,proj),directions=[];
  (j.member_ids||[]).forEach(id=>{{
    const m=memberMap[id];if(!m)return;
    const ds=Math.hypot(...m.start.map((v,i)=>v-j.at[i])),de=Math.hypot(...m.end.map((v,i)=>v-j.at[i]));
    const other=screen(ds>de?m.start:m.end,proj),dx=other[0]-p[0],dy=other[1]-p[1],length=Math.hypot(dx,dy);
    if(length<5)return;const d=[dx/length,dy/length];
    if(!directions.some(x=>Math.abs(x[0]*d[0]+x[1]*d[1])>.985))directions.push(d);
  }});
  return [p,directions];
}}
function drawStructureJoint(j,proj) {{
  const p=screen(j.at,proj);ctx.fillStyle=state.step===5?'#e47726':'#6d7a83';ctx.strokeStyle='#f5f1e9';ctx.lineWidth=2;
  ctx.beginPath();ctx.arc(p[0],p[1],state.step===5?7:5,0,Math.PI*2);ctx.fill();ctx.stroke();
}}
function drawRealJoint(j,proj) {{
  const [p,directions]=jointDirections(j,proj);ctx.save();ctx.lineCap='round';
  directions.slice(0,3).forEach(d=>{{
    const end=[p[0]+d[0]*14,p[1]+d[1]*14];
    ctx.strokeStyle='#525b60';ctx.lineWidth=10;ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(end[0],end[1]);ctx.stroke();
    ctx.strokeStyle=state.step===5?'#d28a50':'#aeb6b9';ctx.lineWidth=7;ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(end[0],end[1]);ctx.stroke();
    const bolt=[p[0]+d[0]*8,p[1]+d[1]*8];ctx.fillStyle='#3f474b';ctx.beginPath();ctx.arc(bolt[0],bolt[1],2.5,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#d8ddde';ctx.beginPath();ctx.arc(bolt[0]-.6,bolt[1]-.6,.9,0,Math.PI*2);ctx.fill();
  }});
  ctx.fillStyle='#3f474b';ctx.strokeStyle='#d5dadb';ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(p[0],p[1],4,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.restore();
}}
function drawFoot(foot,proj) {{
  const top=screen(foot.at,proj),bottom=screen([foot.at[0],foot.at[1],foot.at[2]-(foot.stem_mm||35)],proj);
  const radius=Math.max(5,Math.min(11,(foot.pad_diameter_mm||45)*proj.scale/2));ctx.save();
  ctx.strokeStyle='#3f474b';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(top[0],top[1]);ctx.lineTo(bottom[0],bottom[1]);ctx.stroke();
  ctx.fillStyle=state.renderMode==='realistic'?'#747d81':'#6d7a83';ctx.strokeStyle='#30373a';ctx.lineWidth=1.5;ctx.beginPath();ctx.ellipse(bottom[0],bottom[1],radius,Math.max(2.5,radius*.34),0,0,Math.PI*2);ctx.fill();ctx.stroke();
  ctx.fillStyle='#c4cacc';ctx.fillRect(top[0]-4,top[1]-2,8,4);ctx.restore();
}}
function drawCaster(caster,proj) {{
  const top=screen(caster.at,proj),stemBottom=screen([caster.at[0],caster.at[1],caster.at[2]-(caster.stem_mm||28)],proj);
  const wheelRadius=Math.max(7,Math.min(15,(caster.wheel_diameter_mm||65)*proj.scale/2));
  const wheelWidth=Math.max(5,Math.min(10,(caster.wheel_width_mm||24)*proj.scale));
  const center=[stemBottom[0],stemBottom[1]+wheelRadius];ctx.save();
  ctx.fillStyle='#70797e';ctx.strokeStyle='#3a4246';ctx.lineWidth=1.5;ctx.fillRect(top[0]-7,top[1]-3,14,6);ctx.strokeRect(top[0]-7,top[1]-3,14,6);
  ctx.strokeStyle='#4d565b';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(top[0],top[1]+2);ctx.lineTo(stemBottom[0],stemBottom[1]);ctx.stroke();
  ctx.strokeStyle='#7a8489';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(center[0]-wheelWidth/2-3,stemBottom[1]);ctx.lineTo(center[0]-wheelWidth/2,center[1]);ctx.moveTo(center[0]+wheelWidth/2+3,stemBottom[1]);ctx.lineTo(center[0]+wheelWidth/2,center[1]);ctx.stroke();
  ctx.fillStyle=state.renderMode==='realistic'?'#24292c':'#596269';ctx.strokeStyle='#9aa3a8';ctx.lineWidth=1.5;ctx.beginPath();ctx.ellipse(center[0],center[1],wheelWidth/2,wheelRadius,0,0,Math.PI*2);ctx.fill();ctx.stroke();
  ctx.fillStyle='#c5cbce';ctx.beginPath();ctx.arc(center[0],center[1],2.2,0,Math.PI*2);ctx.fill();ctx.restore();
}}
function draw() {{
  const rect=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
  const w=Math.round(rect.width*dpr), h=Math.round(rect.height*dpr);
  if (canvas.width!==w||canvas.height!==h) {{ canvas.width=w; canvas.height=h; }}
  ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,rect.width,rect.height);
  const proj=projection();
  ctx.save();
  if (state.showPanels && state.step!==1 && state.step!==2 && state.step!==3) {{
    const panels=(design.visuals||[]).filter(v=>v.type==='panel'&&v.corners?.length>=3).sort((a,b)=>polygonDepth(b)-polygonDepth(a));
    panels.forEach(panel=>drawPanel(panel,proj));
  }}
  const sorted=[...members].sort((a,b)=>((rotated(a.start)[2]+rotated(a.end)[2])-(rotated(b.start)[2]+rotated(b.end)[2])));
  state.hit=[];
  sorted.forEach(m=>{{
    const a=screen(m.start,proj),b=screen(m.end,proj),width=memberWidth(m);
    ctx.globalAlpha=(state.step>0&&state.step<4&&!currentStepKind(m))?.26:1;
    if(state.renderMode==='realistic')drawRealMember(m,a,b,width);else drawStructureMember(m,a,b,width);
    ctx.globalAlpha=1; state.hit.push({{id:m.id,a,b}});
  }});
  if (state.showHardware && state.step!==1 && state.step!==2 && state.step!==3) {{
    (design.visuals||[]).filter(v=>v.type==='leveling_foot').sort((a,b)=>rotated(a.at)[2]-rotated(b.at)[2]).forEach(foot=>drawFoot(foot,proj));
    (design.visuals||[]).filter(v=>v.type==='caster').sort((a,b)=>rotated(a.at)[2]-rotated(b.at)[2]).forEach(caster=>drawCaster(caster,proj));
    (design.joints||[]).sort((a,b)=>rotated(a.at)[2]-rotated(b.at)[2]).forEach(j=>{{
      if(state.renderMode==='realistic')drawRealJoint(j,proj);else drawStructureJoint(j,proj);
    }});
  }}
  drawDimensions(proj);
  ctx.restore();
}}
function selectMember(id) {{ state.selected=id; state.hoverIds.clear(); renderSelection(); renderMembers(); draw(); }}
function renderSelection() {{
  const root=document.getElementById('selection'), m=members.find(x=>x.id===state.selected);
  if (!m) {{ root.innerHTML='<p class="selection-kicker">当前选择</p><h2>检查结构</h2><p class="selection-empty">点击模型中的型材，查看长度、规格和连接信息。</p>'; return; }}
  const p=profiles[m.profile_id]||{{}}, connected=(design.joints||[]).filter(j=>j.member_ids?.includes(m.id));
  const evidence=evidenceNames[m.evidence_basis]||'未标注';
  root.innerHTML=`<p class="selection-kicker">当前构件</p><h2>${{m.id}}</h2><dl class="facts">
    <div class="fact"><dt>目录编号</dt><dd>${{p.catalog_id||'未绑定'}}</dd></div>
    <div class="fact"><dt>型材</dt><dd>${{p.part_number||`${{p.width_mm||''}}${{p.height_mm||''}}`}}</dd></div>
    <div class="fact"><dt>长度</dt><dd>${{memberLength(m)}} mm</dd></div>
    <div class="fact"><dt>用途</dt><dd>${{roleNames[m.role]||m.role||'构件'}}</dd></div>
    <div class="fact"><dt>相连节点</dt><dd>${{connected.length}}</dd></div>
    <div class="fact"><dt>加工</dt><dd>${{m.machining_status==='not_required'?'无需加工':m.machining_status==='specified'?'已说明':'待确认'}}</dd></div>
    <div class="fact"><dt>识别依据</dt><dd>${{evidence}}</dd></div>
    <div class="fact"><dt>置信度</dt><dd>${{confidenceNames[m.evidence_confidence]||m.evidence_confidence||'未标注'}}</dd></div>
    ${{m.evidence_note?`<div class="fact" style="grid-column:1/-1"><dt>依据说明</dt><dd>${{m.evidence_note}}</dd></div>`:''}}
  </dl>`;
}}
function renderMembers() {{
  const root=document.getElementById('members-panel');
  const badge=m=>m.evidence_basis&&evidenceNames[m.evidence_basis]?`<span class="evidence-badge evidence-${{m.evidence_basis}}">${{evidenceNames[m.evidence_basis]}}</span>`:'';
  const legend=design.reference_image?'<div class="evidence-legend"><span class="evidence-badge evidence-visible">原图可见</span><span class="evidence-badge evidence-inferred">结构推测</span><span class="evidence-badge evidence-confirmed">用户确认</span></div>':'';
  root.innerHTML='<p class="section-title">全部构件</p>'+legend+'<div class="member-list">'+members.map(m=>`<button class="list-row ${{state.selected===m.id?'active':''}}" data-member="${{m.id}}"><span class="list-main"><span class="list-name">${{m.id}}${{badge(m)}}</span><span class="list-sub">${{roleNames[m.role]||m.role||'构件'}} · ${{profiles[m.profile_id]?.catalog_id||m.profile_id}}</span></span><span class="list-value">${{memberLength(m)}} mm</span></button>`).join('')+'</div>';
  root.querySelectorAll('[data-member]').forEach(b=>{{b.onclick=()=>selectMember(b.dataset.member);b.onmouseenter=()=>{{state.hoverIds=new Set([b.dataset.member]);draw();}};b.onmouseleave=()=>{{state.hoverIds.clear();draw();}};}});
}}
function renderBom() {{
  const root=document.getElementById('bom-panel');
  root.innerHTML='<p class="section-title">型材下料汇总</p><div class="bom-list">'+payload.bom.map((r,i)=>`<button class="list-row" data-bom="${{i}}"><span class="list-main"><span class="list-name">${{r.catalog_id}} · ${{r.designation}}</span><span class="list-sub">${{r.length_mm}} mm</span></span><span class="list-value">× ${{r.qty}}</span></button>`).join('')+'</div>';
  root.querySelectorAll('[data-bom]').forEach(b=>{{const ids=payload.bom[+b.dataset.bom].member_ids;b.onmouseenter=()=>{{state.hoverIds=new Set(ids);draw();}};b.onmouseleave=()=>{{state.hoverIds.clear();draw();}};b.onclick=()=>{{state.hoverIds=new Set(ids);state.selected=ids[0];renderSelection();draw();}};}});
}}
const steps=payload.assembly_plan?.steps?.length?payload.assembly_plan.steps:[{{name:'完整结构',copy:'查看所有型材、板材和五金。'}}];
function renderAssembly() {{
  const s=steps[state.step], root=document.getElementById('assembly-panel');
  root.innerHTML=`<div class="assembly-head"><div><p class="section-title">装配演示</p><p class="step-name">${{s.name}}</p></div><div class="step-controls"><button class="step-button" id="prev-step" aria-label="上一步">←</button><button class="step-button" id="next-step" aria-label="下一步">→</button></div></div><p class="step-copy">${{s.copy}}</p>${{s.check?`<div class="issue"><span class="issue-label">这一步要核对</span><p>${{s.check}}</p></div>`:''}}<div class="progress" aria-label="装配进度">${{Array.from({{length:Math.max(1,steps.length-1)}},(_,i)=>`<span class="${{i<state.step?'done':''}}"></span>`).join('')}}</div>`;
  root.querySelector('#prev-step').onclick=()=>{{state.step=Math.max(0,state.step-1);renderAssembly();draw();}};
  root.querySelector('#next-step').onclick=()=>{{state.step=Math.min(steps.length-1,state.step+1);renderAssembly();draw();}};
}}
function renderQuote() {{
  const root=document.getElementById('quote-panel'),q=payload.quote||{{}},money=r=>r?`¥${{Number(r[0]).toFixed(2)}}–¥${{Number(r[1]).toFixed(2)}}`:'缺少价格';
  root.innerHTML=`<p class="section-title">整套预算</p><p class="step-name">${{money(q.total_range_cny)}}</p><div class="bom-list">${{(q.rows||[]).map(r=>`<div class="list-row"><span class="list-main"><span class="list-name">${{r.item}}</span><span class="list-sub">${{r.section}} · ${{r.qty}} ${{r.unit}}</span></span><span class="list-value">${{money(r.amount_range_cny)}}</span></div>`).join('')}}</div><p class="section-title bom-section">收货核对</p><div class="bom-list">${{(payload.receipt_checklist||[]).map(r=>`<div class="list-row"><span class="list-main"><span class="list-name">${{r.category}} · ${{r.item}}</span><span class="list-sub">${{r.expected}}<br>${{r.check}}</span></span></div>`).join('')}}</div>`;
}}
function renderIssues() {{
  const labels={{error:'错误',blocker:'必须确认',warning:'提醒'}}, root=document.getElementById('issues-panel');
  root.innerHTML='<p class="section-title">方案检查</p><div class="issue-list">'+(payload.issues.length?payload.issues.map(i=>`<div class="issue ${{i.severity}}"><span class="issue-label">${{labels[i.severity]}}</span><p>${{i.text}}</p></div>`).join(''):'<p class="empty">没有发现阻断项，可以继续准备询价。</p>')+'</div>';
}}
function setTab(tab) {{
  document.querySelectorAll('.tab').forEach(b=>{{const active=b.id===`${{tab}}-tab`;b.setAttribute('aria-selected',active);b.tabIndex=active?0:-1;}});
  document.querySelectorAll('.tab-panel').forEach(p=>p.hidden=p.id!==`${{tab}}-panel`);
}}
document.querySelectorAll('.tab').forEach((b,index,all)=>{{
  b.onclick=()=>setTab(b.id.replace('-tab',''));
  b.onkeydown=e=>{{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const next=(index+(e.key==='ArrowRight'?1:-1)+all.length)%all.length;all[next].focus();all[next].click();}};
}});
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{{
  [state.yaw,state.pitch]=presets[b.dataset.view];state.zoom=1;
  document.querySelectorAll('[data-view]').forEach(x=>x.setAttribute('aria-pressed',x===b));draw();
}});
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{{
  state.renderMode=b.dataset.mode;
  document.querySelectorAll('[data-mode]').forEach(x=>x.setAttribute('aria-pressed',x===b));
  document.getElementById('mode-note').hidden=state.renderMode!=='realistic';draw();
}});
document.getElementById('reset-view').onclick=()=>{{[state.yaw,state.pitch]=presets.iso;state.zoom=1;draw();}};
document.getElementById('show-panels').onchange=e=>{{state.showPanels=e.target.checked;draw();}};
document.getElementById('show-hardware').onchange=e=>{{state.showHardware=e.target.checked;draw();}};
document.getElementById('show-dimensions').onchange=e=>{{state.showDimensions=e.target.checked;document.getElementById('dimensions').hidden=!e.target.checked;draw();}};
canvas.addEventListener('pointerdown',e=>{{state.dragging=true;state.last=[e.clientX,e.clientY];state.dragDistance=0;canvas.classList.add('dragging');canvas.setPointerCapture(e.pointerId);}});
canvas.addEventListener('pointermove',e=>{{if(!state.dragging)return;const dx=e.clientX-state.last[0],dy=e.clientY-state.last[1];state.last=[e.clientX,e.clientY];state.dragDistance+=Math.hypot(dx,dy);state.yaw+=dx*.008;state.pitch=Math.max(-Math.PI/2,Math.min(Math.PI/2,state.pitch-dy*.006));draw();}});
canvas.addEventListener('pointerup',e=>{{state.dragging=false;canvas.classList.remove('dragging');canvas.releasePointerCapture(e.pointerId);}});
canvas.addEventListener('wheel',e=>{{e.preventDefault();state.zoom=Math.max(.55,Math.min(2.6,state.zoom*(e.deltaY>0?.92:1.08)));draw();}},{{passive:false}});
canvas.addEventListener('click',e=>{{if(state.dragDistance>5)return;const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const hit=state.hit.map(h=>[h.id,lineDistance(x,y,h.a,h.b)]).sort((a,b)=>a[1]-b[1])[0];if(hit&&hit[1]<18)selectMember(hit[0]);}});
canvas.addEventListener('keydown',e=>{{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();if(e.key==='ArrowLeft')state.yaw-=.08;if(e.key==='ArrowRight')state.yaw+=.08;if(e.key==='ArrowUp')state.pitch+=.06;if(e.key==='ArrowDown')state.pitch-=.06;draw();}});
new ResizeObserver(draw).observe(canvas.parentElement);
document.getElementById('dimensions').innerHTML=[`宽 ${{envelope[0]}} mm`,`深 ${{envelope[1]}} mm`,`高 ${{envelope[2]}} mm`].map(x=>`<span class="dimension">${{x}}</span>`).join('');
document.getElementById('hardware-panel').innerHTML='<p class="section-title">五金汇总</p><div class="issue-list">'+(design.accessories||[]).map(a=>`<div class="issue"><p>${{a.description||a.category}} × ${{a.qty||0}}</p></div>`).join('')+'</div>';
renderSelection();renderMembers();renderBom();renderQuote();renderAssembly();renderIssues();draw();
</script>
<script>{three_runtime}</script>
<script>{viewer_runtime}</script>
<script>{reference_review_runtime}</script>
</body>
</html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.design.read_text(encoding="utf-8"))
        document = html_document(_payload(data, args.design.resolve().parent))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
        print(args.output)
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(f"无法生成交互预览: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
