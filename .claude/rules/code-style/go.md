---
paths:
  - "**/*.go"
---

# Go Code Style

## Naming
- Packages: short, lowercase, single-word (`api`, `db`, `models`)
- Exported: PascalCase (`HandleEvent`, `UserService`)
- Unexported: camelCase (`parseInput`, `dbConn`)
- Interfaces: er-suffix for single-method (`Reader`, `Handler`)
- Files: snake_case (`user_service.go`, `event_handler.go`)
- Test files: `*_test.go` in same package

## Patterns
- Accept interfaces, return structs
- Define interfaces at the consumption site, not implementation
- Keep interfaces small (1-3 methods)
- Constructor functions: `NewXxx()` pattern
- Error handling: check errors immediately, don't defer error checks
- Use `fmt.Errorf("context: %w", err)` for error wrapping
- No named returns except for documentation on complex signatures

## Package Organization
- `cmd/` — entry points
- `internal/` — private packages
- Package by domain, not by layer (for larger projects)
- Avoid `utils/` — put functions where they're used

## Limits
- Functions: 60 lines max, 5 params max, nesting depth 3
- Files: 400 lines max
- See `quality.md` for full table

## Formatting
- `gofmt` is non-negotiable — always format before commit
- `goimports` for import ordering
- No blank lines inside function bodies unless separating logical blocks
