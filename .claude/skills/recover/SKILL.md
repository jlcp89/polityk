---
name: recover
description: Recover project context at the start of a work session from git, the issue tracker, and CONTEXT.md. Use when starting a session, picking up after a break, or before working on anything that needs orientation.
disable-model-invocation: true
---

# /recover

Run in a single message:

- `git branch --show-current && git status --short && git log --oneline -10` (skip if not a git repo)
- List ready issues from the project's tracker (`gh issue list --state open --limit 5` if a GitHub remote exists; otherwise read `ISSUES.md` if it exists)
- Read `CONTEXT.md` (full, if present) — project context: domain, architecture, conventions
- Read `HANDOFF.md` (if present) — active task state from last session
- Read `REQUIREMENTS.md` (first 40 lines; follow up with grep `in-progress|blocked -B 2 -A 3` if active items found) — work statuses
- Read `KNOWLEDGE.md` (first 30 lines) — debugging insights, env quirks
- Read `SESSIONS.md` (full — capped at 100 entries, bounded read) — per-ticket session log: what landed, tied to ticket numbers

Skip any missing source.

## Scope Fence

If HANDOFF.md is present and contains a **Task** line, emit this line
**before the dashboard**:

> **Session scope**: {Task line from HANDOFF.md} — all other tickets,
> carry-forward items, and unrelated work are OUT OF SCOPE for this session.
> Do not reference or act on them unless the user explicitly redirects.

If HANDOFF.md is absent or empty, skip.

## Dashboard (≤ 16 lines: 15 + optional Last session line)

Orient, don't summarize. Point at files instead of quoting them.

```
## Session Context
**Branch**: `{branch}` | **Modified**: {N} files | **Last commit**: {short sha — subject}

### In Progress  ← omit this block entirely if HANDOFF.md is absent or empty
{Task line from HANDOFF.md}
Next: {Next line from HANDOFF.md}

### Open work
- {issue/source}: {title}

### Project context
{1 line from CONTEXT.md} | Work: {N in-progress/blocked from REQUIREMENTS.md, or "none"} | Knowledge: {N entries from KNOWLEDGE.md, or "empty"} | Sessions: {N entries from SESSIONS.md, or "empty"}

### Last session  ← omit this block entirely if SESSIONS.md is empty or absent
{newest SESSIONS.md entry, truncated to 120 chars}

What are we working on today?
```

If no git, no tracker, and no session files exist: print only the working directory and ask what to work on.

Then wait.
