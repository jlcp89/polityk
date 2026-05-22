---
name: diagnose
description: Disciplined diagnosis loop for hard bugs and performance regressions — reproduce, hypothesise, instrument, fix, regression-test. Use when a bug is reported, something is broken/throwing/failing, or a performance regression is described.
---

# Diagnose

A discipline for hard bugs. Skip phases only when explicitly justified. Project gates: see [gates.md](gates.md).

## Phase 1 — Build a feedback loop

**This is the skill.** Everything else is mechanical. With a fast, deterministic, agent-runnable pass/fail signal you will find the cause. Without one, no amount of staring at code will save you.

Spend disproportionate effort here. Be aggressive. Be creative. Refuse to give up.

Ways to construct one, in rough order: failing test at the seam that reaches the bug → curl/HTTP script against a dev server → CLI invocation diffing stdout against a snapshot → headless browser script → replay of a captured trace → throwaway harness with mocked deps → fuzz/property loop → bisection harness for `git bisect run` → differential loop (old vs new) → HITL bash script as last resort.

Treat the loop as a product. Make it faster (cache setup, narrow scope), sharper (assert on the specific symptom), more deterministic (pin time, seed RNG, freeze network). A 30-second flaky loop is barely better than no loop; a 2-second deterministic loop is a debugging superpower.

For non-deterministic bugs the goal is not a clean repro but a *higher reproduction rate*. Loop the trigger 100×, parallelise, narrow timing windows, inject sleeps. 50% flake is debuggable; 1% is not.

If you genuinely cannot build a loop, stop and say so. List what you tried. Ask the user for environment access, captured artifacts, or permission to instrument production. Do not hypothesise without a loop.

## Phase 2 — Reproduce

Run the loop. Confirm the failure mode is the one the user described (not a different failure that happens nearby), reproducible across runs, and the symptom is captured exactly.

## Phase 3 — Hypothesise

Generate 3–5 ranked, falsifiable hypotheses before testing any. Each hypothesis must state its prediction: "if X is the cause, then changing Y will make the bug disappear." Show the ranked list to the user before testing — they often re-rank instantly with domain knowledge. Don't block on it if they're AFK.

## Phase 4 — Instrument

Each probe maps to a specific Phase 3 prediction. Change one variable at a time. Prefer debugger/REPL over logs. Tag every debug log with a unique prefix (e.g. `[DEBUG-a4f2]`) so cleanup is one grep. For perf regressions, measure first, fix second.

## Phase 5 — Fix + regression test

Write the regression test before the fix, but only at a *correct seam* — one that exercises the real bug pattern as it occurs at the call site. If no correct seam exists, that itself is the finding; note it. Otherwise: failing test → fix → passing test → re-run the Phase 1 loop against the original scenario.

## Phase 6 — Cleanup + post-mortem

Required before declaring done: original repro no longer reproduces, regression test passes (or absence is documented), all `[DEBUG-...]` instrumentation removed, prototypes deleted, the correct hypothesis is stated in the commit/PR message.

Then ask: what would have prevented this bug? If architectural, hand off to `/refactor` or `/techdebt` with specifics — *after* the fix is in.
