# TASK

Implement issue {{ISSUE_NUMBER}} — {{ISSUE_TITLE}}.

Pull in the issue:

```
gh issue view $ID --comments
```

Only work on this issue.

Work on branch `{{BRANCH}}`. Make commits, run feedback loops, and follow the close protocol when done.

# CONTEXT

Last 10 commits:

```
!`git log -n 10 --format="%H%n%ad%n%B---" --date=short`
```

# EXPLORATION

Read the relevant files. Pay extra attention to test files in the affected area.

# EXECUTION

Use red-green-refactor.

1. RED: write one failing test
2. GREEN: write the minimal implementation
3. REPEAT until acceptance criteria are met
4. REFACTOR

# FEEDBACK LOOPS

Before committing, run the proof cycle for the area you touched (see `.claude/rules/verification.md`):

- Go (`cmd/`, `internal/`): `go vet ./...` && `go test -race ./...`
- Python (`pipeline/`): `uv run mypy pipeline/` && `uv run pytest pipeline/tests/`
- Android (`android/`): `./gradlew :app:compileDebugKotlin` && `./gradlew test`

All must pass. Fix before committing.

# COMMIT

Single commit. Message format:

```
RALPH: <issue title>

Issue: #{{ISSUE_NUMBER}}
Decisions: <key decisions>
Files: <changed paths>
Notes: <blockers or follow-ups, or "none">
```

# CLOSE

If the acceptance criteria are met: do nothing further (the merge step will close the issue after review).

If not: leave a comment on the issue summarizing what was done and what is left. Do NOT close.

# DONE

Output `<promise>COMPLETE</promise>`.

ONLY WORK ON A SINGLE TASK.
