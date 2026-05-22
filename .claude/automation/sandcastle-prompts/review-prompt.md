# REVIEW

Issue: {{ISSUE_NUMBER}} — {{ISSUE_TITLE}}
Branch: {{BRANCH}}

# DIFF

```
!`git diff main...{{BRANCH}}`
```

# CRITERIA

Walk the in-scope diff against the project's review checklist (`.claude/skills/reviewing-code/checklist.md` if present, otherwise the standard severity buckets below).

**Critical** (must fix): security, data loss, breaking changes without migration, missing error handling at external boundaries, **any change to the blackout middleware (`internal/middleware/blackout.go`) without a `needs-human` label**.
**Important** (should fix): missing tests for new logic, convention drift, performance issues, poor user-facing error messages.
**Suggestions**: naming, simplification, type usage, docs for complex logic.

# SCOPE RULE

Every comment must cite a `+` line in the diff. Pre-existing code is out of scope unless a changed line introduces a defect that manifests in unchanged code (then anchor on the changed line).

# OUTPUT

Structured JSON ONLY:

```json
{
  "issue": {{ISSUE_NUMBER}},
  "branch": "{{BRANCH}}",
  "verdict": "approve | request-changes",
  "critical": [{"file":"...", "line":1, "comment":"..."}],
  "important": [...],
  "suggestions": [...],
  "merge_blockers_pasteable": "<paste-ready PR comment block>"
}
```

If `verdict == "request-changes"`, the merge step will not run. The implement step is re-invoked with the critical+important comments as additional context.
