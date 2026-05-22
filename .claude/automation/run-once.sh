#!/usr/bin/env bash
# run-once.sh — single supervised iteration.
#
# Runs exactly one iteration of the AFK loop with streaming output,
# then exits. Equivalent to: run-loop.sh 1
#
# Use this to test the loop on a single issue before going fully unattended.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RUN_LOOP="$REPO_ROOT/.claude/automation/run-loop.sh"

[ -x "$RUN_LOOP" ] || chmod +x "$RUN_LOOP"

exec bash "$RUN_LOOP" 1 "$@"
