# Skill: Refactoring

## When to Use

Use this skill when the task restructures existing code without changing its external behavior. This includes extracting functions, renaming identifiers, moving code between modules, simplifying logic, and removing dead code. If the task also adds new behavior, the refactoring portion should be done as a separate step.

## Safety Protocol

Refactoring must not break existing behavior. Follow this sequence strictly:

1. **Run all tests before starting** — confirm the baseline is green. Use `checks.test` from `agents/repos/{REPO_NAME}/config.yaml`.
2. **Make one logical change at a time** — do not batch multiple refactors into a single step.
3. **Run all tests after each change** — if tests fail, revert and investigate before proceeding.
4. **Run all tests at the end** — full suite pass confirms the refactoring is complete.

If the repo has linting configured (`checks.lint`), run it after each change as well. Refactoring should never introduce lint violations.

## Extract Function / Method

Extract when a block of code:
- Has a clear single purpose that can be named
- Exceeds ~10 lines
- Is duplicated in multiple places
- Lives inside a deeply nested conditional

Steps:
1. Identify the block and its inputs (parameters) and outputs (return values)
2. Create a new function with a descriptive name
3. Move the block into the new function
4. Replace the original block with a call to the new function
5. Run tests

```
# Before
def process_order(order):
    # ... 15 lines calculating discount ...
    # ... 10 lines applying tax ...
    # ... 5 lines formatting receipt ...

# After
def process_order(order):
    discount = calculate_discount(order)
    total = apply_tax(order.subtotal - discount, order.region)
    return format_receipt(order, total)

def calculate_discount(order):
    # ... clear, focused logic ...

def apply_tax(amount, region):
    # ... clear, focused logic ...

def format_receipt(order, total):
    # ... clear, focused logic ...
```

## Rename

Renaming must update every reference — including imports, tests, documentation, configuration files, and string references (log messages, error messages, serialization keys).

Steps:
1. Search the entire codebase for the identifier (use grep/ripgrep, not just IDE rename)
2. Check for dynamic references: string-based lookups, reflection, serialization formats
3. Check for external references: API contracts, database column names, config files
4. Rename all occurrences
5. Run tests and lint

When renaming public API identifiers (exported functions, API endpoints, database columns), consider backward compatibility — see the section below.

## Move Code Between Modules

Moving a function, class, or block to a different file or package.

Steps:
1. Copy the code to the destination module
2. Move any imports the code depends on
3. Update the destination module's imports
4. Update all files that imported from the old location
5. Check for circular import issues — if moving creates a cycle, extract shared code into a new utility module
6. Delete the code from the original location
7. Run tests

Watch for re-exports: if the old module re-exported the moved code for public use, add a temporary re-export with a deprecation warning.

## Simplify Conditionals

Replace deeply nested conditionals with clearer patterns:

**Early returns / guard clauses:**
```
# Before
def get_price(user, product):
    if user is not None:
        if product is not None:
            if product.in_stock:
                price = product.base_price
                if user.is_premium:
                    price *= 0.9
                return price
            else:
                return None
        else:
            return None
    else:
        return None

# After
def get_price(user, product):
    if user is None or product is None:
        return None
    if not product.in_stock:
        return None

    price = product.base_price
    if user.is_premium:
        price *= 0.9
    return price
```

**Lookup tables instead of if/elif chains:**
```
# Before
if status == "active":
    label = "Active"
elif status == "paused":
    label = "On Hold"
elif status == "cancelled":
    label = "Cancelled"

# After
STATUS_LABELS = {
    "active": "Active",
    "paused": "On Hold",
    "cancelled": "Cancelled",
}
label = STATUS_LABELS.get(status, "Unknown")
```

## Remove Dead Code

Dead code is code that is never executed — unused functions, unreachable branches, commented-out blocks.

Steps:
1. Grep the entire codebase for references to the identifier
2. Check for dynamic references: string-based lookups, plugin registries, reflection
3. Check exports: is the identifier part of a public API or library interface?
4. Check entry points: CLI commands, cron jobs, and scripts may reference code not found via import tracing
5. If no references exist, delete the code
6. Run tests

Do not comment out code "for later." Version control preserves history. Delete it.

## Incremental Commits

Each commit during a refactoring session should:
- Contain exactly one logical change (one extract, one rename, one move)
- Pass all tests
- Have a descriptive commit message explaining what was refactored and why

This makes it possible to bisect regressions and revert individual changes without losing the entire refactoring.

## Backward Compatibility

When refactoring code that is part of a public API, library interface, or cross-service contract:

1. **Keep the old interface working** — create a wrapper that calls the new implementation
2. **Add a deprecation signal** — log a warning, add a `@deprecated` annotation, or document the change
3. **Set a removal timeline** — note in the deprecation message when the old interface will be removed
4. **Update dependents** — migrate all internal callers to the new interface before removing the old one

```
# Backward-compatible rename example
def calculate_total(items):
    """Compute order total. Use compute_order_total() instead."""
    import warnings
    warnings.warn("calculate_total is deprecated, use compute_order_total", DeprecationWarning)
    return compute_order_total(items)

def compute_order_total(items):
    # ... new implementation ...
```

## Anti-Patterns

- **Big-bang refactoring**: Changing hundreds of lines across dozens of files in one step. Break it down.
- **Refactoring without tests**: If there are no tests covering the code, write tests first, then refactor.
- **Mixing refactoring with behavior changes**: A refactor commit should produce identical behavior. New behavior is a separate commit.
- **Renaming to something less clear**: Names should get more descriptive, not shorter or more abbreviated.
- **Moving code without updating all references**: Results in import errors. Always grep the full codebase.
- **Premature abstraction**: Do not extract a shared function until there are at least two concrete use cases. Duplication is cheaper than the wrong abstraction.

## Checklist Before Submitting

1. All tests pass (same pass count as before the refactoring)
2. Lint passes with no new violations
3. No leftover TODO/FIXME markers from the refactoring process
4. Each commit contains one logical change
5. No behavioral changes — inputs and outputs are identical
6. All imports and references are updated
