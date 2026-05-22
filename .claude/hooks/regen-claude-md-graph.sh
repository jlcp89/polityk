#!/usr/bin/env bash
# Regenerate CLAUDE.md AUTO-MANAGED blocks (directory-tree, architecture-patterns)
# from graphify-out/graph.json. Invoked by /setup Phase 4.5 and /update Phase 3.5.
# Safe to re-run. No-ops if graph.json is missing or CLAUDE.md lacks markers.
set -euo pipefail

GRAPH="graphify-out/graph.json"
MD="CLAUDE.md"

[ -f "$GRAPH" ] || { echo "regen-graph: $GRAPH not found, skipping" >&2; exit 0; }
[ -f "$MD" ]    || { echo "regen-graph: $MD not found, skipping" >&2; exit 0; }
command -v python3 >/dev/null 2>&1 || { echo "regen-graph: python3 not found, skipping" >&2; exit 0; }

python3 - "$GRAPH" "$MD" <<'PY'
import json, re, sys, os
from collections import defaultdict, Counter

graph_path, md_path = sys.argv[1], sys.argv[2]
with open(graph_path) as f:
    g = json.load(f)

nodes = g.get("nodes", [])
links = g.get("links", g.get("edges", []))
if not nodes:
    sys.exit(0)

degree = Counter()
for e in links:
    degree[e.get("source")] += 1
    degree[e.get("target")] += 1

# Directory tree: group by dirname, capped at 2 levels
by_dir = defaultdict(list)
for n in nodes:
    src = n.get("source_file") or ""
    d = os.path.dirname(src)
    if not d:
        key = "(root)"
    else:
        parts = d.split(os.sep)
        key = os.sep.join(parts[:2])
    by_dir[key].append(n)

tree_lines = []
for d in sorted(by_dir.keys()):
    grp = by_dir[d]
    top = sorted(grp, key=lambda n: -degree.get(n.get("id"), 0))[:5]
    labels = ", ".join(f"{n.get('label','?')}({degree.get(n.get('id'),0)})" for n in top)
    tree_lines.append(f"{d}/  [{len(grp)} nodes]  hubs: {labels}")
tree_lines = tree_lines[:40] or ["(graph produced no nodes)"]

# Architecture patterns: community summaries
by_comm = defaultdict(list)
for n in nodes:
    by_comm[n.get("community", -1)].append(n)

patt_lines = []
for cid in sorted(by_comm.keys(), key=lambda c: -len(by_comm[c]))[:8]:
    grp = by_comm[cid]
    ft = Counter(n.get("file_type","?") for n in grp).most_common(1)[0][0]
    top = sorted(grp, key=lambda n: -degree.get(n.get("id"), 0))[:3]
    names = ", ".join(n.get("label","?") for n in top)
    patt_lines.append(f"- **Community {cid}** ({ft}, {len(grp)} files): {names}")
if not patt_lines:
    patt_lines = ["(no communities detected)"]

def splice(text, marker, body):
    start = f"<!-- AUTO-MANAGED: {marker} -->"
    end   = f"<!-- /AUTO-MANAGED: {marker} -->"
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    repl = f"{start}\n{body}\n{end}"
    if pat.search(text):
        return pat.sub(repl, text)
    return text  # markers missing; silently skip

tree_body = "## Project Structure\n\n```\n" + "\n".join(tree_lines) + "\n```"
patt_body = "## Architecture Patterns\n\n" + "\n".join(patt_lines)

with open(md_path) as f:
    md = f.read()
md = splice(md, "directory-tree", tree_body)
md = splice(md, "architecture-patterns", patt_body)
with open(md_path, "w") as f:
    f.write(md)
print(f"regen-graph: updated {md_path} from {len(nodes)} nodes, {len(by_comm)} communities")
PY
