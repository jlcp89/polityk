# Tech Debt — Categorisation & Priority Rubric

Used by `/techdebt` Steps 3 and 4.

## Categories

| Category | Examples |
|---|---|
| **Code Quality** | Long functions, duplication, `any` types, deep nesting |
| **Architecture** | Circular dependencies, tight coupling, misplaced logic |
| **Testing** | Missing tests, skipped tests, flaky tests |
| **Dependencies** | Outdated packages, deprecated APIs, security advisories |
| **Documentation** | Missing or stale comments, undocumented public APIs |

## Priority Levels

| Priority | Criteria | Action |
|---|---|---|
| **P0 — Fix now** | Security vulnerabilities, data-loss risks, broken functionality | Fix immediately |
| **P1 — Fix this sprint** | Actively causing bugs, blocking development, flaky tests | Schedule soon |
| **P2 — Plan for** | Code-quality improvement, maintainability, moderate risk | Add to backlog |
| **P3 — Backlog** | Nice-to-have cleanup, style consistency, minor improvements | Track only |

## Effort Sizing

- `S` — small, under 1 hour
- `M` — medium, 1–4 hours
- `L` — large, over 4 hours

## Report Format

```
## Tech Debt Report — {scope}
Date: {date}

### Summary
- P0 (critical): {count}
- P1 (high):     {count}
- P2 (medium):   {count}
- P3 (low):      {count}
- Total:         {count}

### Findings

| # | File | Line | Category | Priority | Description | Effort |
|---|------|------|----------|----------|-------------|--------|
| 1 | src/auth/login.ts | 42 | Code Quality | P1 | Function 85 lines, 4 levels deep | M |
```

## Parking-Lot Append Format

For P0 and P1 findings, append to `## Parking Lot` in `REQUIREMENTS.md`:

```markdown
- [ ] [P{n}] {description} — {file}:{line}
```
