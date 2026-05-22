#!/usr/bin/env bash
# SessionStart hook: hint at recovery if project context exists
if [ -f "CONTEXT.md" ] && [ -s "CONTEXT.md" ]; then
  echo "Project context available in CONTEXT.md. Run /recover to load it, or describe what you need."
fi

# Knowledge graph status + staleness nudge
if [ -f "graphify-out/graph.json" ]; then
  graph_age_days=$(( ($(date +%s) - $(stat -c %Y graphify-out/graph.json 2>/dev/null || stat -f %m graphify-out/graph.json 2>/dev/null || echo 0)) / 86400 ))
  node_count=$(python3 -c "import json;print(len(json.load(open('graphify-out/graph.json')).get('nodes',[])))" 2>/dev/null || echo 0)
  file_count=$(git ls-files 2>/dev/null | wc -l)
  [ "$file_count" -eq 0 ] && file_count=$(find . -type f -not -path './.git/*' -not -path './node_modules/*' 2>/dev/null | wc -l)
  stale=0
  [ "$graph_age_days" -gt 14 ] && stale=1
  if [ "$node_count" -gt 0 ] && [ "$file_count" -gt 0 ]; then
    diff=$(( node_count > file_count ? node_count - file_count : file_count - node_count ))
    threshold=$(( file_count / 5 ))
    [ "$diff" -gt "$threshold" ] && stale=1
  fi
  if [ "$stale" -eq 1 ]; then
    echo "⚠ Knowledge graph may be stale (${graph_age_days}d old, ${node_count} nodes vs ${file_count} files) — run /graphify . --update or /update."
  else
    echo "Knowledge graph available at graphify-out/GRAPH_REPORT.md — read it before architecture questions."
  fi
fi
