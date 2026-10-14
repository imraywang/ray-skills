#!/usr/bin/env bash
# ray-broll environment self-check.
# Adapted from gbro-collage-broll (MIT, (c) 2026 狗哥笔记).
# Exit 0 = all good; exit 1 = at least one item missing (details on stdout).

set -u

VENV_PY="$HOME/hyperframes-projects/.omni-venv/bin/python"
FAIL=0

ok()   { printf 'PASS  %s\n' "$1"; }
bad()  { printf 'FAIL  %s\n' "$1"; FAIL=1; }

# 1. GEMINI_API_KEY（注意:agent 会话环境是启动快照,刚写入 ~/.zshrc 的
#    key 需要在命令里显式 source 才可见）
if [ -n "${GEMINI_API_KEY:-}" ]; then
  ok "GEMINI_API_KEY 已设置"
else
  bad "GEMINI_API_KEY 未设置（到 https://aistudio.google.com/apikey 创建后 export 到 shell 配置；agent 内记得 source）"
fi

# 2. ffmpeg / ffprobe
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  ok "ffmpeg / ffprobe 可用"
else
  bad "ffmpeg / ffprobe 缺失（macOS: brew install ffmpeg；Debian/Ubuntu: sudo apt install ffmpeg）"
fi

# 3. Python >= 3.10
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  ok "python3 >= 3.10"
else
  bad "python3 缺失或版本低于 3.10"
fi

# 4. shared venv with google-genai >= 2.10.0
if [ -x "$VENV_PY" ] && "$VENV_PY" - <<'PY' 2>/dev/null
import sys
from google import genai
parts = [int(x) for x in genai.__version__.split(".")[:2]]
sys.exit(0 if parts >= [2, 10] else 1)
PY
then
  ok "共享 venv 就绪（google-genai >= 2.10.0）"
else
  bad "共享 venv 未创建或 google-genai 版本过旧（创建：python3 -m venv ~/hyperframes-projects/.omni-venv && ~/hyperframes-projects/.omni-venv/bin/python -m pip install --upgrade 'google-genai>=2.10.0' 'httpx[socks]'）"
fi

# 5. FAL_KEY（只有 video-jobs 里用 provider: fal 时需要;缺失只提示不判 FAIL）
if [ -n "${FAL_KEY:-}" ]; then
  ok "FAL_KEY 已设置（fal 聚合可用）"
else
  printf 'WARN  %s\n' "FAL_KEY 未设置（只走 google 可忽略；要用 provider: fal 时到 https://fal.ai/dashboard/keys 创建后 export）"
fi

# 6. Pillow（render_caption.py / render_headline.py 用;共享 venv 或 python3 任一可用即可）
PIL_OK=0
for PY in "$VENV_PY" python3; do
  if command -v "$PY" >/dev/null 2>&1 && "$PY" -c 'import PIL' 2>/dev/null; then
    PIL_OK=1; break
  fi
done
if [ "$PIL_OK" = 1 ]; then
  ok "Pillow 可用（字幕 / 画内标题渲染）"
else
  bad "Pillow 缺失（~/hyperframes-projects/.omni-venv/bin/python -m pip install Pillow）"
fi

# 7. 中文字体（字幕 / 标题脚本优先 PingFang,退回 Hiragino Sans GB）
if [ -f /System/Library/Fonts/PingFang.ttc ]; then
  ok "PingFang 字体可用"
elif [ -f "/System/Library/Fonts/Hiragino Sans GB.ttc" ]; then
  ok "PingFang 缺失，退回 Hiragino Sans GB"
else
  bad "找不到 /System/Library/Fonts/PingFang.ttc（字幕与画内标题需要 macOS 系统中文字体）"
fi

exit $FAIL
