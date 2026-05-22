# Impact Analysis Detail (refactor Step 2)

The bar for Step 2 is `Grep + Read + git log` of the target area. Below: what to do, how to present, and what NOT to do.

## What to do

1. Use Grep to find every reference to symbols being moved or renamed.
2. Use Read to inspect callers, importers, and dependents.
3. List all files that will need to change.
4. Identify the test files covering the target code.
5. `git log --oneline -10 -- <target files>` — capture whether the area is in active flux. Recent commits ≠ a stable base for refactor.
6. State the call graph in one sentence: `"{N} callers across {M} files; {test_count} tests cover the target; last touched {date} by {commit_msg}"`

## How to present

```
Impact Analysis:
  Target files:    {list}
  Affected files:  {list of importers/dependents}
  Test coverage:   {list of test files}
  Recent activity: {git log summary}
  Estimated steps: {count}
```

Then ask: `"Proceed with this scope?"` and wait.

## What NOT to do (forbidden without the summary in transcript)

- Propose a refactor plan from inspecting one or two files. You have not seen the full call graph.
- Skip the `git log` — recent active flux means the refactor will collide with in-progress work.
- Treat "I read the file once" as equivalent to impact analysis. The bar is Grep + Read + git log.
- Move to Step 3 (Baseline) without first stating the one-sentence call-graph summary above.
