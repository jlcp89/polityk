# Code Review Checklist

**Apply only to changed lines.** This checklist evaluates lines added or modified in the current diff (see Step 1b of `SKILL.md`). Pre-existing code outside the diff is out of scope, regardless of what the checklist would otherwise catch.

## Security
- [ ] No hardcoded secrets, tokens, or passwords
- [ ] User input validated and sanitized
- [ ] SQL queries parameterized (no string concatenation)
- [ ] HTML output escaped (no XSS vectors)
- [ ] Auth checks present on protected endpoints
- [ ] No sensitive data in logs or error messages
- [ ] File uploads validated (type, size, name)

## Correctness
- [ ] Logic handles edge cases (empty, null, boundary values)
- [ ] Error cases handled explicitly (not swallowed or ignored)
- [ ] Async operations handle rejection/timeout
- [ ] Database transactions used for multi-step operations
- [ ] Race conditions considered for concurrent operations
- [ ] Cleanup happens on error paths (connections, files, locks)

## Testing
- [ ] New logic has corresponding tests
- [ ] Edge cases have tests
- [ ] Error paths have tests
- [ ] Tests are deterministic (no flaky dependencies)
- [ ] Test names describe behavior, not implementation
- [ ] Mocks are appropriate (external deps, not internal)

## Performance
- [ ] No N+1 query patterns
- [ ] No unnecessary re-renders (React)
- [ ] Large lists use pagination or virtualization
- [ ] Expensive operations cached appropriately
- [ ] No synchronous operations that should be async
- [ ] Bundle size impact considered for new dependencies

## Conventions
- [ ] File naming matches project pattern
- [ ] Code organization matches project structure
- [ ] Error handling follows project pattern
- [ ] Logging follows project format
- [ ] Types/interfaces follow project conventions
- [ ] Tests follow project testing patterns

## Maintainability
- [ ] No dead code or commented-out code
- [ ] No TODOs without context or tracking
- [ ] Complex logic has explanatory comments
- [ ] Functions are focused (single responsibility)
- [ ] No magic numbers — use named constants
- [ ] Dependencies are justified (not added frivolously)
