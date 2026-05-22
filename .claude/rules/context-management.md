---
paths:
  - ".claude/skills/wrap/**"
---

# Context Management — when to `/compact`

## Good times to compact
- After a research phase — insights gathered, ready to implement
- After a milestone — tests passing, ready for next task
- Between unrelated tasks — A's context won't help B
- When context feels heavy — repeating yourself, forgetting decisions

## Bad times to compact
- Mid-implementation — loses the mental model
- Mid-debugging — loses the hypothesis chain
- Before committing — needs context to write a good message
- Before `/wrap` — always persist context first

## Before compacting
1. Run `/wrap` — captures decisions to CONTEXT.md, updates KNOWLEDGE.md and REQUIREMENTS.md, commits.
2. Stash anything unrelated.
3. If structural changes landed, run `/graphify . --update`.

## Low-context signals (suggest `/compact`)
Forgetting earlier instructions, repeating answered questions, contradicting prior decisions, asking "what file was that in?"
