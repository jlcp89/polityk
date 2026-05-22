---
paths:
  - "**/test_*"
  - "**/*_test.py"
  - "**/tests/**"
  - "**/conftest.py"
---

# Pytest Testing Rules

## File Naming
- Test files: `test_<module>.py` or `<module>_test.py`
- Conftest: `conftest.py` for shared fixtures (at appropriate directory level)

## Patterns
- Use fixtures for setup/teardown (`@pytest.fixture`)
- Parametrize for multiple test cases (`@pytest.mark.parametrize`)
- Use `conftest.py` for shared fixtures — avoid inheritance-based test classes
- Prefer function-based tests over class-based
- Use `tmp_path` fixture for temporary files
- Use `monkeypatch` fixture for patching (over `unittest.mock.patch`)

## Assertions
- Use plain `assert` statements — pytest rewrites them for good output
- For exceptions: `with pytest.raises(ValueError, match="expected msg")`
- Compare complex objects with `==` — pytest shows diffs

## Async Tests
- Use `pytest-asyncio` with `@pytest.mark.asyncio`
- Use `httpx.AsyncClient` for testing FastAPI endpoints

## Fixtures
- Scope appropriately: `function` (default), `module`, `session`
- Use `yield` fixtures for cleanup
- Avoid fixture chains deeper than 3 levels
