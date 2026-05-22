---
paths:
  - "**"
---

# Subagent Delegation

## When to Spawn

Spawn an Agent when: research needs >3 reads, parallel investigations,
isolated debugging, or broad refactors. Skip for single-file edits and
search-and-replace across known files.

## Background Task Output — DO NOT use TaskOutput(block=false)

It dumps the agent's raw streaming transcript (every tool call, JSON message,
partial result) into main context — 10–40k tokens per check. Wait for the
completion notification. For progress peeks, use `Bash` with
`tail -5 <output_file>`. Use `TaskOutput(block=true)` only after the
notification.
