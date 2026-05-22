# Autonomous Loop

This is the AFK loop. Each iteration: pick one ready task, implement it end-to-end, commit, close, output the completion sentinel. Run with `--dangerously-skip-permissions`.

# ISSUES

Tracker: **github**.

List ready tasks:

```
gh issue list --label ready-for-agent --state open --limit 10 --json number,title,body,labels
```

Filter for ones tagged ready for an agent (label `ready-for-agent` for GitHub; the literal `agent-ready` tag in the body for `ISSUES.md`). Skip anything tagged HITL or human-only.

**If the context above contains an `## Assigned issue` section, that is your task — work on that specific issue. Do not pick a different one.** The wrapper has already claimed it for this worker.

If no issue is assigned in context (solo mode), list ready tasks yourself via the command above. Filter for ones tagged ready for an agent. Skip anything tagged HITL, human-only, or with any `claimed-by-*` label.

If there are no ready tasks, output `<promise>NO MORE TASKS</promise>` and stop.

You have also been passed the recent commits in context. Read them before picking a task — work that was almost-done last iteration takes priority over fresh starts.

# TASK SELECTION

Pick exactly one. Priority order:

1. Critical bugfixes
2. Development infrastructure (tests, types, dev scripts)
3. Tracer-bullet new features (a thin end-to-end slice)
4. Polish and quick wins
5. Refactors

# EXPLORATION

Before writing code: read the issue body + comments, then explore the relevant files. Use the project's domain glossary (`CONTEXT.md`) and respect ADRs in the area you're touching.

# IMPLEMENTATION

Use red-green-refactor where possible.

- **RED**: write a single failing test
- **GREEN**: write the minimal implementation that passes
- **RED**: write the next failing test

Repeat until the issue's acceptance criteria are met.

# FEEDBACK LOOPS

Before committing, run the proof cycle for the area you touched (see `.claude/rules/verification.md`):

- Go (`cmd/`, `internal/`): `go vet ./...` && `go test -race ./...`
- Python (`pipeline/`): `uv run mypy pipeline/` && `uv run pytest pipeline/tests/`
- Android (`android/`): `./gradlew :app:compileDebugKotlin` && `./gradlew test`

Do NOT skip these. If they fail, fix before committing.

# COMMIT

Make a single git commit directly on the current branch. Do NOT create a new branch.
After committing, push: `git push origin HEAD`.

Commit message must include:

1. Issue reference
2. Key decisions made
3. Files changed (one-line list)
4. Blockers or notes for the next iteration (if any)

# CLOSE

If complete:

```
gh issue close $ID --comment "Closed by AFK loop. Merged and pushed to main."
```

If not complete: leave a comment on the issue with what was done and what is left. Do NOT close.

# FINAL

Output `<promise>COMPLETE</promise>`.

ONLY WORK ON A SINGLE TASK PER ITERATION.
