"""BigCodeBench/854 independently designed DEVELOPMENT-ONLY task adapter.

No official/private tests, no model calls, no code execution in this module.
The proposed suite is intentionally not approved until a person reviews it.
"""
from __future__ import annotations

from collections import Counter
from itertools import permutations
from math import factorial
from typing import Any

TASK_ID = "BigCodeBench/854"
ENTRY_POINT = "task_func"
MAX_N = 4


def _valid_numbers(value: Any) -> list[int]:
    if type(value) is not list:
        raise TypeError("numbers must be a list")
    # bool is a subclass of int. Exclude it as an explicit conservative choice;
    # do not add bool cases until the benchmark's original contract is resolved.
    if any(type(x) is not int for x in value):
        raise TypeError("list elements must be integers")
    if any(x < 0 for x in value):
        raise ValueError("integers must be nonnegative")
    if len(value) > MAX_N:
        raise ValueError("outside the bounded development adapter domain")
    return value


def independently_derived_expectation(numbers: Any) -> dict:
    """Return a JSON-safe test expectation derived from the public prose.

    Not a hidden/reference benchmark solution. All computation happens in the
    trusted author's local test oracle; candidate source is never executed.
    """
    try:
        nums = _valid_numbers(numbers)
    except (TypeError, ValueError) as exc:
        return {"status": "exception", "error_type": type(exc).__name__}
    if not nums:  # explicit exception to the usual mathematical 0! permutation
        return {"status": "ok", "value": [[], []]}
    p = [list(row) for row in permutations(nums)]
    s = sum(factorial(x) for x in nums)
    return {"status": "ok", "value": [[s] * len(p), p]}


def proposed_cases() -> list[dict]:
    """Bounded, independently derived examples; pending human review."""
    rows = [
        ("empty", []),
        ("singleton_zero", [0]),
        ("singleton_four", [4]),
        ("two_distinct", [0, 4]),
        ("two_repeated", [2, 2]),
        ("three_distinct", [1, 2, 3]),
        ("three_with_repeats", [0, 0, 1]),
        ("four_distinct", [0, 1, 2, 3]),
        ("four_with_repeats", [1, 1, 2, 2]),
        ("non_list_tuple", (0, 4)),
        ("non_list_string", "0,4"),
        ("non_list_integer", 4),
        ("noninteger_string", [1, "2"]),
        ("noninteger_float", [1, 2.5]),
        ("noninteger_none", [None]),
        ("negative_single", [-1]),
        ("negative_mixed", [2, -1]),
    ]
    # JSON transport converts tuple args into arrays. To preserve a true tuple
    # argument for invalid-input testing, it requires an opt-in argument decoder
    # inside the trusted child runner. We deliberately omit that case for now.
    rows = [row for row in rows if row[0] != "non_list_tuple"]
    result = []
    for name, numbers in rows:
        result.append({"name": name, "args": [numbers],
                       "expected": independently_derived_expectation(numbers)})
    return result


def _integers_only(value: Any) -> bool:
    return type(value) is int


def _base_shape(actual: Any) -> tuple[bool, list, list, str]:
    if type(actual) is not list or len(actual) != 2:
        return False, [], [], "result_must_have_two_items"
    sums, perms = actual
    if type(sums) is not list or type(perms) is not list:
        return False, [], [], "results_must_be_lists"
    if not all(_integers_only(x) for x in sums):
        return False, [], [], "factorial_sums_must_be_ints"
    if not all(type(row) is list and all(_integers_only(x) for x in row)
               for row in perms):
        return False, [], [], "permutations_must_have_integer_elements"
    return True, sums, perms, ""


def _semantic_match(observed: dict, expected: dict) -> tuple[bool, str]:
    if expected["status"] == "exception":
        if observed.get("status") != "exception":
            return False, "expected_exception"
        if observed.get("error_type") != expected["error_type"]:
            return False, "incorrect_exception_type"
        return True, "passed"
    if observed.get("status") != "ok":
        return False, observed.get("status", "missing_status")
    ok, sums, perms, failure = _base_shape(observed.get("value"))
    if not ok:
        return False, failure
    expected_sums, expected_perms = expected["value"]
    if len(sums) != len(perms) or len(sums) != len(expected_sums):
        return False, "incorrect_result_count"
    # Check ordered (sum, permutation) associations without enforcing a
    # particular permutation enumeration order. A Counter preserves duplicates.
    actual_pairs = Counter((s, tuple(p)) for s, p in zip(sums, perms))
    desired_pairs = Counter((s, tuple(p)) for s, p in zip(expected_sums, expected_perms))
    if actual_pairs != desired_pairs:
        return False, "incorrect_pairs_or_multiplicity"
    return True, "passed"


def _strict_types(observed: dict, expected: dict) -> tuple[bool, str]:
    if expected["status"] != "ok":
        return True, "not_applicable"
    # Root and all nested Python types come from the trusted isolated child,
    # not from JSON alone or metadata supplied by generated candidate code.
    if observed.get("type") != "tuple":
        return False, "root_must_be_tuple"
    tree = observed.get("type_tree")
    if not isinstance(tree, dict) or tree.get("kind") != "tuple":
        return False, "nested_type_metadata_unavailable"
    items = tree.get("items")
    if not isinstance(items, list) or len(items) != 2:
        return False, "root_tuple_wrong_shape"
    sums, perms = items
    if sums.get("kind") != "list" or perms.get("kind") != "list":
        return False, "expected_two_lists"
    if (sums.get("truncated") or perms.get("truncated")
        or not isinstance(sums.get("items"), list)
        or not isinstance(perms.get("items"), list)
        or len(sums["items"]) != len(expected["value"][0])
        or len(perms["items"]) != len(expected["value"][1])):
        return False, "missing_or_truncated_type_metadata"
    for item in sums["items"]:
        if item.get("kind") != "int":
            return False, "sum_type_not_integer"
    for permutation in perms["items"]:
        if permutation.get("truncated") or not isinstance(permutation.get("items"), list):
            return False, "missing_or_truncated_permutation_types"
        if permutation.get("kind") != "tuple":
            return False, "permutations_must_be_tuples"
        if any(item.get("kind") != "int" for item in permutation.get("items", [])):
            return False, "permutation_element_not_integer"
    return True, "passed"


def compare(observed: dict, expected: dict) -> dict:
    """Evaluate semantic correctness separately from strict example typing.

    Does not claim equivalence with an official BigCodeBench grader.
    """
    semantic_ok, semantic_reason = _semantic_match(observed, expected)
    strict_ok, strict_reason = _strict_types(observed, expected)
    return {
        "semantic_pass": semantic_ok,
        "semantic_reason": semantic_reason,
        "strict_pass": bool(semantic_ok and strict_ok),
        "strict_reason": semantic_reason if not semantic_ok else strict_reason,
    }


def type_tree(value: Any, depth: int = 0) -> dict:
    """Trusted-runner-compatible type tree for OFFLINE comparator tests."""
    kind = type(value).__name__
    if depth >= 6:
        return {"kind": kind, "truncated": True}
    if type(value) in (list, tuple):
        return {"kind": kind, "items": [type_tree(x, depth + 1) for x in value[:128]],
                "length": len(value), "truncated": len(value) > 128}
    return {"kind": kind}


def conservative_source_review(code: str) -> list[str]:
    """Flag likely side effects before sandboxing. NOT a security boundary.

    Intentionally errs toward rejecting unusual, potentially legitimate code.
    A human reviewer and a hardened isolated runtime remain necessary.
    """
    import ast
    allow_imports = {
        "__future__", "math", "itertools", "functools", "collections",
        "operator", "typing", "copy",
    }
    blocked_calls = {"open", "exec", "eval", "compile", "input", "__import__"}
    blocked_attrs = {"__import__", "__subclasses__", "__globals__", "__builtins__"}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"invalid_syntax_line_{exc.lineno}"]
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in allow_imports:
                    errors.append(f"unreviewed_import:{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.level != 0 or (node.module or "").split(".")[0] not in allow_imports):
                errors.append(f"unreviewed_import_from:{node.module}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in blocked_calls:
                errors.append(f"blocked_call:{node.func.id}")
        elif isinstance(node, ast.Attribute) and node.attr in blocked_attrs:
            errors.append(f"blocked_attribute:{node.attr}")
    return sorted(set(errors))
