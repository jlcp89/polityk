---
name: to-issues
description: Decompose a plan, spec, or PRD into atomic per-story issues — each one the smallest end-to-end task an AFK agent can complete without leaving the system broken. Auto-detects whether to write to GitHub Issues or a local ISSUES.md file. Use when converting a plan into actionable work, creating implementation tickets, or breaking work into AFK-loop-ready issues.
---

# /to-issues

Break a plan into independently-grabbable atomic issues — one per user story (or a sub-part of one). Each issue ships end-to-end in one AFK iteration and exercises every layer the capability crosses. Codebase state is consulted before drafting so already-built work is never re-issued.

## Step 1 — Pick the tracker

Default to **local** unless the repo has already chosen one:

1. If `ISSUES.md` exists at the repo root → **local**, no question asked.
2. If `.claude/automation/loop-prompt.md` exists, parse its `Tracker:` header → use that.
3. Otherwise ask the user (do NOT auto-pick `github` even if `gh` works — many users prefer a local file regardless):
   > "Tracker for this issue? `local` writes to `ISSUES.md` at the repo root (default). `github` writes to GitHub Issues via `gh`."
   - On `local` (or empty answer): create `ISSUES.md` with a `# Issues` header if missing. Continue as **local**.
   - On `github`: continue as **github**.

## Step 2 — Gather context + scan codebase

1. **Fetch the source.** If `$ARGUMENTS` is a path under `docs/prd/`, an issue reference, or another file path, read its full body. Work from conversation context otherwise.

2. **Extract all user stories** as a numbered list (US1 … USN). Every story must be named explicitly before any issue is drafted. If the source uses epics/tasks/requirements instead of user stories, treat each discrete behavior as a story.

3. **Scan the codebase** for existing implementations relevant to each story:
   - Look for existing models, migrations, handlers, routes, and tests that correspond to each story.
   - Mark each story: **done** (already shipped — skip entirely), **partial** (started but incomplete — draft an extension issue), or **not started**.

4. Load the domain glossary from `CONTEXT.md` and identify relevant ADRs. Issue titles must use project vocabulary.

## Step 3 — Per-story atomic breakdown

This is the core of the skill. Read `verticality.md` (sibling aux file) before drafting — it has the anti-patterns, vertical replacements, and self-check rules in full.

**Unit of work**: one atomic issue = the smallest completable end-to-end task an AFK agent can execute without leaving the system in a broken state.

**Algorithm — for each user story (US1 … USN in order):**

1. State what the story requires (behavior, layers, dependencies).
2. Note what already exists in the codebase (from Step 2 scan). Skip **done** stories entirely.
3. Decide: is this 1 atomic issue or does it need to be split?
   - **Split when**: distinct sub-capabilities exist, different layers can be independently deployed, or the work would occupy more than one focused agent session.
   - **Keep together when**: the pieces are meaningless without each other (e.g., a model + its only consumer belong in one issue).
4. For each resulting issue:
   - **Title**: one atomic capability, single noun-phrase naming exactly one deliverable. No `+`, `and`, `with`, or `,`.
   - **Verticality check**: name the layers it touches; if only one layer → it is horizontal → merge into a consumer issue or add the missing layer.
   - **Classification**: mark **AFK** (CI-runnable) or **HITL** (needs a human — design review, real environment, Windows install).
   - **Blockers**: before finalizing any issue number, identify shared infrastructure across the full set:
     1. List every file that multiple issues will CREATE (migrations, schema files, generated code, shared interfaces).
     2. For each shared resource, identify which issue creates it (provider) and which issues consume it (dependents).
     3. Every consuming issue must list the providing issue in its `## Blocked by` section.
     4. **Migration serialization rule**: sequential migration files (`0009_`, `0010_`, …) cannot be created concurrently — only one number can exist. Each migration issue must block all subsequent migration issues in the set regardless of story independence.
     5. `## Blocked by` is NEVER left blank. Either list `- #N (reason)` or write `- None — can start immediately`. A blank field is indistinguishable from "not analyzed" and causes the AFK supervisor to treat the issue as unblocked.

**Hard caps per issue**: ≤1 user story (or a sub-part of one story), ≤2 modules emphasized in the title, ≤1 verb-phrase in the title.

**Self-check before showing the user**: for each proposed issue, name the layers it touches; reject any that touch only one layer; reject any whose title contains `+`/`and`/`with`/`,`; reject any that covers more than one user story. See `verticality.md` for the full rationale and worked examples.

## Step 4 — Present to user

Show the breakdown **grouped by user story** so the user can see "US3 → 2 issues: #A, #B" and judge granularity per story. For each issue show: **Title**, **Type** (AFK/HITL), **Blocked by** (other issue numbers), **Story** (which US), **Layers touched** (the verticality witness — schema/endpoint/agent/tests, etc.).

Skip **done** stories with a one-line note: "US2 — already shipped (found in `internal/foo`)."

Ask: granularity right? verticality right? dependency relationships correct? AFK/HITL assignments right? Iterate until approved.

## Step 5 — Publish

For each approved slice, in dependency order so blocker IDs are real:

### If tracker is **github**

```bash
gh issue create \
  --title "<title>" \
  --label ready-for-agent \   # only for AFK slices; HITL slices get --label needs-human instead
  --body "$(cat <<'EOF'
## What to build
<concise end-to-end behavior — name the layers it crosses>

## Acceptance criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Blocked by
- #<num> (or "None — can start immediately")
EOF
)"
```

### If tracker is **local**

Append a new block to `ISSUES.md` at the repo root. Compute next ID = `1 + max(existing IDs)`.

```markdown
## [open] #<N> — <title>
**Tags**: agent-ready    <!-- or "needs-human, hitl" for HITL slices -->
**Blocked by**: #<other> <!-- or "none" -->

### What to build
<concise end-to-end behavior — name the layers it crosses>

### Acceptance criteria
- [ ] Criterion 1
- [ ] Criterion 2

---
```

`git add ISSUES.md` after writing; do NOT commit (let the user choose when).

## Triage existing issues (alternate mode)

If the user invokes `/to-issues triage` instead of passing a plan:

- For **github**: list issues with no `ready-for-agent` / `needs-human` label and walk them with the user one at a time, asking category + state, then applying labels with `gh issue edit`.
- For **local**: list `ISSUES.md` blocks with no `Tags` field and walk them the same way, editing the file in place.

Triaging issues is now part of this skill — there is no separate `/triage` command.

**See also:** `verticality.md` (sibling aux — anti-patterns, replacements, self-check)
