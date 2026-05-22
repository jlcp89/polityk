#!/usr/bin/env bash
# Hook: Block TaskOutput with block=false
# Non-blocking TaskOutput dumps raw streaming transcripts (10-40k+ tokens)
# into the main conversation context. Always wait for completion notification.

input="${CLAUDE_TOOL_INPUT:-}"

if echo "$input" | grep -qE '"block"\s*:\s*false'; then
  echo "BLOCKED: TaskOutput(block=false) wastes 10-40k+ tokens by dumping raw agent transcripts into context." >&2
  echo "Instead: wait for the completion notification, or use: Bash(tail -5 <output_file>)" >&2
  exit 2
fi

exit 0
