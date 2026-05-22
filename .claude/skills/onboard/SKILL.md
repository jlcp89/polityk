---
name: onboard
description: Guided codebase onboarding for new contributors or returning after absence. Reads all project context, generates a quickstart guide, traces primary data flow, and shows common tasks. Use when starting on an unfamiliar project or returning after a break.
---

# Onboard — Codebase Tour

Guided tour for new contributors or returning after absence. Reads available context and builds a mental model.

## Step 1 — Read All Context

Read these files (skip any that don't exist):

1. `CLAUDE.md` — project overview, conventions, commands
2. `CONTEXT.md` — mission, ADRs, goals, constraints
3. `KNOWLEDGE.md` — debugging insights, environment quirks
4. `REQUIREMENTS.md` — work items and priorities (if present)
5. Issue tracker — `gh issue list` (if a GitHub remote exists) or `ISSUES.md`
6. `README.md` — project documentation
7. Auto-memory files (`~/.claude/projects/<project>/memory/`)

## Step 2 — Ask Focus Area

> "What part of the project are you working on? (or 'general' for full overview)"

- **Specific area** — focus the tour on that module/feature
- **General** — cover full project architecture

## Step 3 — Generate Quickstart

Use the Quickstart template in [tour-format.md](tour-format.md). Pull mission, ADRs, active work, gotchas, conventions, and essential commands from the files read in Step 1.

## Step 4 — Trace Primary Data Flow

Walk entry → routing → business logic → persistence → response. Use the data-flow procedure in [tour-format.md](tour-format.md). If a focus area was given, scope the trace to it.

## Step 5 — Show Common Tasks

Use the Common-Tasks template in [tour-format.md](tour-format.md), tailored to the project's actual patterns.

## Step 6 — Save Mental Model

Offer to save the architecture summary to auto memory:

> "Save this architecture summary to auto memory for future sessions?"

On approval, follow the save procedure in [tour-format.md](tour-format.md).
