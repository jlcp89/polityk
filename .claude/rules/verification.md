---
paths:
  - "src/**"
  - "lib/**"
  - "app/**"
  - "pkg/**"
  - "internal/**"
  - "cmd/**"
  - "pipeline/**"
  - "android/**"
  - "**/*.go"
  - "**/*.py"
  - "**/*.kt"
  - "**/*.kts"
---

# Proof Cycle & Verification Gate

After EVERY code change, run the proof cycle for the area you touched. Fix issues at each step before proceeding.

## Commands by area

| Area | Type check | Lint | Test | Build |
|------|-----------|------|------|-------|
| Go (`cmd/`, `internal/`) | `go vet ./...` | `golangci-lint run` | `go test -race ./...` | `go build ./...` |
| Python (`pipeline/`) | `uv run mypy pipeline/` | `uv run ruff check pipeline/` | `uv run pytest pipeline/tests/` | n/a |
| Android (`android/`) | `./gradlew :app:compileDebugKotlin` | `./gradlew detekt ktlintCheck` | `./gradlew test` | `./gradlew assembleDebug` |

If a change spans multiple areas, run the cycle for each.

## Rules

- Run ALL steps for the area, not just the one related to your change.
- A passing build with failing tests is NOT acceptable.
- A passing test with lint errors is NOT acceptable.
- If any step fails, fix it before moving to the next step.
- If a test fails, do NOT modify the test to make it pass unless the test is genuinely wrong.
- After fixing, re-run from step 1.

## When to Skip

- Documentation-only changes: skip type check and build.
- Config file changes: run full loop.
- Test file changes: run lint + test.
- NEVER skip the full loop before committing.

## Completion Gate

Completion claims require evidence. Claiming work is complete without verification is unacceptable.

Before declaring any task complete:

1. **Identify** the verification command (from the table above or the issue's acceptance criteria).
2. **Run** it fresh — not from cache, history, or memory.
3. **Read** the COMPLETE output including exit code.
4. **Confirm** the output actually proves the claim (passing tests, clean build, no errors).
5. **State** the claim WITH the evidence — paste the relevant output.

## Red-Flag Words

If you catch yourself using any of these, STOP and run verification instead:

- "should work", "probably works", "seems to", "looks correct", "appears to"
- "I think it", "I believe", "likely", "most likely", "presumably"
- "everything seems", "that should do it", "looks good"

These words mean you haven't verified. Replace the hedge with a command.

## Examples

**Bad**: "The D'Hondt allocator should handle ties correctly now."
**Good**: "All 14 allocator tests pass: `go test ./internal/dhondt/... -v` → ok internal/dhondt 0.034s (exit 0). Includes 3 tie-break cases."

**Bad**: "This probably fixes the pytrends rate-limit error."
**Good**: "Reproduced original failure, applied 60s backoff, re-ran scraper end-to-end against the live endpoint: 24/24 keywords fetched, no 429s. Log saved to data/logs/trends-2026-05-21.log."
