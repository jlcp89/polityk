---
name: techdebt
description: Scans for and catalogs technical debt across the project. Searches for TODOs, suppressed warnings, duplicated code, oversized functions, and missing tests. Categorizes and prioritizes findings by severity. Use when assessing code health or planning cleanup work.
---

# Tech Debt — Audit & Prioritise

Scans the project for debt indicators, categorises findings, and prioritises by impact.

## Step 1 — Determine Scope

If `$ARGUMENTS` (e.g., `/techdebt src/auth/`) specifies a path, scope to it. Otherwise scan the full project. Check the issue tracker (`gh issue list` or `ISSUES.md`) for active-work context, so debt-vs-active-work doesn't get conflated.

## Step 2 — Automated Detection

Search for these indicators:

**Code markers:**
- `TODO`, `FIXME`, `HACK`, `WORKAROUND`, `XXX` comments
- Suppressed linter warnings (`// eslint-disable`, `# noqa`, `//nolint`, `#[allow(...)]`)
- Suppressed type errors (`// @ts-ignore`, `// @ts-expect-error`, `# type: ignore`)

**Type safety:**
- `any` types (TypeScript), untyped parameters (Python), `interface{}` (Go)
- Missing return types on public functions
- Type assertions / unsafe casts

**Code smells:**
- Functions over 50 lines
- Files over 500 lines
- Duplicated code blocks (>10 lines substantially similar)
- Deeply nested logic (>3 indentation levels)

**Testing gaps:**
- Public functions without test coverage
- Skipped/disabled tests (`.skip`, `@pytest.mark.skip`, `t.Skip()`)

**Dependencies:**
- Outdated major versions (check lock files)
- Deprecated packages (deprecation warnings)

## Step 3 — Categorise & Prioritise

Group findings using the rubric in [scoring.md](scoring.md): five categories (code quality, architecture, testing, dependencies, documentation), four priority levels (P0–P3), and S/M/L effort sizes.

## Step 4 — Present Report

Use the report format in [scoring.md](scoring.md): summary counts, then a findings table with file, line, category, priority, description, effort.

## Step 5 — Commit to Parking Lot

For P0 and P1 findings:

> "Found {count} critical/high priority items. Add them to REQUIREMENTS.md parking lot?"

On approval, append each P0/P1 finding to the `## Parking Lot` section of `REQUIREMENTS.md` using the format in [scoring.md](scoring.md).
