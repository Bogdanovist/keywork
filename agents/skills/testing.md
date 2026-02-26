# Skill: Testing

## When to Use

Use this skill when the primary task is creating, modifying, or improving tests. For tasks where testing is secondary (e.g., implementing a feature that includes tests), follow the testing guidance in the relevant skill file instead.

## Framework Detection

Before writing tests, identify the repo's test framework from `agents/repos/{REPO_NAME}/config.yaml` under `checks.test`. Common frameworks:

| Language | Frameworks |
|----------|-----------|
| Python | pytest, unittest |
| JavaScript/TypeScript | jest, vitest, mocha |
| Go | go test |
| Rust | cargo test |
| Ruby | rspec, minitest |
| Java/Kotlin | JUnit, TestNG |

Check for existing test files and match their patterns exactly. If no tests exist yet, use the framework most common for the repo's language and framework combination.

## File Organization

Tests mirror the source directory structure:

```
src/                          tests/
├── auth/                     ├── auth/
│   ├── login.{ext}          │   ├── test_login.{ext}
│   └── tokens.{ext}         │   └── test_tokens.{ext}
├── api/                      ├── api/
│   └── routes.{ext}         │   └── test_routes.{ext}
└── utils.{ext}              └── test_utils.{ext}
```

One test file per source file. Do not combine tests for multiple source files.

## Naming Conventions

Follow the repo's existing convention. If starting fresh:

| Language | Test file | Test function/method |
|----------|-----------|---------------------|
| Python | `test_{module}.py` | `test_{function}_{scenario}` |
| JS/TS | `{module}.test.ts` or `{module}.spec.ts` | `it("should {behavior}")` |
| Go | `{module}_test.go` | `Test{Function}{Scenario}` |
| Rust | inline `#[cfg(test)]` mod or `tests/{module}.rs` | `fn test_{function}_{scenario}()` |
| Ruby | `{module}_spec.rb` | `it "{behavior}"` |

Test names must describe the scenario, not the implementation:

```
# Good
test_login_rejects_expired_token
test_calculate_total_with_empty_cart_returns_zero

# Bad
test_login
test_1
test_function_calls_validate
```

## Unit Test Structure

Follow the Arrange-Act-Assert pattern:

```
# Arrange — set up inputs and expected outputs
input_data = create_test_input(...)
expected = ...

# Act — call the function under test
result = function_under_test(input_data)

# Assert — verify the result
assert result == expected
```

One logical assertion per test. Testing multiple unrelated behaviors in one test makes failures harder to diagnose.

## What to Test

- **Happy path**: Normal input produces expected output
- **Edge cases**: Empty inputs, boundary values, single-element collections, zero, negative numbers
- **Error handling**: Invalid input raises appropriate errors, error messages are correct
- **Return types/shapes**: Correct structure, required fields present, proper types

Every new public function must have at minimum:
1. One happy-path test
2. One edge-case or error-handling test

## What Not to Test

- Private/internal functions — test them through their public callers
- Third-party library behavior — trust the library's own tests
- Language built-ins — do not test that `len([1,2,3]) == 3`
- Configuration files — unless they drive runtime behavior

## Mocking

Mock external dependencies at the boundary. Never mock the unit under test.

**Do mock:**
- HTTP clients and API calls
- Database connections and queries
- File system operations (when testing logic, not I/O)
- Time/date functions (when testing time-dependent logic)
- Environment variables

**Do not mock:**
- The function being tested
- Simple data transformations
- Pure utility functions

Mock at the point of use, not at the point of definition:

```
# Python example — mock where it's imported, not where it's defined
@patch("myapp.auth.login.requests.post")  # where login.py imports requests
def test_login_calls_auth_service(mock_post):
    mock_post.return_value.status_code = 200
    result = login("user", "pass")
    assert result.authenticated is True
```

## Test Data

- Use factories or fixtures for reusable test data
- Keep test data minimal — only include fields relevant to the test
- Never depend on external data sources (databases, APIs, files on disk)
- Use descriptive variable names: `expired_token`, `admin_user`, not `token1`, `user_a`

Shared fixtures belong in a shared conftest/setup file. Test-specific fixtures stay in the test file.

## Integration Tests

Integration tests verify component boundaries — how modules interact with each other and with external systems.

- Use real implementations where safe (in-memory databases, test servers)
- Isolate from production systems — never read/write production data
- Clean up after each test — delete created records, reset state
- Mark integration tests distinctly so they can be run separately from unit tests

## Running Tests

Use the test command from `agents/repos/{REPO_NAME}/config.yaml` under `checks.test`. Common patterns:

```bash
# Run all tests
{checks.test}

# Run a specific file
pytest tests/test_auth/test_login.py -v
jest --testPathPattern=auth/login.test.ts
go test ./auth/...
cargo test auth::login

# Run by name pattern
pytest -k "test_login"
jest -t "should reject expired token"
go test -run TestLoginRejectsExpiredToken
```

Always run the full test suite after making changes to verify nothing is broken.

## Anti-Patterns

- **Order-dependent tests**: Each test must run in isolation. Never rely on test execution order.
- **Testing implementation, not behavior**: Test what a function returns, not how it computes it. Refactors should not break tests.
- **Network-dependent tests**: Unit tests must not make real HTTP calls. Use mocks or recorded responses.
- **Shared mutable state**: Do not share mutable objects between tests. Create fresh instances in each test.
- **Overly broad assertions**: `assert result is not None` tells you nothing. Assert specific values and structures.
- **Commented-out tests**: Delete them. Version control preserves history.
- **Testing constants**: `assert STATUS_OK == 200` tests nothing useful.

## Checklist Before Submitting

1. All new public functions have tests
2. All tests pass locally (`checks.test` from config.yaml)
3. Test names describe the scenario being tested
4. No hardcoded paths, URLs, or credentials in test code
5. No tests depend on execution order or external state
6. Mocks are reset between tests (no shared state leaking)
