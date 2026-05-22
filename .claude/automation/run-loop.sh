#!/usr/bin/env bash
# run-loop.sh — unattended AFK iteration driver.
#
# Modes:
#   ./run-loop.sh                # sequential, unbounded — picks next unblocked issue, loops until drained
#   ./run-loop.sh 1              # sequential, one iteration (same as run-once.sh)
#   ./run-loop.sh 7              # parallel — spawns 7 concurrent Claude instances via run-parallel.sh
#   ./run-loop.sh --issue 7      # single iteration assigned to issue #7 (used internally by run-parallel.sh)
#
# Each sequential iteration runs `claude` in print mode with --dangerously-skip-permissions and
# stream-json output. The final `result` block is parsed deterministically with jq:
#   <promise>NO MORE TASKS</promise>  → exit 0   (drained)
#   <promise>COMPLETE</promise>       → continue (or exit 0 if cap reached)
#   <promise>NOT PICKABLE</promise>   → exit 2   (--issue mode only — issue no longer pickable)
#   neither sentinel                  → exit 1   (something failed; see log)
#
# Logs land in /tmp/<project>-afk-<unix-ts>/ — path printed at startup. Each iteration's
# raw stream-json is preserved so post-mortem doesn't depend on the live tee output.

set -euo pipefail
IFS=$'\n\t'

# ── Pre-flight ──────────────────────────────────────────────────────────────
command -v jq >/dev/null 2>&1 || {
    echo "error: jq is required (install: apt-get install jq / brew install jq)" >&2
    exit 127
}
command -v claude >/dev/null 2>&1 || {
    echo "error: claude CLI not on PATH" >&2
    exit 127
}

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PROMPT_FILE="$REPO_ROOT/.claude/automation/loop-prompt.md"
ENV_FILE="$REPO_ROOT/.claude/automation/loop-prompt.env"

[ -f "$PROMPT_FILE" ] || { echo "error: $PROMPT_FILE not found" >&2; exit 1; }
[ -f "$ENV_FILE" ]    || { echo "error: $ENV_FILE not found (re-run /setup or write it manually)" >&2; exit 1; }

# shellcheck disable=SC1090
source "$ENV_FILE"   # provides ISSUE_LIST_CMD, ISSUE_CLOSE_CMD

# ── Argument parsing ────────────────────────────────────────────────────────
MAX_ITERS=0          # 0 = unbounded
ASSIGNED_ISSUE=""    # empty = agent picks
case "${1:-}" in
    --issue)
        ASSIGNED_ISSUE="${2:?--issue requires an issue number}"
        MAX_ITERS=1
        ;;
    "")
        ;;
    *)
        if [[ "$1" =~ ^[0-9]+$ ]]; then
            if [ "$1" -gt 1 ]; then
                # N > 1 → parallel mode: spawn N concurrent workers via run-parallel.sh
                SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
                exec bash "$SCRIPT_DIR/run-parallel.sh" "$1"
            fi
            MAX_ITERS="$1"
        else
            echo "usage: $0 [<N-workers> | --issue <N>]" >&2
            exit 2
        fi
        ;;
esac

# Branch guard — solo mode only (parallel workers run in their own worktree branches).
if [ -z "$ASSIGNED_ISSUE" ]; then
    CURRENT_BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
    if [ "$CURRENT_BRANCH" != "main" ]; then
        echo "error: must be on 'main' branch (currently on '$CURRENT_BRANCH')" >&2
        echo "       run: git checkout main" >&2
        exit 1
    fi
fi

# ── Log directory ───────────────────────────────────────────────────────────
PROJECT="$(basename "$REPO_ROOT")"
LOGDIR="/tmp/${PROJECT}-afk-$(date +%s)"
mkdir -p "$LOGDIR"
SUMMARY="$LOGDIR/summary.log"
echo "AFK loop log dir: $LOGDIR" | tee "$SUMMARY"
[ -n "$ASSIGNED_ISSUE" ] && echo "Mode: single-issue (#$ASSIGNED_ISSUE)" | tee -a "$SUMMARY"

# ── Signal handling ─────────────────────────────────────────────────────────
ITER=0
trap '
    echo "" >&2
    echo "stopped at iteration $ITER — last commit (if any) is on disk; logs at $LOGDIR" >&2
    exit 130
' INT TERM

# ── jq filters ──────────────────────────────────────────────────────────────
STREAM_TEXT='select(.type == "assistant").message.content[]? | select(.type == "text").text // empty'
FINAL_RESULT='select(.type == "result").result // empty'

# ── Iteration loop ──────────────────────────────────────────────────────────
while :; do
    ITER=$((ITER + 1))
    if [ "$MAX_ITERS" -gt 0 ] && [ "$ITER" -gt "$MAX_ITERS" ]; then
        echo "reached max iterations ($MAX_ITERS), exiting" | tee -a "$SUMMARY"
        exit 0
    fi

    ITER_LOG="$LOGDIR/iter-$(printf '%03d' "$ITER").jsonl"
    printf '\n=== iteration %d starting at %s ===\n' "$ITER" "$(date -Iseconds)" | tee -a "$SUMMARY"

    # Front-load context: recent commits + open issue list (the ralph trick).
    commits="$(git log -n 5 --format='%H%n%ad%n%B---' --date=short 2>/dev/null || echo 'No commits yet')"
    tracker_output="$(eval "$ISSUE_LIST_CMD" 2>&1 || echo 'tracker query failed')"
    loop_prompt="$(cat "$PROMPT_FILE")"

    if [ -n "$ASSIGNED_ISSUE" ]; then
        directive="You are assigned issue #${ASSIGNED_ISSUE}. Do NOT pick a different issue. If issue #${ASSIGNED_ISSUE} is no longer open / ready-for-agent (someone else closed or claimed it), output <promise>NOT PICKABLE</promise> and stop without making changes."
    else
        directive=""
    fi

    prompt="$(printf '%s\n\n# Recent commits\n%s\n\n# Open issues\n%s\n\n%s\n' \
        "$directive" "$commits" "$tracker_output" "$loop_prompt")"

    # Run claude with stream-json so we can parse the final result deterministically.
    # Live streaming text goes to stdout via jq; raw stream is preserved in iter log.
    set +e
    claude --dangerously-skip-permissions \
           --print \
           --verbose \
           --output-format stream-json \
           --include-partial-messages \
           "$prompt" \
        | tee "$ITER_LOG" \
        | jq --unbuffered -rj "$STREAM_TEXT" 2>/dev/null
    claude_rc="${PIPESTATUS[0]}"
    set -e

    # Extract final result (deterministic — not grepping prose).
    result="$(jq -r "$FINAL_RESULT" "$ITER_LOG" 2>/dev/null || echo '')"

    if [ -z "$result" ] && [ "$claude_rc" -ne 0 ]; then
        echo "iter $ITER: claude exited $claude_rc with no final result; see $ITER_LOG" | tee -a "$SUMMARY"
        exit 1
    fi

    if [[ "$result" == *"<promise>NO MORE TASKS</promise>"* ]]; then
        echo "iter $ITER: drained" | tee -a "$SUMMARY"
        exit 0
    elif [[ "$result" == *"<promise>NOT PICKABLE</promise>"* ]]; then
        echo "iter $ITER: not pickable (issue #${ASSIGNED_ISSUE} no longer available)" | tee -a "$SUMMARY"
        exit 2
    elif [[ "$result" == *"<promise>COMPLETE</promise>"* ]]; then
        echo "iter $ITER: complete" | tee -a "$SUMMARY"
        # In --issue mode MAX_ITERS=1 ⇒ next loop tick exits; otherwise continue.
        continue
    else
        echo "iter $ITER: missing sentinel; see $ITER_LOG" | tee -a "$SUMMARY"
        exit 1
    fi
done
