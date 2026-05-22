---
name: new-feature
description: Implement a non-trivial feature spec-first — research the codebase, generate SPEC.md for approval, then implement after explicit sign-off. Use when starting any non-trivial feature, before writing implementation code, or when scope needs explicit alignment.
---

# /new-feature

The spec is the engineering. The AI just types fast.

## Phase 1 — Spec generation

### Step 1 — Capture the request

If `$ARGUMENTS` is provided, use it. Otherwise ask: "What feature are we building? Describe it in a sentence or two." Complex scope (10+ files, new patterns, unclear shape) → break it into multiple `/new-feature` runs, one slice per spec.

### Step 2 — Research the codebase (MANDATORY before Step 3)

Memory of "the codebase already does X" is not authoritative — the code is. Run an Explore agent to understand where similar features live, what patterns to follow, what APIs/interfaces exist, what tests look like. Also run:

```bash
git log --oneline -15 -- <relevant directories>
git diff --stat HEAD
git status --short
```

Read at least one existing similar implementation end-to-end. Then state in one sentence what the codebase already does, e.g.:

> "Auth lives in `src/auth/`; uses session cookies + Redis; pattern is `Service → Repository → Model`; ~12 endpoints; last touched 2 weeks ago"

### Step 3 — Context assembly

Use the layered approach from [context-assembly-guide.md](context-assembly-guide.md). Classify complexity (trivial 1–3 files / standard 4–10 / complex 10+) and ask only what cannot be inferred. Always ask: "What edge cases, error scenarios, or constraints should we handle? What 'obvious' approach doesn't work here?" For standard+ also ask the acceptance criteria; for complex also ask what's most uncertain.

### Step 4 — Generate SPEC.md

Write `SPEC.md` at the project root with: **Problem** (1–2 sentences) / **Solution** (1–2 sentences) / **Changes** (per file: what + why) / **API Changes** / **Test Plan** (checklist) / **Verification** (commands and expected output).

### Step 5 — Present SPEC.md for approval

Show the spec and ask: "Does this spec match what you want? Any changes before I start implementing?" Wait for approval. **HARD RULE**: no code, no edits, no "rough sketch" until the user explicitly approves the spec.

## Phase 2 — Implementation

Only after approval:

1. Branch: `git checkout -b feature/{name}`.
2. Implement file by file per the Changes section.
3. After each file: type check → lint → test → build. Fix before moving on.
4. Write tests per the Test Plan.
5. Run the Verification section commands.
6. One commit per logical change, referencing the spec.

## Phase 3 — Cleanup

Delete `SPEC.md` (or move to `docs/specs/` if the team keeps them). Close the originating issue with a summary, or if no tracker exists append a `Status: done` entry to `REQUIREMENTS.md`.
