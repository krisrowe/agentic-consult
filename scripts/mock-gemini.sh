#!/bin/bash

# Mock Gemini script for testing/development
# Accepts arguments like the real CLI but outputs canned JSON

# Optional: Print arguments to stderr for debugging
echo "Mock Gemini called with args: $@" >&2

# Determine the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# Path to the mock data file
MOCK_DATA_FILE="$REPO_ROOT/mock-deltas.json"
EXAMPLE_DATA_FILE="$REPO_ROOT/mock-deltas.json.example"

if [ -f "$MOCK_DATA_FILE" ]; then
  cat "$MOCK_DATA_FILE"
else
  # Fallback canned response
  cat <<EOF
{
  "create": [
    {
      "title": "Mock Task (Fallback)",
      "priority": 1,
      "content": "No mock data file found."
    }
  ],
  "update": []
}
EOF
fi
