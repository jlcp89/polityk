#!/usr/bin/env bash
# PreToolUse hook: Block destructive commands
# Reads JSON from stdin: {"tool_name": "Bash", "tool_input": {"command": "..."}}

set -euo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty')

# Only check Bash commands
if [[ "$TOOL" != "Bash" ]]; then
  exit 0
fi

CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
if [[ -z "$CMD" ]]; then
  exit 0
fi

# rm -rf on dangerous paths
if echo "$CMD" | grep -qE 'rm\s+(-[a-zA-Z]*r[a-zA-Z]*f|(-[a-zA-Z]*f[a-zA-Z]*r))\s+(\/|~|\$HOME|\/home)\b'; then
  echo "BLOCKED: rm -rf on root/home path. Use a specific path instead." >&2
  exit 2
fi

# git push --force to main/master
if echo "$CMD" | grep -qE 'git\s+push\s+.*--force.*\s+(main|master)\b|git\s+push\s+.*\s+(main|master)\s+.*--force'; then
  echo "BLOCKED: Force push to main/master. Push to a feature branch instead." >&2
  exit 2
fi

# git reset --hard
if echo "$CMD" | grep -qE 'git\s+reset\s+--hard'; then
  echo "BLOCKED: git reset --hard destroys uncommitted work. Use 'git stash' or 'git restore <file>' instead." >&2
  exit 2
fi

# DROP TABLE / DROP DATABASE
if echo "$CMD" | grep -qiE 'DROP\s+(TABLE|DATABASE)'; then
  echo "BLOCKED: DROP TABLE/DATABASE is irreversible. Use migrations instead." >&2
  exit 2
fi

# chmod 777
if echo "$CMD" | grep -qE 'chmod\s+777'; then
  echo "BLOCKED: chmod 777 is overly permissive. Use specific permissions (e.g., 755, 644)." >&2
  exit 2
fi

exit 0
