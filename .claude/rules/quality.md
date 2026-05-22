---
paths:
  - "src/**"
  - "lib/**"
  - "app/**"
  - "pkg/**"
  - "internal/**"
  - "cmd/**"
---

# Quality Standards & Limits

## Self-Check

Before considering any change complete:

1. Re-read the original requirement — does the implementation actually satisfy it?
2. Trace the happy path — does it work end-to-end?
3. Trace the error path — does it fail gracefully?
4. Check edge cases — empty inputs, boundary values, concurrent access?
5. Evaluate elegance — is this the simplest solution that works?

## Red Flags

Stop and reconsider if you notice:

- "It works but I'm not sure why"
- "This is temporary" (it never is)
- Suppressing errors instead of handling them
- Copy-pasted logic instead of shared abstraction
- Adding complexity to handle a case that hasn't happened

Use `/grill` for structured interrogation of any design decision.

## Per-Language Limits

Hard numeric limits. When exceeded, flag it — don't silently accept.

| Language | Function Lines | File Lines | Params | Nesting Depth | Cyclomatic Complexity |
|----------|---------------|------------|--------|---------------|----------------------|
| TypeScript/JS | 50 | 300 | 4 | 3 | 10 |
| Go | 60 | 400 | 5 | 3 | 10 |
| Rust | 60 | 500 | 5 | 4 | 12 |
| Python | 40 | 300 | 5 | 3 | 10 |
| Java | 50 | 400 | 5 | 3 | 10 |
| Kotlin | 40 | 300 | 4 | 3 | 10 |
| Ruby | 30 | 250 | 4 | 3 | 8 |

## When Limits Are Exceeded

1. **Flag it** — don't ignore. State which limit was exceeded and by how much.
2. **Refactor first** — extract helper functions, split files, reduce branching.
3. **Justify exceptions** — test setup, generated code, and data tables may legitimately exceed file-line limits. Document why.

## Definition of Done

A change is complete when ALL three pass:
1. **Numeric limits** — function/file sizes within bounds (table above)
2. **5-point self-check** — all items above verified
3. **Verification gate** — proof cycle run, evidence shown (see `verification.md`)
