# PLAN

Issue: {{ISSUE_NUMBER}} — {{ISSUE_TITLE}}

Pull in the issue:

```
gh issue view $ID --comments
```

If it has a parent PRD or spec, pull that in too.

# CONTEXT

Here are the last 10 commits for orientation:

```
!`git log -n 10 --format="%H%n%ad%n%B---" --date=short`
```

# OUTPUT

Produce a structured JSON plan ONLY. No prose. Schema:

```json
{
  "issue": {{ISSUE_NUMBER}},
  "branch": "agent/issue-{{ISSUE_NUMBER}}",
  "approach": "<one-paragraph approach>",
  "files": [
    {"path": "<path>", "change": "<add|edit|delete>", "summary": "<one line>"}
  ],
  "tests": [
    {"path": "<path>", "summary": "<one line>"}
  ],
  "risks": ["<one-line risk>"],
  "ready_for_implement": true
}
```

If the issue is ambiguous, set `ready_for_implement: false` and add a `questions` array. The implement step will not run until the maintainer resolves the questions.
