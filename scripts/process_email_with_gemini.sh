#!/usr/bin/env bash
set -euo pipefail

# process_email_with_gemini.sh
# Send a single email (file) plus local issues context to the Gemini CLI and
# ask it to produce a structured plan to create or update issue .md files.
# The plan is saved to .issue_plans.json and then passed to
# scripts/apply_issue_plans.sh for dry-run or commit.
#
# Usage:
#   scripts/process_email_with_gemini.sh <email_file> [--commit]

EMAIL_FILE="$1"
COMMIT=0
if [ "${2:-}" = "--commit" ] || [ "${3:-}" = "--commit" ]; then
  COMMIT=1
fi

if [ ! -f "$EMAIL_FILE" ]; then
  echo "Email file not found: $EMAIL_FILE" >&2
  exit 2
fi

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "GEMINI_API_KEY not set. Export it before running this script." >&2
  exit 3
fi

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$REPO_ROOT" ]; then
  echo "Not inside a git repository; run this from repo root." >&2
  exit 4
fi
cd "$REPO_ROOT"


ISSUES_DIR="${ISSUES_DIR:-issues}"
mkdir -p "$ISSUES_DIR"

OUT_PLAN=".issue_plans.json"
DEBUG_DIR=".debug"
mkdir -p "$DEBUG_DIR"

# Refresh local TickTick tasks so Gemini can reason about existing tasks.
TICKTICK_LOCAL=".ticktick_tasks.json"
echo "Refreshing local TickTick task list..."
exported=0

try_cmds=(
  "tt list --json"
  "tt --json list"
  "ticktick list --json"
  "ticktick-cli export --json"
  "ticktick export --json"
)
for c in "${try_cmds[@]}"; do
  if command -v $(echo "$c" | awk '{print $1}') >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    set +e
    eval $c > "$TICKTICK_LOCAL" 2>/dev/null
    rc=$?
    set -e
    if [ $rc -eq 0 ] && [ -s "$TICKTICK_LOCAL" ]; then
      echo "Exported tasks via: $c"
      exported=1
      break
    fi
  fi
done

if [ $exported -eq 0 ]; then
  if [ -f "tasks.json" ]; then
    cp tasks.json "$TICKTICK_LOCAL"
    echo "Using existing tasks.json -> $TICKTICK_LOCAL"
    exported=1
  else
    echo "No TickTick export available; writing empty task list to $TICKTICK_LOCAL"
    printf '[]' > "$TICKTICK_LOCAL"
  fi
fi

cp "$TICKTICK_LOCAL" "$DEBUG_DIR/$(basename $TICKTICK_LOCAL).debug"

# Gather a concise summary of existing issues (filename, title, excerpt)
EXISTING_SUMMARY=$(mktemp)
for f in $(find "$ISSUES_DIR" -maxdepth 1 -type f -name '*.md' 2>/dev/null | sort); do
  title=$(awk '/^#/{gsub(/^#+[ \t]*/,"",$0); print $0; exit}' "$f" || true)
  excerpt=$(head -c 800 "$f" | tr '\n' ' ' | sed 's/"/\\"/g')
  printf '{"file":"%s","title":"%s","excerpt":"%s"}\n' "$(basename "$f")" "${title}" "${excerpt}" >> "$EXISTING_SUMMARY"
done

EMAIL_CONTENT=$(sed -n '1,4000p' "$EMAIL_FILE" | sed 's/"/\\"/g')

TASKS_SUMMARY=$(jq -c '.[:10]' "$TICKTICK_LOCAL" 2>/dev/null || echo '[]')

PROMPT=$(cat <<-EOF
You are given a corpus of existing issue files for a project (each file name, title, and short excerpt) and one new email. Your job is to decide deterministically whether the email should be appended to an existing issue file or should create a new issue file.

Return a single JSON object on stdout with fields:
  {"source":"<email_path>", "action":"append"|"create", "target":"<relative-target-filename>", "snippet":"<markdown snippet to append or file body>", "reason":"<short reason>", "confidence":0.0}

Rules:
- Prefer append when there is a clear match by ticket number, thread-id, or strong title/keyword overlap.
- If multiple existing files are possible, pick the best match and include a short reason and confidence (0..1).
- For create, suggest a short hyphen-slug filename (YY-MM-DD_slug.md) as target and include the file body in "snippet".
- The snippet must be valid Markdown and include a leading header or update block if appending.
- Only output the single JSON object, nothing else.

Existing issues (one JSON per line):
$(cat "$EXISTING_SUMMARY")

Email file path: $EMAIL_FILE
Email content:
'''
$EMAIL_CONTENT
'''

Current TickTick tasks (first 10):
$TASKS_SUMMARY

EOF
)

printf '%s\n' "$PROMPT" > "$DEBUG_DIR/prompt_for_email_$(basename "$EMAIL_FILE").txt"

if ! command -v gemini >/dev/null 2>&1; then
  echo "gemini CLI not found. Install and authenticate it before running this script." >&2
  exit 5
fi

OUT_RAW="$DEBUG_DIR/gemini_raw_$(basename "$EMAIL_FILE").txt"
printf '%s\n' "$PROMPT" | gemini chat --stdin > "$OUT_RAW" 2>&1 || true

# Extract JSON object from Gemini output
JSON=$(tr '\n' ' ' < "$OUT_RAW" | sed -n 's/.*\({.*}\).*/\1/p' || true)
if [ -z "$JSON" ]; then
  echo "Gemini did not return a JSON object. See $OUT_RAW" >&2
  exit 6
fi

# Wrap into an array expected by apply_issue_plans
echo "[ $JSON ]" > "$OUT_PLAN"
cp "$OUT_RAW" "$DEBUG_DIR/last_raw_output.txt"

echo "Wrote plan to $OUT_PLAN (raw output in $OUT_RAW)."

# Invoke applier (dry-run unless --commit)
if [ $COMMIT -eq 1 ]; then
  scripts/apply_issue_plans.sh "$OUT_PLAN" --commit
else
  scripts/apply_issue_plans.sh "$OUT_PLAN"
fi

exit 0
