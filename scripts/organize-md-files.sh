#!/usr/bin/env bash
set -euo pipefail

# organize-md-files.sh
# Find untracked .md files (reported by git), classify them with Gemini CLI
# (if available) to determine whether they pertain to the customer and to
# extract a short subject. If relevant, move the file into the project's
# issues directory using a date-time + subject-slug naming pattern and
# relocate related content (sibling files with the same basename prefix)
# into an issue subfolder.
#
# Usage:
#  scripts/organize-md-files.sh [TARGET_DIR] [--commit]
# By default runs in dry-run mode and prints planned moves.

TARGET_DIR="${1:-.}"
COMMIT=0
if [ "${2:-}" = "--commit" ] || [ "${3:-}" = "--commit" ]; then
  COMMIT=1
fi

# Explicitly disallow any flag that would include tracked files
for a in "$@"; do
  case "$a" in
    --include-tracked|--tracked|--include-tracked=*)
      echo "This script will NOT process tracked files. Remove the --include-tracked/--tracked flag and run again." >&2
      exit 2
      ;;
  esac
done

CONFIG_FILE="config.yaml"
read_cfg(){
  local key="$1"
  awk -F":" -v k="$key" '$1==k {sub(/^[ \t]+/,"",$2); print $2; exit}' "$CONFIG_FILE" 2>/dev/null || true
}

ISSUES_DIR="${ISSUES_DIR:-$(read_cfg issues_dir || echo ./issues)}"
mkdir -p "$ISSUES_DIR"

# Get repo top-level; require git repo because we focus on untracked files
REPO_TOP=$(git -C "$TARGET_DIR" rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$REPO_TOP" ]; then
  echo "Not inside a git repository. This script focuses on untracked files reported by git." >&2
  echo "If you want to organize standalone files, run a different tool or initialize a git repo." >&2
  exit 1
fi

cd "$REPO_TOP"

# Find untracked .md files (git status --porcelain reports '??' for untracked)
mapfile -t UNTRACKED_ALL < <(git status --porcelain --untracked-files=all | awk '/^\?\?/ {print $2}')
UNTRACKED=()
for p in "${UNTRACKED_ALL[@]:-}"; do
  if [[ "$p" =~ \.md$ ]]; then
    # limit to files under the target dir if a path was passed
    if [ "$TARGET_DIR" = "." ] || [[ "$p" == $(realpath --relative-to="$REPO_TOP" "${TARGET_DIR}")/* ]] || [[ "$p" == ${TARGET_DIR}/* ]]; then
      UNTRACKED+=("$p")
    fi
  fi
done

if [ ${#UNTRACKED[@]} -eq 0 ]; then
  echo "No untracked .md files found under '$TARGET_DIR'. Nothing to do."
  exit 0
fi

# Load per-customer patterns from scripts/read_customers.py if available
CUSTOMER_NAME=""
declare -a C_PAT_TYPES
declare -a C_PAT_SLUGS
declare -a C_PAT_VALS
if python3 scripts/read_customers.py >/dev/null 2>&1; then
  while IFS=$'\t' read -r ptype pslug pval; do
    C_PAT_TYPES+=("$ptype")
    C_PAT_SLUGS+=("$pslug")
    C_PAT_VALS+=("$pval")
  done < <(python3 scripts/read_customers.py)
else
  # fallback: read single customer.yaml in repo root if present
  CUSTOMER_FILE="customer.yaml"
  if [ -f "$CUSTOMER_FILE" ]; then
    CUSTOMER_NAME=$(awk -F":" '/^name:/ {gsub(/^[ \t]+|\"/,"",$2); print $2; exit}' "$CUSTOMER_FILE") || true
  fi
fi

# Helper: build slug from subject
slugify(){
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g' | sed -E 's/^-+|-+$//g'
}

# Helper: ensure unique destination filename
unique_dest(){
  local basepath="$1"
  if [ ! -e "$basepath" ]; then
    printf '%s' "$basepath"
    return
  fi
  local i=1
  local ext="${basepath##*.}"
  local prefix="${basepath%.*}"
  while [ -e "${prefix}-${i}.${ext}" ]; do
    i=$((i+1))
  done
  printf '%s' "${prefix}-${i}.${ext}"
}

echo "Found ${#UNTRACKED[@]} untracked .md file(s) to consider:"
for f in "${UNTRACKED[@]}"; do
  echo " - $f"
done

PLAN=()

for src in "${UNTRACKED[@]}"; do
  # read a bounded chunk of the file for classification
  CONTENT=$(head -c 16000 "$src" || true)

  SUBJECT=""
  RELEVANT=0
  MATCHED_SLUG=""

  # Use Gemini CLI if available and GEMINI_API_KEY is present; otherwise fallback
  if command -v gemini >/dev/null 2>&1 && [ -n "${GEMINI_API_KEY:-}" ]; then
    PROMPT=$(cat <<-EOF
You are a classifier. Given the following Markdown file content and the customer name, answer with a JSON object on a single line.
Fields: {"relevant": true|false, "subject": "A short descriptive subject (6 words max)"}
Customer: ${CUSTOMER_NAME}
Content:
'''
${CONTENT}
'''
Only output the JSON object.
EOF
)
    OUT=$(printf '%s\n' "$PROMPT" | gemini chat --stdin 2>/dev/null || true)
    # Extract JSON-looking substring between first { and last }
    JSON=$(printf '%s\n' "$OUT" | tr '\n' ' ' | sed -n 's/.*\({.*}\).*/\1/p' || true)
    if [ -n "$JSON" ]; then
      # parse relevant and subject using sed/grep
      if printf '%s' "$JSON" | grep -qi '"relevant"[[:space:]]*:[[:space:]]*true'; then
        RELEVANT=1
      fi
      SUBJECT=$(printf '%s' "$JSON" | sed -n 's/.*"subject"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)
    fi
  fi

  # Fallback heuristics
  if [ -z "$SUBJECT" ]; then
    # first markdown heading
    SUBJECT=$(awk '/^#/{gsub(/^#+[ \t]*/,"",$0); print $0; exit}' "$src" || true)
  fi
  if [ -z "$SUBJECT" ]; then
    # filename base
    SUBJECT="$(basename "$src" .md)"
  fi

  # quick pattern fallback: check per-customer patterns (names, slugs, keywords)
  if [ ${#C_PAT_VALS[@]} -gt 0 ]; then
    for i in "${!C_PAT_VALS[@]}"; do
      val="${C_PAT_VALS[i]}"
      slug="${C_PAT_SLUGS[i]}"
      if [ -n "$val" ] && grep -F -i -q -- "$val" "$src" 2>/dev/null; then
        RELEVANT=1
        MATCHED_SLUG="$slug"
        break
      fi
    done
  else
    if [ -z "$RELEVANT" ] || [ "$RELEVANT" -eq 0 ]; then
      if [ -n "$CUSTOMER_NAME" ] && grep -qi -- "$CUSTOMER_NAME" "$src"; then
        RELEVANT=1
      fi
    fi
  fi

  if [ "$RELEVANT" -eq 0 ]; then
    echo "Skipping (not relevant): $src"
    continue
  fi

  # determine date-time prefix: prefer a YYYY-MM-DD in file, else mtime
  DATESTR=$(grep -Eo '\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b' "$src" | head -n1 || true)
  if [ -n "$DATESTR" ]; then
    TIMEPART=$(grep -Eo '[0-9]{2}:[0-9]{2}' "$src" | head -n1 || true)
    if [ -n "$TIMEPART" ]; then
      DATETIME="${DATESTR}_$(echo $TIMEPART | tr -d ':')"
    else
      DATETIME="${DATESTR}_0000"
    fi
  else
    DATETIME=$(date -r "$src" +%Y-%m-%d_%H%M)
  fi

  SLUG=$(slugify "$SUBJECT")
  if [ -z "$SLUG" ]; then
    SLUG="$(slugify "$(basename "$src" .md)")"
  fi

  # Destination: per-customer issues under customers/<slug>/issues
  if [ -n "$MATCHED_SLUG" ]; then
    ISSUE_SUBDIR="$REPO_TOP/customers/$MATCHED_SLUG/issues"
    DEST_BASE="$REPO_TOP/customers/$MATCHED_SLUG/issues/${DATETIME}_${SLUG}.md"
  else
    ISSUE_SUBDIR="$ISSUES_DIR/$SLUG"
    DEST_BASE="$ISSUES_DIR/${DATETIME}_${SLUG}.md"
  fi
  DEST=$(unique_dest "$DEST_BASE")

  # find related sibling files: same basename prefix (before first dot) or files that start with basename
  base_no_ext="$(basename "$src" .md)"
  RELATED=( )
  while IFS= read -r -d $'\0' s; do RELATED+=("$s"); done < <(find "$(dirname "$src")" -maxdepth 1 -type f -iname "${base_no_ext}*" -print0)

  PLAN+=("$src -> $DEST (into $ISSUE_SUBDIR) with related: ${RELATED[*]}")

  # If file is tracked, abort and instruct user to handle manually
  if git ls-files --error-unmatch -- "$src" >/dev/null 2>&1; then
    echo "ERROR: $src appears to be tracked by git and would need to be moved into $ISSUE_SUBDIR"
    echo "Guidance: To preserve history, run: git mv $src $DEST and adjust related files manually."
    echo "Aborting organizer. No changes made."
    exit 2
  fi

  if [ $COMMIT -eq 1 ]; then
    mkdir -p "$ISSUE_SUBDIR"
    mv -- "$src" "$DEST"
    for r in "${RELATED[@]:-}"; do
      [ "$r" = "$src" ] && continue
      mv -- "$r" "$ISSUE_SUBDIR/" || true
    done
    echo "Moved: $src -> $DEST"
  else
    echo "[DRY RUN] Would move: $src -> $DEST and related files to $ISSUE_SUBDIR/"
  fi
done

echo
echo "Plan summary:"
for p in "${PLAN[@]:-}"; do
  echo " - $p"
done

if [ $COMMIT -eq 0 ]; then
  echo
  echo "Dry run complete. To perform moves, re-run with --commit:" 
  echo "  scripts/organize-md-files.sh ${TARGET_DIR} --commit"
fi

exit 0
