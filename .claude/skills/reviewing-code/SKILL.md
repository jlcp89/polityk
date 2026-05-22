---
name: reviewing-code
description: Review code changes for quality, security, and convention adherence — analyzes git diff, applies a severity-bucketed checklist, includes a fix loop. Use when finishing a feature, before opening a PR, or whenever changes need a quality pass.
---

# /reviewing-code

Reviews diff-scoped changes against [checklist.md](checklist.md), grouped by severity.

## Step 1 — Identify changes and in-scope lines

Run `git diff` (or `git diff --staged`, or `git diff main...HEAD`, or `gh pr diff <num>` for a PR). Then **output a visible code block** mapping each file to the new-side line numbers of every `+` (added) line before proceeding to Step 2 — this mapping is the **review scope** and must be present in your response.

For PR reviews via `gh api`, extract line numbers mechanically:

```bash
gh api repos/{owner}/{repo}/pulls/{N}/files --paginate | python3 -c "
import json, sys, re
for f in json.load(sys.stdin):
    ln, lines = 0, []
    for row in (f.get('patch') or '').split('\n'):
        if row.startswith('@@'):
            m = re.search(r'\+(\d+)', row)
            if m: ln = int(m.group(1)) - 1
        elif not row.startswith('-'):
            ln += 1
            if row.startswith('+'): lines.append(ln)
    if lines: print(f['filename'] + ': ' + repr(lines))
"
```

For local diffs, walk line-by-line: extract `+{start}` from each `@@` header, increment counter for every non-`-` line, record `+` lines. Exclude `-` lines, `@@` headers, and context lines.

Every comment must cite a line from the scope set. Pre-existing code is out of scope.

Single exception: if a *changed* line introduces a defect that only manifests in *unchanged* code, anchor on the changed line and reference the unchanged line as supporting context.

## Step 2 — Spec compliance gate

If `SPEC.md` exists, verify acceptance criteria are met, no scope creep, no scope gaps, error scenarios from the spec are handled. Fix spec compliance issues BEFORE proceeding to quality review.

## Step 3 — Quality review

For each in-scope file, walk [checklist.md](checklist.md) and bucket findings:

- **Critical** (must fix): security, data loss, breaking changes without migration, missing error handling for external calls.
- **Important** (should fix): missing tests for new logic, convention drift, performance issues (N+1, unnecessary re-renders), poor user-facing error messages.
- **Suggestions** (nice to have): naming, simplification, type usage, docs for complex logic.
- **Positive** (well done): patterns worth highlighting.

Before writing each bullet: (1) confirm the line is in the Step 1 scope set, and (2) quote the exact `+` line verbatim from the diff. If you cannot do both, drop the bullet.

## Step 4 — Present review

```
## Code Review Summary
**Files**: {N} | **+{added} / -{removed}**

### Critical ({N})
- [{file}:{line} `{verbatim + line text}`] {issue} — {fix}

### Important ({N})
### Suggestions ({N})
### Positive

### Verdict: {APPROVE | APPROVE WITH SUGGESTIONS | REQUEST CHANGES}

### Merge blockers ({N})
**`{file}:{line}`** — {1–2 sentence PR comment}
```

The Merge blockers block is paste-ready for the PR.

## Step 5 — Fix loop

If critical or important issues exist, ask: "Want me to fix the {N} issues?" On approval: fix → proof cycle → re-review → repeat until clean. Then run the full proof cycle one last time and report results.
