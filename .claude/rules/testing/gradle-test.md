---
paths:
  - "**/Test*.kt"
  - "**/*Test.kt"
  - "**/test/**/*.kt"
  - "**/androidTest/**/*.kt"
---

# Gradle/Kotlin Testing Rules

## File Naming
- Unit tests: `src/test/kotlin/` mirror of `src/main/kotlin/`
- Instrumented: `src/androidTest/kotlin/`
- Name: `ClassNameTest.kt`

## Patterns
- Use JUnit 5 for unit tests
- Use `@Before`/`@After` for setup/teardown
- Use `@DisplayName` for readable test names
- Mock with MockK (idiomatic Kotlin mocking)
- Use `runTest` for coroutine tests

## Compose Testing
- Use `composeTestRule` for UI tests
- Find by semantics: `onNodeWithText`, `onNodeWithTag`
- Use `testTag` modifier for test identification
- Assert: `assertIsDisplayed()`, `assertTextEquals()`

## Assertions
- Use Truth or kotlin.test assertions
- `assertEquals(expected, actual)` — expected first
- Test ViewModel state emissions with Turbine
