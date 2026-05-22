---
name: wrap
description: Capture session context before ending work — architecture decisions to CONTEXT.md, debugging insights to KNOWLEDGE.md, work statuses to REQUIREMENTS.md, active task state to HANDOFF.md. Use when ending a session, before stepping away, or when a meaningful decision should be persisted.
disable-model-invocation: true
---

# /wrap

Captures the reasoning git cannot reconstruct.

## Step 0 — Read what actually changed (MANDATORY)

Memory of "what we did" is not authoritative — `git log` is. Before writing to any session file, run:

```bash
git log --oneline -20
git diff --stat $(git merge-base HEAD @{u} 2>/dev/null || git rev-list --max-parents=0 HEAD | tail -1)..HEAD
git status --short
```

State, in one sentence, what actually changed this session.

## Step 1 — KNOWLEDGE.md

Review the session: did anything take unexpected time to figure out? An env quirk, a gotcha, an unexpected dependency behavior, a workaround? If yes — append using the existing `Context / Problem / Solution / Prevention` format. If genuinely nothing surprised you, skip.

## Step 1.5 — SESSIONS.md (one line per wrap, always)

Append exactly one line per `/wrap` to `SESSIONS.md`, even when the session landed nothing (`problem: none | fix: none | ref: none`). SESSIONS.md is ticket-keyed; KNOWLEDGE.md is ticket-agnostic — keep concerns separate.

Build the line:

- DATE = today (`date +%Y-%m-%d`; if `CLAUDE.local.md` provides a current-date override, prefer that).
- TICKET = first match, in order:
  1. `grep -E '^\*?\*?Task' HANDOFF.md` — extract any `ticket-N`, `#N`, `TKT-N`, or `issue-N` token.
  2. Current branch from `git branch --show-current` — parse `agent/issue-N`, `feature/TKT-N-…`, `ticket-N-…`.
  3. Otherwise `ticket-none`.
- BRANCH = `git branch --show-current` (use `detached` if empty).
- SHA = `git log -1 --format=%h`.
- `problem:` = one sentence (≤ 120 chars) — what was wrong / what we needed to do.
- `fix:` = one sentence (≤ 120 chars) — what actually shipped, or `none`.
- `ref:` = optional pointer (ADR id, PR, file path; ≤ 120 chars), or `none`.

Whole line MUST be ≤ 500 chars. If too long, trim `problem:` and `fix:` first; keep `ref:` intact.

**Prepend, don't append.** New entry sits directly under the `<!-- newest first … -->` marker line.

**Rotation (120 → 100):**

1. Read `SESSIONS.md` with `Read`.
2. Count entry lines (after `## Entries`, matching `^[0-9]{4}-[0-9]{2}-[0-9]{2} \| `).
3. If count ≥ 120 after prepending, rewrite the file as: original header + legend + `## Entries` + marker line + newest 100 entry lines (drop the oldest count − 100 from the bottom).
4. Write the result back with `Write`.

If `SESSIONS.md` does not exist, copy `templates/session/SESSIONS.md` (or recreate it inline using the template body) before prepending.

## Step 2 — CONTEXT.md

If a significant architectural decision landed, append an ADR (`### ADR-{N}: {title}` with **Status / Context / Decision / Consequences**). Token-impact claims must be measured with `bash measure-context.sh` before/after. If active ADRs exceed 5, archive the oldest to `CONTEXT_ARCHIVE.md` with a one-line pointer.

Skip if no project-level context changed.

## Step 3 — REQUIREMENTS.md / issues

Record what changed this session. Mark completed items `done` with today's date. If no REQUIREMENTS.md exists and meaningful work was done, create one and add a brief `done` entry. Don't skip because items weren't pre-tracked. If using a remote tracker, comment on or close the issue instead.

## Step 4 — HANDOFF.md

> **HANDOFF.md holds exactly ONE active task.** If multiple items are still
> in progress, identify the primary task (the one to pick up next session).
> Everything else belongs in REQUIREMENTS.md as `in-progress`, not in
> HANDOFF.md. Carry-forward notes, reminders, and unrelated context must
> NOT go into HANDOFF.md — they belong in REQUIREMENTS.md or KNOWLEDGE.md.

Ask the user: *"Is the current task complete, or still in progress?"*

- **Still in progress**: write or update `HANDOFF.md` with four sections — **Task** (one sentence: what I'm fixing/building/investigating), **Context** (relevant file paths, error messages, branch name), **Tried** (bullet list of approaches + outcomes so far), **Next** (single most concrete next action). Keep each entry to one sentence.
- **Task complete**: delete `HANDOFF.md` if it exists.
- **Nothing in progress**: skip.

## Step 5 — Summary

Report what changed. Tell the user to run `/recover` next time.
