# MERGE

Issue: {{ISSUE_NUMBER}}
Branch: {{BRANCH}}

# PRECONDITIONS

The review step must have returned `verdict: approve`. If not, stop.

# ACTIONS

1. Final feedback loop. Run the proof cycle for the area touched (see `.claude/rules/verification.md`):

   - Go: `go vet ./...` && `go test -race ./...`
   - Python: `uv run mypy pipeline/` && `uv run pytest pipeline/tests/`
   - Android: `./gradlew :app:compileDebugKotlin` && `./gradlew test`

   If any fails, abort the merge.

2. Merge:

   ```bash
   git checkout main
   git merge --ff-only {{BRANCH}}
   git push
   ```

   If `--ff-only` fails, do NOT force. Stop and surface the conflict — a human resolves it.

3. Close the issue:

   ```
   gh issue close $ID --comment "Closed by AFK loop. Merged and pushed to main."
   ```

4. Delete the merged branch locally and on the remote (if applicable).

# DONE

Output `<promise>MERGED</promise>`.
