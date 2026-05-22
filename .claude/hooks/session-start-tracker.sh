#!/usr/bin/env bash
# SessionStart hook (AFK mode): show ready issues from the configured tracker so /recover loads them automatically.
# Activated when the project's `.claude/automation/loop-prompt.md` exists.

# Detect tracker by inspecting the loop-prompt.md header
if [ ! -f ".claude/automation/loop-prompt.md" ]; then
  exit 0
fi

tracker=$(grep -m1 "Tracker:" ".claude/automation/loop-prompt.md" | sed -E 's/.*\*\*([a-z-]+)\*\*.*/\1/')

case "$tracker" in
  github)
    if command -v gh >/dev/null 2>&1; then
      ready=$(gh issue list --label ready-for-agent --state open --limit 5 --json number,title --jq '.[] | "  #\(.number) \(.title)"' 2>/dev/null)
      if [ -n "$ready" ]; then
        echo "Ready for agent (GitHub):"
        echo "$ready"
      else
        echo "No issues labeled ready-for-agent. Run /to-issues to add some."
      fi
    fi
    ;;
  local-issues)
    if [ -f "ISSUES.md" ]; then
      ready=$(awk '/^## \[open\]/{block=$0; tag=0; next} /agent-ready/{tag=1} /^## \[/ && block && tag {print "  " block; block=""; tag=0} END { if (block && tag) print "  " block }' ISSUES.md | head -5)
      if [ -n "$ready" ]; then
        echo "Ready for agent (ISSUES.md):"
        echo "$ready"
      else
        echo "ISSUES.md has no agent-ready entries. Run /to-issues to add some."
      fi
    fi
    ;;
esac
