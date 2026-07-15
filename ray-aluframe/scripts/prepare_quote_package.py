#!/usr/bin/env python3
"""Resolve catalog pairings and write an enriched quote-ready design."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_frame import load_catalog, validate
from quote_engine import resolve_design


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.design.read_text(encoding="utf-8"))
    resolved = resolve_design(data, load_catalog())
    result = validate(resolved)
    resolved["quote_summary"] = result["quote"]
    resolved["receipt_checklist"] = result["receipt_checklist"]
    resolved["assembly_plan"] = result["assembly_plan"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(resolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.output} · {result['readiness']} · 预算 ¥{result['quote']['total_range_cny'][0]:.2f}–¥{result['quote']['total_range_cny'][1]:.2f}")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
