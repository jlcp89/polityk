---
paths:
  - "**"
---

# Feature Scope — One Active Task Per Session

## Rule

HANDOFF.md declares the session's single active task. All other tickets,
carry-forward items, and unrelated context are **out of scope** unless the
user explicitly redirects.

## Switching scope mid-session

If the user asks about a different task or ticket, confirm before switching:
> "That's outside current scope ({current task from HANDOFF.md}). Should we
> switch? That requires `/wrap` first, then state the new scope."

Do not begin work on the new task until `/wrap` completes and the user confirms.

## Carry-forward items

Items from a previous session in REQUIREMENTS.md do not constitute a request
to work on them. Wait for the user to direct what to pick up.

## Why this rule exists

Opus 4.7 treats multi-item HANDOFF.md content as a literal work queue. The
scope fence emitted by `/recover` declares one active task; this rule
reinforces it throughout the session.
