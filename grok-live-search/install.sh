#!/usr/bin/env bash
# Link this skill into Codex, Claude Code, and generic agent skill directories.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
NAME="grok-live-search"
HOSTS=(
  "$HOME/.agents/skills"
  "$HOME/.codex/skills"
  "$HOME/.claude/skills"
)

usage() {
  cat <<'EOF'
Usage: install.sh [--uninstall]

  (default)   Symlink this directory into:
                ~/.agents/skills/grok-live-search
                ~/.codex/skills/grok-live-search
                ~/.claude/skills/grok-live-search
  --uninstall Remove those symlinks when they point at this directory.
EOF
}

if [[ ! -f "$SKILL_DIR/SKILL.md" ]]; then
  echo "FAIL: SKILL.md is missing in $SKILL_DIR" >&2
  exit 1
fi

uninstall=0
for arg in "$@"; do
  case "$arg" in
    --uninstall) uninstall=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "FAIL: unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

linked=0
skipped=0
removed=0

for host in "${HOSTS[@]}"; do
  target="$host/$NAME"
  if [[ "$uninstall" -eq 1 ]]; then
    if [[ -L "$target" ]]; then
      current="$(readlink "$target")"
      if [[ "$current" == "$SKILL_DIR" ]]; then
        rm "$target"
        echo "removed: $target"
        removed=$((removed + 1))
      else
        echo "skip: $target points at $current"
        skipped=$((skipped + 1))
      fi
    elif [[ -e "$target" ]]; then
      echo "skip: $target exists and is not a symlink"
      skipped=$((skipped + 1))
    else
      echo "skip: $target is not installed"
      skipped=$((skipped + 1))
    fi
    continue
  fi

  mkdir -p "$host"
  if [[ -L "$target" ]]; then
    current="$(readlink "$target")"
    if [[ "$current" == "$SKILL_DIR" ]]; then
      echo "ok: $target"
      skipped=$((skipped + 1))
      continue
    fi
    rm "$target"
  elif [[ -e "$target" ]]; then
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    backup="${target}.bak-${stamp}"
    mv "$target" "$backup"
    echo "backed up: $target -> $backup"
  fi
  ln -s "$SKILL_DIR" "$target"
  echo "linked: $target -> $SKILL_DIR"
  linked=$((linked + 1))
done

if [[ "$uninstall" -eq 1 ]]; then
  echo "uninstalled $removed link(s); skipped $skipped"
else
  echo "installed $linked host(s); already current $skipped"
  echo "Requires ~/.grok/bin/grok and a prior grok login."
fi
