#!/usr/bin/env bash
set -euo pipefail

# generate_issue_plans.sh
# Scan existing issue files and source untracked .md files, ask Gemini to map
# sources to existing issues or propose new issue files. Output a single JSON
# plan file (.issue_plans.json).
#
# Usage: scripts/generate_issue_plans.sh [TARGET_DIR] [OUTFILE]
# TARGET_DIR defaults to . (repo root). OUTFILE defaults to .issue_plans.json

TARGET_DIR="${1:-.}"
OUTFILE="${2:-.issue_plans.json}"
CONFIG_FILE="config.yaml"

read_cfg(){
  local key="$1"
  awk -F":" -v k="$key" '$1==k {sub(/^[ \t]+/,"",$2); print $2; exit}' "$CONFIG_FILE" 2>/dev/null || true
}

ISSUES_DIR="${ISSUES_DIR:-$(read_cfg issues_dir || echo ./issues)}"
mkdir -p "$ISSUES_DIR"

REPO_TOP=$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$REPO_TOP" ]; then
  echo "Not in a git repo; this script expects to run from a repository." >&2
  exit 1
fi

cd "$REPO_TOP"

# Collect existing issues metadata
ISSUES_METADATA=""
for f in $(find "$ISSUES_DIR" -maxdepth 1 -type f -name "*.md" 2>/dev/null | sort); do
  title=$(awk '/^#/{gsub(/^#+[ \t]*/,"",$0); print $0; exit}' "$f" || true)
  excerpt=$(head -c 800 "$f" | tr '\n' ' ' | sed 's/"/\\"/g')
  ISSUES_METADATA+="FILE:$(basename "$f"),TITLE:$(echo $title | sed 's/,/ /g'),EXCERPT:${excerpt}\n"
done

# Find untracked source .md files (candidates)
mapfile -t CANDIDATES < <(git status --porcelain --untracked-files=all | awk '/^\?\?/ {print $2}' | grep -E '\.md$' || true)
if [ ${#CANDIDATES[@]} -eq 0 ]; then
  echo "No untracked .md files found."
  exit 0
fi

PLANS="[]"

for src in "${CANDIDATES[@]}"; do
  content=$(head -c 12000 "$src" | sed 's/"/\\"/g')

  # Build prompt: include brief list of existing issues (filenames + titles)
  PROMPT_HEADER="You are an assistant that assigns new notes to existing issue files or creates new ones.\nReturn a single JSON object with fields: action ('append'|'create'), target (filename or suggested slug), snippet (markdown to append or file body).\nExisting issues:\n$ISSUES_METADATA\n\nNow consider this new source file: $src\nContent:\n" 

  PROMPT="$PROMPT_HEADER
'"$content"'

  if command -v gemini >/dev/null 2>&1 && [ -n "${GEMINI_API_KEY:-}" ]; then
    OUT=$(printf '%s\n' "$PROMPT" | gemini chat --stdin 2>/dev/null || true)
    JSON_SNIP=$(printf '%s\n' "$OUT" | tr '\n' ' ' | sed -n 's/.*\({.*}\).*/\1/p' || true)
  else
    # Fallback: simple heuristic - match by title keyword overlap
    title=$(awk '/^#/{gsub(/^#+[ \t]*/,"",$0); print $0; exit}' "$src" || true)
    MATCH_FILE=""
    for f in $(find "$ISSUES_DIR" -maxdepth 1 -type f -name "*.md" 2>/dev/null); do
      if grep -qi "$(echo "$title" | awk '{print $1}')" "$f"; then
        MATCH_FILE=$(basename "$f")
        break
      fi
    done
    if [ -n "$MATCH_FILE" ]; then
      # create a minimal JSON
      JSON_SNIP="{\"action\":\"append\",\"target\":\"$MATCH_FILE\",\"snippet\":\"$(head -c 400 "$src" | sed 's/"/\\"/g' | tr '\n' ' ')\"}"
    else
      SUGGEST_SLUG=$(echo "$title" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g' | sed -E 's/^-+|-+$//g')
      JSON_SNIP="{\"action\":\"create\",\"target\":\"${SUGGEST_SLUG}.md\",\"snippet\":\"$(head -c 400 "$src" | sed 's/"/\\"/g' | tr '\n' ' ')\"}"
    fi
  fi

  if [ -n "$JSON_SNIP" ]; then
    # accumulate into PLANS using python for valid JSON array append
    PLANS=$(python3 - <<PY
import json,sys
old=json.loads('''$PLANS''')
new=json.loads('''$JSON_SNIP''')
old.append({'source':'$src', **new})
print(json.dumps(old))
PY
)
  fi
done

echo "$PLANS" > "$OUTFILE"
echo "Wrote plan to $OUTFILE"

exit 0
