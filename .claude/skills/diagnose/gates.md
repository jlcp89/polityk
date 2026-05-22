# c2 Diligence Gates for `/diagnose`

These are c2-specific verification gates layered on top of the upstream `diagnose` skill. They preserve the proof-cycle discipline that c2 enforced in the previous `debugging` skill.

## Phase 2 — Reproduce: GATE-2

Cannot proceed past Phase 2 unless ONE of:

- A failing test exists that demonstrates the bug, OR
- A captured reproduction artifact (HAR, log dump, screen recording) confirms the failure

If neither exists, STOP and report. Do NOT hypothesise.

## Phase 4 — Instrument: GATE-3

Cannot proceed past Phase 4 unless the root cause is identified **with evidence** — log output, debugger trace, profiler result, or test diff. "I think it might be X" is not a root cause.

## Phase 5 — Fix: GATE-5

Cannot claim the bug is fixed unless ALL of:

1. The Phase 1 reproduction loop no longer reproduces.
2. The regression test (or documented absence of seam) is committed.
3. Project proof cycle passes — see `.claude/rules/verification.md`.

## After 2 failed fix attempts

Escalate before continuing:

1. Spawn `/fork debug` — fresh context.
2. If that fails, run `/solve` — fan-out hypotheses.
3. Only after both: STOP and report with evidence from all attempts.

## See also

- `.claude/rules/verification.md` — project-wide proof cycle
- `.claude/rules/diligence-before-conclusion.md` — pre-action git diligence
