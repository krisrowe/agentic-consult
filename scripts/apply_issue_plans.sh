#!/usr/bin/env bash
set -euo pipefail

# apply_issue_plans.sh
# Apply a JSON plan produced by `generate_issue_plans.sh`.
# Safe by default: DRY_RUN=1 prints diffs; pass --commit to apply.
#
# Usage: scripts/apply_issue_plans.sh [PLAN_FILE] [--commit]

PLAN_FILE="${1:-.issue_plans.json}"
COMMIT=0
if [ "${2:-}" = "--commit" ] || [ "${3:-}" = "--commit" ]; then
  COMMIT=1
fi

if [ ! -f "$PLAN_FILE" ]; then
  echo "Plan file not found: $PLAN_FILE" >&2
  exit 2
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

jq -c '.[]' "$PLAN_FILE" | while read -r item; do
  src=$(echo "$item" | jq -r '.source')
  action=$(echo "$item" | jq -r '.action')
  target=$(echo "$item" | jq -r '.target')
  snippet=$(echo "$item" | jq -r '.snippet')

  # Normalize target path under issues dir if plain filename
  if [[ "$target" != */* ]]; then
    TARGET_PATH="issues/$target"
  else
    TARGET_PATH="$target"
  fi

  if [ "$action" = "append" ]; then
    if [ ! -f "$TARGET_PATH" ]; then
      echo "Target does not exist for append: $TARGET_PATH. Creating instead."
      mkdir -p "$(dirname "$TARGET_PATH")"
      if [ $COMMIT -eq 1 ]; then
        printf '%s
'"$(date -u +%Y-%m-%dT%H:%M:%SZ) - added from %s"\n" "$src" > "$TARGET_PATH"
      else
        echo "[DRY RUN] Would create file: $TARGET_PATH"
      fi
    fi

    # prepare new content file
    NEWFILE="$TMPDIR/$(basename "$TARGET_PATH")"
    cp "$TARGET_PATH" "$NEWFILE" 2>/dev/null || true
    printf '\n\n## Update: %s\n\n%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ) - from $src" "$snippet" >> "$NEWFILE"

    if [ $COMMIT -eq 1 ]; then
      # backup
      cp -- "$TARGET_PATH" "$TARGET_PATH.bak.$(date +%s)" 2>/dev/null || true
      mv -- "$NEWFILE" "$TARGET_PATH"
      echo "Appended to $TARGET_PATH"
    else
      echo "[DRY RUN] Diff for $TARGET_PATH:" 
      git --no-pager diff --no-index --color=auto "$TARGET_PATH" "$NEWFILE" || true
    fi

  elif [ "$action" = "create" ]; then
    TARGET_DIR=$(dirname "$TARGET_PATH")
    mkdir -p "$TARGET_DIR"
    if [ -f "$TARGET_PATH" ]; then
      echo "Target already exists: $TARGET_PATH — skipping create (use update)."
      continue
    fi
    if [ $COMMIT -eq 1 ]; then
      printf '# %s\n\n%s\n' "$(basename "$TARGET_PATH" .md | sed -E 's/-/ /g' | sed -E 's/^./\u\0/')" "$snippet" > "$TARGET_PATH"
      echo "Created $TARGET_PATH"
    else
      echo "[DRY RUN] Would create $TARGET_PATH with snippet:" 
      echo "$snippet" | sed 's/^/  /'
    fi
  else
    echo "Unknown action: $action for source $src" >&2
  fi
done

if [ $COMMIT -eq 0 ]; then
  echo
  echo "Dry run complete. Re-run with --commit to apply changes."
fi

exit 0
