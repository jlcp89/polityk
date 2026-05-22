# Conflict Resolution Task

You are resolving a git rebase conflict as part of an automated pipeline.
`git rebase main` has paused with conflicts. Your working directory is already
the conflicted worktree — you do not need to `cd` anywhere.

## Resolution principles

- **Keep both**: if main added feature A and the branch added feature B in the
  same file, include both. This is feature integration, not a fork.
- **Trust the branch**: the branch's new code implements the assigned issue —
  do not drop it.
- **Trust main**: main's changes are already reviewed and merged — do not
  revert them.
- **No guessing**: if the semantic intent of either side is ambiguous and a
  wrong merge would silently break behaviour, prefer UNRESOLVABLE.

## Steps

1. Run `git status` to confirm the rebase state and see conflicted paths.
2. For each conflicted file:
   a. Read the file — it contains conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`).
   b. Understand what each side brought.
   c. Edit the file to remove all conflict markers, preserving both sides' intent.
   d. Run `git add <file>` to stage the resolution.
3. Run `git rebase --continue`.
   - If more conflicts appear (multi-commit rebase), repeat from step 2.
   - The rebase is complete when `git rebase --continue` exits 0 with no
     remaining REBASING state (`git status` shows a clean working tree on the branch).
4. Run the type-check for the touched area to confirm the merged result compiles:
   - Go: `go vet ./...`
   - Python: `uv run mypy pipeline/`
   - Android: `./gradlew :app:compileDebugKotlin`
   Fix trivial compilation errors (missing imports, unused vars from merge) if needed.
5. If at any point a conflict is genuinely irresolvable (two incompatible
   implementations of the same function where picking one loses real work),
   run `git rebase --abort` and output `<promise>UNRESOLVABLE</promise>`.
6. When the rebase completes successfully, output `<promise>RESOLVED</promise>`.

Output only the sentinel as your final line. No prose after it.
