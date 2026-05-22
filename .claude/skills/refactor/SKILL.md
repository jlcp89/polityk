---
name: refactor
description: Restructure code without changing external behavior — impact analysis, baseline tests, incremental atomic commits. Use when restructuring code, extracting/moving/renaming, or reducing complexity without changing public APIs.
---

# /refactor

Each step is independently testable and `git revert`-able.

## Step 1 — Define goal

If `$ARGUMENTS` describes the goal, use it. Otherwise ask: "What do you want to refactor, and why?" Clarify **target**, **goal**, **constraint** (what must NOT change — public API, behavior, performance).

## Step 2 — Impact analysis (MANDATORY before any code change)

Run before proposing any plan:

```bash
git log --oneline -10 -- <target files>
git diff --stat HEAD -- <target files>
git status --short
```

Then state the call-graph in one sentence. Full procedure in [impact-analysis.md](impact-analysis.md).

## Step 3 — Baseline

Run the full proof cycle BEFORE any change: tests, type check, lint. Record exact counts: `"{N} tests passed, 0 failed"`. If tests are already failing, STOP and ask whether to fix first.

## Step 4 — Plan incremental steps

Break into the smallest steps that each leave tests passing. Order to minimise intermediate breakage. Present:

```
Refactoring plan:
  1. {step} — affects {files}
  2. {step} — affects {files}
```

Ask: "Approve this plan, or adjust?"

## Step 5 — Execute

For each step: implement → tests → type check → commit `refactor: {what}`. If a step breaks tests and the fix isn't obvious, `git revert HEAD` and reassess.

## Step 6 — Final verification

Full proof cycle. Compare to Step 3 baseline (same count, same passing tests).
