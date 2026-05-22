---
paths:
  - "**/*.kt"
  - "**/*.kts"
---

# Kotlin Code Style

## Naming
- Files: PascalCase matching primary class (`UserViewModel.kt`)
- Classes/Interfaces: PascalCase
- Functions/properties: camelCase
- Constants: UPPER_SNAKE_CASE in companion objects
- Packages: lowercase, no underscores

## Patterns
- Prefer `data class` for DTOs and value objects
- Use `sealed class`/`sealed interface` for restricted hierarchies
- Extension functions over utility classes — but limit to 3 per file to avoid discovery issues
- Use `?.let {}` and `?.run {}` — avoid deep null chains
- Prefer `when` over `if-else` chains
- Use coroutines over callbacks — `suspend` functions
- Flows for reactive streams, StateFlow for UI state

## Coroutines
- Launch in `viewModelScope` (Android) or structured `CoroutineScope`
- Use `withContext(Dispatchers.IO)` for blocking I/O — never block the Main dispatcher
- Use `SupervisorJob` when child failures should not cancel siblings
- Prefer `flow {}` builders for cold streams, `MutableStateFlow` for hot state
- Use `catch {}` operator for Flow error handling — not try/catch around collect

## Compose (if applicable)
- Composable functions: PascalCase (`UserCard`, `LoginScreen`)
- State hoisting: stateless composables receive state as params
- `remember` and `rememberSaveable` for local state
- Preview functions: `@Preview` annotation with meaningful params
- Modifier parameter always first optional param

## Limits
- Functions: 40 lines max, 4 params max, nesting depth 3
- Files: 300 lines max
- See `quality.md` for full table

## Formatting
- Follow project's ktlint/detekt config
- Trailing commas in multiline declarations
