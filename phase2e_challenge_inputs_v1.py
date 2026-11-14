#!/usr/bin/env python3
"""Freeze independent development challenge inputs for HumanEval/0 and /1.

This program does NOT execute generated code, call an oracle, start Docker, or
access official/held-out tests. The Phase 2D quarantine policy is checked first.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from phase2d_quarantine_guard import require_task_permission

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "results" / "phase2e" / "challenge_inputs_v1.json"
SEEDS = {"HumanEval/0": 202611130, "HumanEval/1": 202611131}
CASES_PER_TASK = 128


def add_unique(bucket: dict[str, list], args: list) -> None:
    key = json.dumps(args, sort_keys=True, separators=(",", ":"), allow_nan=False)
    bucket.setdefault(key, args)


def close_elements_cases() -> list[dict]:
    """Nonnegative thresholds, varied list sizes, duplicates and near-boundaries."""
    rng = random.Random(SEEDS["HumanEval/0"])
    unique: dict[str, list] = {}
    examples = [
        ([], 0), ([], 0.5), ([0], 0), ([0], 0.5),
        ([0, 0], 0), ([0, 0], 0.25), ([1, 1.5], 0.5),
        ([1, 1.5], 0.75), ([-1, -1.5], 0.5),
        ([-1, -1.5], 0.75), ([0, 0.25, 0.5], 0.25),
        ([0, 0.25, 0.5], 0.5), ([2, -2, 2], 0.01),
        ([0, 5, 10], 5), ([0, 5, 10], 5.25),
        ([-10, -9.75, 10], 0.25),
    ]
    for nums, threshold in examples:
        add_unique(unique, [[float(x) for x in nums], float(threshold)])

    # Deliberate equality and just-below/above threshold boundaries.
    for threshold in [0, 0.25, 0.5, 1, 1.5, 2, 4]:
        for difference in [0, max(0, threshold - 0.25), threshold,
                           threshold + 0.25]:
            for shift in [-5, 0, 5]:
                add_unique(unique, [[float(shift), float(shift + difference)],
                                    float(threshold)])
                if len(unique) >= 56:
                    break
            if len(unique) >= 56:
                break
        if len(unique) >= 56:
            break

    grid = [i / 4 for i in range(-40, 41)]
    trials = 0
    while len(unique) < CASES_PER_TASK and trials < 20000:
        trials += 1
        n = rng.randint(0, 12)
        nums = [rng.choice(grid) for _ in range(n)]
        if n >= 2 and rng.random() < 0.35:
            nums[rng.randrange(n)] = nums[0]
        if rng.random() < 0.25:
            nums.sort(reverse=bool(rng.randrange(2)))
        threshold = rng.choice([0, 0.125, 0.25, 0.5, 0.75, 1, 1.5, 2, 4, 8])
        add_unique(unique, [nums, float(threshold)])

    if len(unique) < CASES_PER_TASK:
        raise RuntimeError("Could not create enough unique HumanEval/0 cases")
    return [{"name": f"challenge_he0_{i:03d}", "args": args,
             "expected_type": "bool"}
            for i, args in enumerate(list(unique.values())[:CASES_PER_TASK], 1)]


def paren_group(rng: random.Random, depth: int) -> str:
    if depth <= 1:
        return "()"
    children = "".join(paren_group(rng, depth - 1)
                       for _ in range(rng.randint(0, 3)))
    return "(" + children + ")"


def is_valid_parenthesized_groups(s: str) -> bool:
    groups = s.split()
    if not groups:
        return False
    for group in groups:
        depth = 0
        for ch in group:
            if ch not in "()":
                return False
            depth += 1 if ch == "(" else -1
            if depth < 0:
                return False
        if depth != 0 or not group.startswith("("):
            return False
    return True


def separate_paren_cases() -> list[dict]:
    """Valid, space-separated balanced parenthesis groups of varying depth."""
    rng = random.Random(SEEDS["HumanEval/1"])
    unique: dict[str, list] = {}
    examples = [
        "()", "(())", "((()))", "() ()", "()  ()", "(()()) ((()))",
        "((())()()) (()) ()", "(()) () (())", "(()(())) ((()))",
        "() () () () ()", "(((())))", "(()()) (()()) (()())",
    ]
    for s in examples:
        assert is_valid_parenthesized_groups(s)
        add_unique(unique, [s])

    trials = 0
    while len(unique) < CASES_PER_TASK and trials < 20000:
        trials += 1
        count = rng.randint(1, 7)
        groups = [paren_group(rng, rng.randint(1, 5)) for _ in range(count)]
        separators = [" " * rng.randint(1, 3) for _ in range(count - 1)]
        value = "".join(g + (separators[i] if i < count - 1 else "")
                        for i, g in enumerate(groups))
        if not is_valid_parenthesized_groups(value):
            raise RuntimeError("Generated invalid parenthesis input")
        add_unique(unique, [value])

    if len(unique) < CASES_PER_TASK:
        raise RuntimeError("Could not create enough unique HumanEval/1 cases")
    return [{"name": f"challenge_he1_{i:03d}", "args": args,
             "expected_type": "list"}
            for i, args in enumerate(list(unique.values())[:CASES_PER_TASK], 1)]


def main() -> None:
    for task_id in SEEDS:
        # Fail closed if the reviewed partition/quarantine changes.
        print(require_task_permission(ROOT, task_id, "evaluate"))

    suite = {
        "protocol": "phase2e_challenge_inputs_v1",
        "status": "development_inputs_frozen_before_candidate_execution",
        "official_or_held_out": False,
        "purpose": "Diagnostic test adequacy; not an independent generalization score",
        "cases_per_task": CASES_PER_TASK,
        "random_seeds": SEEDS,
        "expected_values_included": False,
        "generation_note": "Inputs generated from hand-authored task-specific rules without observing candidate outputs.",
        "tasks": {
            "HumanEval/0": {
                "entry_point": "has_close_elements",
                "cases": close_elements_cases(),
            },
            "HumanEval/1": {
                "entry_point": "separate_paren_groups",
                "cases": separate_paren_cases(),
            },
        },
    }
    for task_id, item in suite["tasks"].items():
        print(f"{task_id}: {len(item['cases'])} unique development inputs")
    payload = (json.dumps(suite, indent=2, sort_keys=True,
                          ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("xb") as output_file:
        output_file.write(payload)
    print("FROZEN INPUT SUITE:", OUTPUT.relative_to(ROOT))
    print("SHA256:", hashlib.sha256(payload).hexdigest())
    print("No candidate/reference code executed; no Docker or model calls.")


if __name__ == "__main__":
    main()
