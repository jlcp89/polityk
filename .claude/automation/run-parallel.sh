#!/usr/bin/env bash
# run-parallel.sh — parallel issue execution supervisor.
#
# Usage:
#   ./run-parallel.sh <N> [<max-rounds>]
#       N           — max concurrent workers (typical: 2–4)
#       max-rounds  — supervisor cycles before giving up (default: unbounded)
#
# Design — supervisor + git worktree workers:
#   1. Supervisor parses each open AFK issue's body for "Blocked by: #X, #Y"
#      (the format /to-issues writes) and computes the unblocked set.
#   2. Each unblocked issue is assigned to a worker. The worker runs in its
#      own git worktree at /tmp/<proj>-worktrees-<ts>/issue-<N> so concurrent
#      commits land on separate branches without touching the main checkout.
#   3. Supervisor uses `wait -n` to react as soon as ANY worker finishes,
#      then recomputes the unblocked set (the just-closed issue's children
#      may now be pickable) and dispatches replacement work.
#
# Non-duplication guarantees:
#   - Single decision-maker (only the supervisor calls $ISSUE_LIST_CMD).
#   - In-flight tracking via the `pids` map subtracts active workers from
#     the pickable set on every recompute.
#   - Worker uses `run-loop.sh --issue N` and exits 2 with NOT PICKABLE if
#     a race closed the issue before it started.
#   - Branch names are issue-numbered (agent/issue-<N>) — no collision.
#
# Time-optimization:
#   - `wait -n` reaps the FIRST finished worker; doesn't gate on the slowest.
#   - Worktrees share .git (cheap to spin up — ~50ms per worker).
#   - No polling, no sleep — event-driven dispatch.

set -euo pipefail
IFS=$'\n\t'

# ── Pre-flight ──────────────────────────────────────────────────────────────
N="${1:?usage: $0 <N> [<max-rounds>]}"
MAX_ROUNDS="${2:-0}"   # 0 = unbounded
[[ "$N" =~ ^[1-9][0-9]*$ ]] || { echo "error: N must be a positive integer" >&2; exit 2; }

command -v jq >/dev/null 2>&1     || { echo "error: jq required" >&2; exit 127; }
command -v claude >/dev/null 2>&1 || { echo "error: claude CLI not on PATH" >&2; exit 127; }
git worktree --help >/dev/null 2>&1 || { echo "error: git worktree unavailable" >&2; exit 127; }

REPO_ROOT="$(git rev-parse --show-toplevel)"
ENV_FILE="$REPO_ROOT/.claude/automation/loop-prompt.env"
RUN_LOOP="$REPO_ROOT/.claude/automation/run-loop.sh"

[ -f "$ENV_FILE" ] || { echo "error: $ENV_FILE not found" >&2; exit 1; }
[ -x "$RUN_LOOP" ] || { echo "error: $RUN_LOOP not executable" >&2; exit 1; }

# Refuse to start if the working tree is dirty — worktrees would inherit junk.
if ! git diff-index --quiet HEAD --; then
    echo "error: working tree has uncommitted changes; commit or stash first" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"   # provides ISSUE_LIST_CMD, ISSUE_CLOSE_CMD

PROJECT="$(basename "$REPO_ROOT")"
WORKTREE_ROOT="/tmp/${PROJECT}-worktrees-$(date +%s)"
mkdir -p "$WORKTREE_ROOT"
SUPERVISOR_LOG="$WORKTREE_ROOT/supervisor.log"
echo "supervisor log: $SUPERVISOR_LOG"
echo "worktree root:  $WORKTREE_ROOT"
{
    echo "=== run-parallel.sh starting at $(date -Iseconds) ==="
    echo "N=$N MAX_ROUNDS=$MAX_ROUNDS"
} | tee -a "$SUPERVISOR_LOG"

# ── State ───────────────────────────────────────────────────────────────────
declare -A PID_TO_ISSUE=()   # pid → issue number
declare -A ISSUE_TO_PID=()   # issue number → pid (for in-flight subtraction)
declare -A ISSUE_TO_WT=()    # issue number → worktree path
declare -A DONE_ISSUES=()    # issue number → 1 (completed this session; never re-dispatch)
declare -A FAILED_ISSUES=()  # issue number → 1 (merge failed this session; never re-dispatch)
ROUND=0

# ── Cleanup ─────────────────────────────────────────────────────────────────
cleanup() {
    local signal="${1:-EXIT}"
    local delete_branches="${2:-0}"
    {
        echo "=== cleanup ($signal) at $(date -Iseconds) ==="
        echo "active workers: ${#PID_TO_ISSUE[@]}"
    } >> "$SUPERVISOR_LOG"
    # Send TERM to all live workers; give them 5s to finish their commit.
    for pid in "${!PID_TO_ISSUE[@]}"; do
        kill -TERM "$pid" 2>/dev/null || true
    done
    sleep 5 || true
    for pid in "${!PID_TO_ISSUE[@]}"; do
        kill -KILL "$pid" 2>/dev/null || true
    done
    # Prune all worktrees.
    for wt in "${ISSUE_TO_WT[@]}"; do
        git worktree remove --force "$wt" 2>/dev/null || true
    done
    git worktree prune 2>/dev/null || true
    # On TSTP (Ctrl+Z full-reset), also delete in-progress branches so a fresh restart is clean.
    if [ "$delete_branches" -eq 1 ]; then
        for issue_num in "${!ISSUE_TO_WT[@]}"; do
            git -C "$REPO_ROOT" branch -D "agent/issue-$issue_num" >>"$SUPERVISOR_LOG" 2>/dev/null || true
            echo "supervisor: deleted branch agent/issue-$issue_num" >>"$SUPERVISOR_LOG"
        done
    fi
    if [ "$signal" != "EXIT" ]; then
        local branch_msg
        [ "$delete_branches" -eq 1 ] && branch_msg="in-progress branches deleted" || branch_msg="completed branches stay"
        echo "stopped at round $ROUND — $branch_msg; logs at $WORKTREE_ROOT" >&2
        exit 130
    fi
}
trap 'cleanup INT'  INT
trap 'cleanup TERM' TERM
trap 'cleanup TSTP 1' TSTP   # Ctrl+Z: full teardown + branch delete for clean restart
trap 'cleanup EXIT' EXIT

# ── Helpers ─────────────────────────────────────────────────────────────────

# Parse both inline "Blocked by: #X" and "## Blocked by / - #X" section format.
# Stdin: JSON array of {number, body}. Stdout: unblocked issue numbers, one per line.
compute_unblocked() {
    local tracker_json="$1"
    local open_set
    open_set="$(echo "$tracker_json" | jq -r '.[].number' | sort -n)"

    while IFS= read -r issue_num; do
        local body blocked_region="" capture=0
        body="$(echo "$tracker_json" | jq -r ".[] | select(.number == $issue_num) | .body // \"\"")"

        # Capture everything from the "Blocked by" trigger line until the next heading.
        # Handles both inline ("**Blocked by**: #5") and section ("## Blocked by\n- #5").
        while IFS= read -r line; do
            if echo "$line" | grep -qiE '(^##[[:space:]]*|[*_]*)blocked by'; then
                capture=1
                blocked_region="$line"   # include the trigger line (catches inline refs)
                continue
            fi
            if [ "$capture" -eq 1 ]; then
                echo "$line" | grep -qE '^#' && break   # next heading ends the section
                blocked_region="${blocked_region}"$'\n'"$line"
            fi
        done <<< "$body"

        # No "Blocked by" found → unblocked.
        if [ -z "$blocked_region" ]; then
            echo "$issue_num"; continue
        fi

        # Explicit "none" → unblocked.
        if echo "$blocked_region" | grep -qiE 'none[[:space:]]*—|^[[:space:]]*-[[:space:]]*none|—[[:space:]]*can start'; then
            echo "$issue_num"; continue
        fi

        # Extract all #N references from the region.
        local blocker_nums
        blocker_nums="$(echo "$blocked_region" | grep -oE '#[0-9]+' | tr -d '#' || true)"
        if [ -z "$blocker_nums" ]; then
            echo "$issue_num"; continue
        fi

        local unmet=0 blocker
        while IFS= read -r blocker; do
            [ -z "$blocker" ] && continue
            echo "$open_set" | grep -qx "$blocker" && { unmet=1; break; }
        done <<< "$blocker_nums"
        [ "$unmet" -eq 0 ] && echo "$issue_num"
    done < <(echo "$open_set")
}

dispatch_worker() {
    local issue_num="$1"
    local wt="$WORKTREE_ROOT/issue-$issue_num"
    local branch="agent/issue-$issue_num"

    echo "supervisor: [$(date +%T)] creating worktree for #$issue_num on branch $branch" | tee -a "$SUPERVISOR_LOG"

    # Create the worktree on a fresh branch off HEAD.
    if git worktree add "$wt" -b "$branch" HEAD >>"$SUPERVISOR_LOG" 2>&1; then
        :
    else
        # Branch may already exist from a prior partial run — reuse it.
        git worktree add "$wt" "$branch" >>"$SUPERVISOR_LOG" 2>&1 || {
            echo "supervisor: [$(date +%T)] FAILED to create worktree for #$issue_num" | tee -a "$SUPERVISOR_LOG" >&2
            return 1
        }
    fi

    # Background the worker; capture its pid.
    (
        cd "$wt"
        bash "$RUN_LOOP" --issue "$issue_num"
    ) >>"$WORKTREE_ROOT/worker-$issue_num.log" 2>&1 &
    local pid=$!

    PID_TO_ISSUE[$pid]="$issue_num"
    ISSUE_TO_PID[$issue_num]="$pid"
    ISSUE_TO_WT[$issue_num]="$wt"

    echo "supervisor: [$(date +%T)] dispatched #$issue_num → pid=$pid | log: worker-$issue_num.log" | tee -a "$SUPERVISOR_LOG"
}

resolve_conflicts_with_claude() {
    local wt="$1"
    local issue_num="$2"
    local merge_branch="agent/issue-$issue_num"
    local resolve_prompt_file="$REPO_ROOT/.claude/automation/resolve-conflicts.md"

    [ -f "$resolve_prompt_file" ] || {
        echo "supervisor: [$(date +%T)] resolve-conflicts.md not found — skipping auto-resolve" | tee -a "$SUPERVISOR_LOG"
        return 1
    }

    local conflicted_files
    conflicted_files="$(git -C "$wt" diff --name-only --diff-filter=U)"
    [ -z "$conflicted_files" ] && {
        echo "supervisor: [$(date +%T)] no conflicted files detected in $wt" | tee -a "$SUPERVISOR_LOG"
        return 1
    }

    echo "supervisor: [$(date +%T)] invoking Claude to resolve conflicts for #$issue_num..." | tee -a "$SUPERVISOR_LOG"
    while IFS= read -r f; do
        echo "supervisor: [$(date +%T)]   conflict: $f" | tee -a "$SUPERVISOR_LOG"
    done <<< "$conflicted_files"

    local prompt
    prompt="$(cat "$resolve_prompt_file")

## Runtime context

- Issue: #${issue_num}
- Branch: ${merge_branch}
- Conflicted files detected by git:
$(echo "$conflicted_files" | sed 's/^/  - /')"

    local resolve_log="$WORKTREE_ROOT/resolve-$issue_num.jsonl"
    local claude_rc=0
    set +e
    (cd "$wt" && claude \
        --dangerously-skip-permissions \
        --print \
        --verbose \
        --output-format stream-json \
        --include-partial-messages \
        "$prompt") \
        | tee "$resolve_log" \
        | jq --unbuffered -rj \
            'select(.type == "assistant").message.content[]? | select(.type == "text").text // empty' \
            2>/dev/null \
        >>"$SUPERVISOR_LOG"
    claude_rc="${PIPESTATUS[0]}"
    set -e

    local sentinel
    sentinel="$(jq -r 'select(.type == "result").result // empty' "$resolve_log" 2>/dev/null || echo '')"
    echo "" >>"$SUPERVISOR_LOG"
    echo "supervisor: [$(date +%T)] Claude conflict-resolver finished rc=$claude_rc" | tee -a "$SUPERVISOR_LOG"

    if [[ "$sentinel" == *"<promise>RESOLVED</promise>"* ]]; then
        echo "supervisor: [$(date +%T)] conflicts RESOLVED by Claude for #$issue_num" | tee -a "$SUPERVISOR_LOG"
        return 0
    else
        echo "supervisor: [$(date +%T)] conflicts UNRESOLVABLE for #$issue_num (sentinel: ${sentinel:-none})" | tee -a "$SUPERVISOR_LOG"
        return 1
    fi
}

promote_newly_unblocked() {
    # After a merge, find 'blocked' issues whose every blocker is now closed
    # and promote them to 'ready-for-agent' so the next round picks them up.

    local all_open_nums
    all_open_nums="$(gh issue list --state open --limit 500 --json number \
        2>>"$SUPERVISOR_LOG" | jq -r '.[].number' | sort -n || true)"
    [ -z "$all_open_nums" ] && return 0

    local blocked_json
    blocked_json="$(gh issue list --label blocked --state open --limit 200 \
        --json number,body 2>>"$SUPERVISOR_LOG" || echo '[]')"

    local n body blocked_region capture line blocker_nums unmet blocker
    while IFS= read -r n; do
        [ -z "$n" ] && continue
        body="$(echo "$blocked_json" | jq -r ".[] | select(.number == $n) | .body // \"\"")"
        blocked_region="" capture=0

        while IFS= read -r line; do
            if echo "$line" | grep -qiE '(^##[[:space:]]*|[*_]*)blocked by'; then
                capture=1; blocked_region="$line"; continue
            fi
            if [ "$capture" -eq 1 ]; then
                echo "$line" | grep -qE '^#' && break
                blocked_region="${blocked_region}"$'\n'"$line"
            fi
        done <<< "$body"

        [ -z "$blocked_region" ] && continue

        if echo "$blocked_region" | grep -qiE 'none[[:space:]]*—|^[[:space:]]*-[[:space:]]*none|—[[:space:]]*can start'; then
            echo "supervisor: [$(date +%T)] promoting #$n (no blockers) → ready-for-agent" | tee -a "$SUPERVISOR_LOG"
            gh issue edit "$n" --add-label "ready-for-agent" --remove-label "blocked" >>"$SUPERVISOR_LOG" 2>&1 || true
            continue
        fi

        blocker_nums="$(echo "$blocked_region" | grep -oE '#[0-9]+' | tr -d '#' || true)"
        [ -z "$blocker_nums" ] && continue

        unmet=0
        while IFS= read -r blocker; do
            [ -z "$blocker" ] && continue
            echo "$all_open_nums" | grep -qx "$blocker" && { unmet=1; break; }
        done <<< "$blocker_nums"

        if [ "$unmet" -eq 0 ]; then
            echo "supervisor: [$(date +%T)] promoting #$n: all blockers resolved → ready-for-agent" | tee -a "$SUPERVISOR_LOG"
            gh issue edit "$n" --add-label "ready-for-agent" --remove-label "blocked" >>"$SUPERVISOR_LOG" 2>&1 || true
        fi
    done <<< "$(echo "$blocked_json" | jq -r '.[].number' | sort -n)"
}

reap_one() {
    # Wait for ANY background worker to finish; reap, auto-merge, and clean up its slot.
    local pid rc issue_num wt
    set +e
    wait -n -p pid
    rc=$?
    set -e
    [ -z "${pid:-}" ] && return 0

    issue_num="${PID_TO_ISSUE[$pid]:-}"
    [ -z "$issue_num" ] && return 0
    wt="${ISSUE_TO_WT[$issue_num]:-}"

    local ts
    ts="$(date +%T)"
    case "$rc" in
        0)   echo "supervisor: [$ts] #$issue_num DONE (rc=0)"            | tee -a "$SUPERVISOR_LOG" ;;
        1)   echo "supervisor: [$ts] #$issue_num FAILED — missing sentinel (rc=1) — check worker-$issue_num.log" | tee -a "$SUPERVISOR_LOG" ;;
        2)   echo "supervisor: [$ts] #$issue_num NOT PICKABLE — race condition (rc=2)" | tee -a "$SUPERVISOR_LOG" ;;
        130) echo "supervisor: [$ts] #$issue_num interrupted (rc=130)"   | tee -a "$SUPERVISOR_LOG" ;;
        *)   echo "supervisor: [$ts] #$issue_num exited rc=$rc — check worker-$issue_num.log" | tee -a "$SUPERVISOR_LOG" ;;
    esac

    # On success: merge the worker branch into main checkout and push, then delete the branch.
    if [ "$rc" -eq 0 ] && [ -n "${issue_num:-}" ]; then
        local merge_branch="agent/issue-$issue_num"
        echo "supervisor: [$(date +%T)] merging $merge_branch → main..." | tee -a "$SUPERVISOR_LOG"
        local merged=0
        if git -C "$REPO_ROOT" merge --no-ff "$merge_branch" \
               -m "merge: issue #$issue_num (AFK loop)" >>"$SUPERVISOR_LOG" 2>&1; then
            merged=1
        else
            git -C "$REPO_ROOT" merge --abort >>"$SUPERVISOR_LOG" 2>&1 || true
            echo "supervisor: [$(date +%T)] merge conflict — rebasing $merge_branch onto main..." | tee -a "$SUPERVISOR_LOG"
            if git -C "$wt" rebase main >>"$SUPERVISOR_LOG" 2>&1; then
                echo "supervisor: [$(date +%T)] rebase OK — retrying merge for #$issue_num..." | tee -a "$SUPERVISOR_LOG"
                if git -C "$REPO_ROOT" merge --no-ff "$merge_branch" \
                       -m "merge: issue #$issue_num (AFK loop, rebased)" >>"$SUPERVISOR_LOG" 2>&1; then
                    merged=1
                else
                    git -C "$REPO_ROOT" merge --abort >>"$SUPERVISOR_LOG" 2>&1 || true
                    FAILED_ISSUES[$issue_num]=1
                    echo "supervisor: [$(date +%T)] merge FAILED after rebase for #$issue_num — branch kept for manual review" | tee -a "$SUPERVISOR_LOG"
                fi
            else
                # Rebase hit conflicts — let Claude resolve before giving up.
                if [ -n "$wt" ] && [ -d "$wt" ] && resolve_conflicts_with_claude "$wt" "$issue_num"; then
                    echo "supervisor: [$(date +%T)] retrying merge for #$issue_num after Claude resolution..." | tee -a "$SUPERVISOR_LOG"
                    if git -C "$REPO_ROOT" merge --no-ff "$merge_branch" \
                           -m "merge: issue #$issue_num (AFK loop, conflict-resolved)" >>"$SUPERVISOR_LOG" 2>&1; then
                        merged=1
                    else
                        git -C "$REPO_ROOT" merge --abort >>"$SUPERVISOR_LOG" 2>&1 || true
                        FAILED_ISSUES[$issue_num]=1
                        echo "supervisor: [$(date +%T)] merge FAILED after Claude resolution for #$issue_num — branch kept for manual review" | tee -a "$SUPERVISOR_LOG"
                    fi
                else
                    git -C "$wt" rebase --abort >>"$SUPERVISOR_LOG" 2>&1 || true
                    FAILED_ISSUES[$issue_num]=1
                    echo "supervisor: [$(date +%T)] rebase conflict unresolvable for #$issue_num — branch $merge_branch kept for manual review" | tee -a "$SUPERVISOR_LOG"
                fi
            fi
        fi

        if [ "$merged" -eq 1 ]; then
            DONE_ISSUES[$issue_num]=1
            echo "supervisor: [$(date +%T)] merged OK — pushing to origin..." | tee -a "$SUPERVISOR_LOG"
            git -C "$REPO_ROOT" push origin HEAD >>"$SUPERVISOR_LOG" 2>&1 \
                && echo "supervisor: [$(date +%T)] pushed #$issue_num ✓" | tee -a "$SUPERVISOR_LOG" \
                || echo "supervisor: [$(date +%T)] push FAILED for #$issue_num — commits are local" | tee -a "$SUPERVISOR_LOG"
            git -C "$REPO_ROOT" branch -d "$merge_branch" >>"$SUPERVISOR_LOG" 2>&1 || true
            promote_newly_unblocked
        else
            : # failure logged inside conflict handler above
        fi
    fi

    # Prune the worktree.
    if [ -n "$wt" ] && [ -d "$wt" ]; then
        git worktree remove --force "$wt" >>"$SUPERVISOR_LOG" 2>&1 || true
    fi

    unset "PID_TO_ISSUE[$pid]"
    unset "ISSUE_TO_PID[$issue_num]"
    unset "ISSUE_TO_WT[$issue_num]"
}

# ── Main supervisor loop ────────────────────────────────────────────────────
while :; do
    ROUND=$((ROUND + 1))
    if [ "$MAX_ROUNDS" -gt 0 ] && [ "$ROUND" -gt "$MAX_ROUNDS" ]; then
        echo "supervisor: reached max-rounds=$MAX_ROUNDS, exiting" | tee -a "$SUPERVISOR_LOG"
        break
    fi

    # 1. Get the open AFK list.
    tracker_json="$(eval "$ISSUE_LIST_CMD" 2>>"$SUPERVISOR_LOG" || echo '[]')"
    # Support both raw JSON arrays (gh) and other shapes — coerce.
    if ! echo "$tracker_json" | jq -e 'type == "array"' >/dev/null 2>&1; then
        echo "supervisor: tracker output is not a JSON array; got: $(echo "$tracker_json" | head -c 200)" | tee -a "$SUPERVISOR_LOG"
        tracker_json='[]'
    fi

    # 2. Compute unblocked, subtract in-flight.
    unblocked="$(compute_unblocked "$tracker_json" || true)"
    pickable=()
    while IFS= read -r n; do
        [ -z "$n" ] && continue
        [ -n "${ISSUE_TO_PID[$n]:-}" ] && continue   # in-flight
        [ -n "${DONE_ISSUES[$n]:-}" ] && continue     # completed this session
        [ -n "${FAILED_ISSUES[$n]:-}" ] && continue   # unresolvable conflict this session
        pickable+=("$n")
    done <<< "$unblocked"

    # Status snapshot.
    active_issues=()
    for n in "${!ISSUE_TO_PID[@]}"; do active_issues+=("#$n"); done
    echo "supervisor: [$(date +%T)] round=$ROUND | active=${#PID_TO_ISSUE[@]} ($(IFS=, ; echo "${active_issues[*]:-none}")) | pickable=${#pickable[@]} ($(IFS=, ; echo "${pickable[*]/#/#}"))" | tee -a "$SUPERVISOR_LOG"

    # 3. Drain check: empty pickable AND no active workers → done.
    if [ "${#pickable[@]}" -eq 0 ] && [ "${#PID_TO_ISSUE[@]}" -eq 0 ]; then
        echo "supervisor: [$(date +%T)] DRAINED — all issues complete" | tee -a "$SUPERVISOR_LOG"
        trap - EXIT
        cleanup EXIT
        exit 0
    fi

    # 4. Dispatch up to N workers.
    while [ "${#PID_TO_ISSUE[@]}" -lt "$N" ] && [ "${#pickable[@]}" -gt 0 ]; do
        next="${pickable[0]}"
        pickable=("${pickable[@]:1}")
        dispatch_worker "$next" || continue
    done

    # 5. Block until ANY worker finishes, then loop back to recompute.
    if [ "${#PID_TO_ISSUE[@]}" -gt 0 ]; then
        echo "supervisor: [$(date +%T)] waiting for a worker to finish..." | tee -a "$SUPERVISOR_LOG"
        reap_one
    fi
done

trap - EXIT
cleanup EXIT
