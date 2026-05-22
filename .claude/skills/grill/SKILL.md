---
name: grill
description: Interview the user relentlessly about a plan or design until the decision tree is resolved, sharpening domain language and capturing decisions inline as ADRs. Use when stress-testing a plan, validating a design, or when user says "grill me".
---

# /grill

Walk down each branch of the design tree, resolving dependencies one decision at a time.

## How to grill

- Ask one question at a time. Wait for the answer before moving on.
- For each question, propose your recommended answer with the question.
- If a question can be answered by reading the codebase, read it instead of asking.
- Stress-test domain relationships with concrete scenarios that probe edge cases.
- Cross-check claims against the code. Surface contradictions: *"Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"*

## Domain language

If `CONTEXT.md` (or `CONTEXT-MAP.md` for multi-context repos) exists, challenge the user against its glossary the moment they use a conflicting or vague term: *"Your glossary defines 'cancellation' as X, but you seem to mean Y."*

When a term is resolved, update `CONTEXT.md` *inline* — don't batch. Format: [CONTEXT-FORMAT.md](CONTEXT-FORMAT.md). If `CONTEXT.md` does not exist yet, create it lazily when the first term lands.

Only include terms meaningful to domain experts. Skip general programming concepts.

## ADRs

Offer to write an ADR only when **all three** are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful.
2. **Surprising without context** — a future reader will wonder "why did they do this?"
3. **Result of a real trade-off** — there were genuine alternatives.

If any leg is missing, skip the ADR. Format: [ADR-FORMAT.md](ADR-FORMAT.md). ADRs live in `docs/adr/` with sequential numbering; create the directory lazily.

## When to stop

When the user says "enough", or when remaining branches are all small implementation details with no architectural weight. Summarize what was decided, where it was captured, and what is still open.
