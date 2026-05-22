---
paths:
  - "src/**"
  - "lib/**"
  - "app/**"
  - "pkg/**"
  - "internal/**"
  - "cmd/**"
  - "**/*.rs"
  - "**/*.go"
  - "**/*.py"
  - "**/*.ts"
  - "**/*.js"
  - "**/*.java"
  - "**/*.kt"
  - "**/*.rb"
---

# Think Before Coding

Before editing any source file, run through SAIV:

**Scope** — What exactly changes? What must NOT change?
**Approach** — Simplest path? What are the alternatives?
**Impact** — What could break? What depends on the code being changed?
**Verify** — How will you prove it works? (see `verification.md`)

## When This Applies

- Ad-hoc code changes (not driven by a skill workflow)
- Skills like /new-feature and /debugging have their own structured thinking — this fills the gap for everything else

## Anti-Patterns

- Jumping straight to editing without reading the surrounding code
- Changing a function signature without checking all call sites
- "Quick fix" that ignores the broader context
- Modifying test assertions to make them pass instead of fixing the code
