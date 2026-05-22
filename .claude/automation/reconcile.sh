#!/usr/bin/env bash
# reconcile.sh — find closed AFK issues whose agent/issue-N branches never
# got merged into main and merge them now. Idempotent; safe to re-run.
#
# Catches the failure mode where the AFK supervisor died (or was killed)
# AFTER a worker committed + closed an issue but BEFORE the supervisor's
# merge step ran. GitHub shows the issue closed; main does not have the
# commit. Without this script, the work is silently lost.
#
# Usage:
#   ./reconcile.sh             # dry-run: list what would be merged, exit 0
#   ./reconcile.sh --apply     # do it
#   ./reconcile.sh --limit N   # only inspect the N most recently closed
#                              # issues (default: 100)
#
# Refuses to operate if the working tree is dirty.

set -euo pipefail
IFS=$'\n\t'

APPLY=0
LIMIT=100
while [ $# -gt 0 ]; do
    case "$1" in
        --apply) APPLY=1; shift ;;
        --limit) LIMIT="${2:?--limit needs N}"; shift 2 ;;
        *) echo "usage: $0 [--apply] [--limit N]" >&2; exit 2 ;;
    esac
done

command -v gh >/dev/null 2>&1 || { echo "error: gh CLI required" >&2; exit 127; }
command -v jq >/dev/null 2>&1 || { echo "error: jq required" >&2; exit 127; }

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

# Refuse on dirty tree (a merge could clobber uncommitted work).
if ! git diff-index --quiet HEAD --; then
    echo "error: working tree is dirty; commit or stash first" >&2
    exit 1
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "error: must be on 'main' (currently on '$CURRENT_BRANCH')" >&2
    exit 1
fi

echo "reconcile: fetching origin..."
git fetch origin --prune

mapfile -t CLOSED < <(
    gh issue list --state closed --limit "$LIMIT" --json number --jq '.[].number'
)

ORPHANS=()
PHANTOMS=()   # closed-and-merged-via-different-SHA
for n in "${CLOSED[@]}"; do
    branch="agent/issue-$n"
    # Skip if the agent branch doesn't exist upstream.
    git show-ref --quiet --verify "refs/remotes/origin/$branch" || continue
    # Skip if the tip is already in main (true ancestor — direct merge).
    if git merge-base --is-ancestor "origin/$branch" main 2>/dev/null; then
        continue
    fi
    # Phantom-orphan check: is there a commit on main whose subject starts
    # with "Issue #N:" or contains "issue #N" in the merge subject? The AFK
    # supervisor's conflict-resolve flow rewrites the branch then merges; the
    # remote agent branch is left dangling at the pre-rewrite SHA. Such
    # branches look like orphans by SHA-ancestry but the WORK is already in
    # main. We classify them separately so --apply doesn't try to re-merge
    # stale code that will conflict by definition.
    if git log --format='%s' main \
        | grep -qiE "^(Issue|merge: issue) #${n}([^0-9]|$)"; then
        PHANTOMS+=("$n")
        continue
    fi
    ORPHANS+=("$n")
done

if [ "${#PHANTOMS[@]}" -gt 0 ]; then
    echo "reconcile: ${#PHANTOMS[@]} phantom branch(es) (work already in main under a different SHA):"
    for n in "${PHANTOMS[@]}"; do
        branch="agent/issue-$n"
        landed="$(git log --format='%h %s' main | grep -iE "^[0-9a-f]+ (Issue|merge: issue) #${n}([^0-9]|$)" | head -1)"
        echo "  #$n → $branch (landed in main as: ${landed:-?})"
    done
    echo "          delete with: git push origin --delete agent/issue-<N>"
    echo ""
fi

if [ "${#ORPHANS[@]}" -eq 0 ]; then
    echo "reconcile: all closed AFK issues are already merged ✓"
    exit 0
fi

echo "reconcile: ${#ORPHANS[@]} orphan branch(es) detected:"
for n in "${ORPHANS[@]}"; do
    branch="agent/issue-$n"
    short="$(git log -1 --format='%h %s' "origin/$branch" 2>/dev/null || echo '?')"
    echo "  #$n → $branch ($short)"
done

if [ "$APPLY" -ne 1 ]; then
    echo ""
    echo "reconcile: dry-run (no changes). Re-run with --apply to merge."
    exit 0
fi

MERGED=()
FAILED=()
for n in "${ORPHANS[@]}"; do
    branch="agent/issue-$n"
    echo ""
    echo "reconcile: merging $branch → main..."
    if git merge --no-ff "origin/$branch" \
           -m "merge: issue #$n (reconcile — orphaned by supervisor death)"; then
        MERGED+=("$n")
        echo "reconcile: #$n merged ✓"
    else
        git merge --abort 2>/dev/null || true
        FAILED+=("$n")
        echo "reconcile: #$n MERGE FAILED — manual review needed" >&2
    fi
done

if [ "${#MERGED[@]}" -gt 0 ]; then
    echo ""
    echo "reconcile: pushing ${#MERGED[@]} merge(s) to origin..."
    git push origin main
    echo "reconcile: pushed."
fi

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo ""
    echo "reconcile: ${#FAILED[@]} branch(es) failed to merge: ${FAILED[*]}" >&2
    echo "          inspect with: git merge --no-ff origin/agent/issue-<N>" >&2
    exit 1
fi
