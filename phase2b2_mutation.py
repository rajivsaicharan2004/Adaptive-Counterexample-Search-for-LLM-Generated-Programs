#!/usr/bin/env python3
"""Phase 2B-2: deterministic, specification-aware input mutation.

Mutate reviewed HumanEval/0 or HumanEval/1 DEVELOPMENT inputs, obtain expected
answers from the independent Phase 2A Docker reference oracle, and compare
saved Phase 1 candidates against exactly the same mutated corpus.

This is reference-validated mutation, not coverage-guided fuzzing or held-out
benchmark evaluation. It never calls an LLM or accesses official test cases.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from uuid import uuid4

import phase2a_validator as phase2a

ROOT = Path(__file__).resolve().parent
SUPPORTED_TASKS = ("HumanEval/0", "HumanEval/1")


def signature(args):
    return json.dumps(args, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(data):
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def valid_numbers(args):
    if not isinstance(args, list) or len(args) != 2:
        return False
    values, threshold = args
    return (isinstance(values, list) and len(values) <= 16
            and all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 300 for x in values)
            and type(threshold) in (int, float) and math.isfinite(threshold)
            and 0 <= threshold <= 300)


def groups_of(text):
    """Parse only balanced top-level parentheses groups; reject other characters."""
    if not isinstance(text, str) or any(c not in "() " for c in text):
        return None
    s = text.replace(" ", "")
    if not s:
        return None  # Avoid underspecified empty-input behavior in this pilot.
    depth, start, groups = 0, None, []
    for i, ch in enumerate(s):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        else:
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                groups.append(s[start:i + 1])
    return groups if depth == 0 else None


def valid_parens(args):
    if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
        return False
    s = args[0]
    return (len(s) <= 240 and groups_of(s) is not None
            and len(groups_of(s)) <= 12)


def mutate_numbers(args, rng):
    xs, t = args
    xs, t = list(xs), float(t)
    ops = ["shuffle", "duplicate", "remove", "add", "perturb",
           "translate", "scale", "threshold_edge", "threshold_random", "pair_edge"]
    op = rng.choice(ops)
    delta = rng.choice([-3.0, -1.0, -0.25, -0.01, 0.01, 0.25, 1.0, 3.0])
    if op == "shuffle" and len(xs) > 1:
        rng.shuffle(xs)
    elif op == "duplicate" and xs and len(xs) < 16:
        xs.insert(rng.randrange(len(xs) + 1), rng.choice(xs))
    elif op == "remove" and xs:
        del xs[rng.randrange(len(xs))]
    elif op == "add" and len(xs) < 16:
        xs.insert(rng.randrange(len(xs) + 1), rng.choice(xs) if xs and rng.random() < 0.4
                  else rng.randint(-40, 40) / rng.choice([1, 2, 4, 10]))
    elif op == "perturb" and xs:
        i = rng.randrange(len(xs))
        xs[i] = xs[i] + delta
    elif op == "translate" and xs:
        xs = [v + delta for v in xs]
    elif op == "scale" and xs:
        factor = rng.choice([-2.0, -1.0, 0.5, 2.0])
        xs = [v * factor for v in xs]
        # If scaling by a positive factor, optionally scale threshold too.
        if factor > 0 and rng.random() < 0.5:
            t *= factor
    elif op == "threshold_edge" and len(xs) > 1:
        a, b = rng.sample(xs, 2)
        t = max(0.0, abs(a - b) + rng.choice([-0.01, 0.0, 0.01]))
    elif op == "threshold_random":
        t = rng.choice([0.0, 0.001, 0.01, 0.1, 0.25, 0.5, 1.0, 2.0, 10.0])
    elif op == "pair_edge" and len(xs) > 1:
        i, j = rng.sample(range(len(xs)), 2)
        xs[j] = xs[i] + t + rng.choice([-0.01, 0.0, 0.01])
    else:
        return None
    new_args = [[round(float(v), 8) for v in xs], round(float(t), 8)]
    return (new_args, op) if valid_numbers(new_args) else None


def random_group(rng, depth=0):
    if depth >= 3 or rng.random() < 0.45:
        return "()"
    return "(" + "".join(random_group(rng, depth + 1)
                         for _ in range(rng.randint(1, 2))) + ")"


def add_spaces(s, rng):
    return (" " * rng.randint(0, 2)
            + "".join(ch + " " * rng.randint(0, 2) for ch in s)
            + " " * rng.randint(0, 2))


def mutate_parens(args, rng):
    source = args[0]
    groups = groups_of(source)
    if groups is None:
        return None
    op = rng.choice(["insert_spaces", "compact", "reorder", "duplicate_group",
                     "add_simple_group", "add_nested_group", "wrap_group",
                     "remove_group", "replace_group", "reverse_groups"])
    result = None
    if op == "insert_spaces":
        result = add_spaces("".join(groups), rng)
    elif op == "compact":
        result = "".join(groups)
    elif op == "reorder" and len(groups) >= 2:
        rng.shuffle(groups)
        result = "".join(groups)
    elif op == "duplicate_group" and len(groups) < 12:
        groups.insert(rng.randrange(len(groups) + 1), rng.choice(groups))
        result = "".join(groups)
    elif op == "add_simple_group" and len(groups) < 12:
        groups.insert(rng.randrange(len(groups) + 1), "()")
        result = "".join(groups)
    elif op == "add_nested_group" and len(groups) < 12:
        groups.insert(rng.randrange(len(groups) + 1), random_group(rng))
        result = "".join(groups)
    elif op == "wrap_group":
        i = rng.randrange(len(groups))
        groups[i] = "(" + groups[i] + ")"
        result = "".join(groups)
    elif op == "remove_group" and len(groups) > 1:
        del groups[rng.randrange(len(groups))]
        result = "".join(groups)
    elif op == "replace_group":
        groups[rng.randrange(len(groups))] = random_group(rng)
        result = "".join(groups)
    elif op == "reverse_groups" and len(groups) > 1:
        result = "".join(reversed(groups))
    if result is None:
        return None
    if op not in ("compact", "insert_spaces") and rng.random() < 0.55:
        result = add_spaces(result, rng)
    new_args = [result]
    return (new_args, op) if valid_parens(new_args) else None


def build_corpus(task_id, seeds, requested, random_seed):
    rng = random.Random(random_seed)
    validate = valid_numbers if task_id == "HumanEval/0" else valid_parens
    mutate = mutate_numbers if task_id == "HumanEval/0" else mutate_parens
    for s in seeds:
        if not validate(s["args"]):
            raise ValueError(f"Reviewed seed {s['name']!r} violates input contract")
    seen = {signature(seed["args"]) for seed in seeds}
    corpus = []
    attempts = 0
    while len(corpus) < requested and attempts < max(1000, requested * 100):
        attempts += 1
        seed = rng.choice(seeds)
        result = mutate(seed["args"], rng)
        if result is None:
            continue
        args, op = result
        key = signature(args)
        if key in seen:
            continue
        seen.add(key)
        corpus.append({"name": f"mutation_{len(corpus) + 1:04d}",
                       "args": args, "parent": seed["name"], "operator": op})
    if len(corpus) != requested:
        raise RuntimeError(f"Generated {len(corpus)} unique valid mutants after {attempts} attempts; "
                           f"requested {requested}. Try fewer mutants.")
    return corpus, attempts


def in_batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def execute_batchwise(code, cases, batch_size):
    results = []
    for batch in in_batches(cases, batch_size):
        results.extend(phase2a.docker_execute(code, batch))
    if len(results) != len(cases):
        raise RuntimeError("Sandbox did not return one result per case")
    return results


def candidate_is_diagnostic(path):
    # Diagnostics must be explicitly opted into, and are marked in reports.
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return (meta.get("diagnostic_only") is True
            or meta.get("source") == "synthetic_fault_injection"
            or "diagnostic" in path.parent.name.lower())


def evaluate(path, task_id, entry_point, corpus, expected, expected_types, batch_size):
    summary = {"candidate": str(path.relative_to(ROOT)), "task_id": task_id,
               "diagnostic": candidate_is_diagnostic(path)}
    try:
        code = path.read_text(encoding="utf-8")
        summary["code_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
        # Phase 2A performs AST parsing, entry-point checking, and source-size checks.
        import ast
        tree = ast.parse(code)
        defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if entry_point not in defined:
            raise ValueError(f"Missing required top-level function {entry_point!r}")
        cases = [{"entry_point": entry_point, "args": case["args"]} for case in corpus]
        observed = execute_batchwise(code, cases, batch_size)
        tests = []
        for case, want, expected_type, got in zip(corpus, expected, expected_types, observed):
            ok = phase2a.matching_result(got, want, expected_type)
            fail = None if ok else ("wrong_answer" if got.get("status") == "ok"
                                    else got.get("status", "unknown"))
            tests.append({"name": case["name"], "args": case["args"],
                          "parent": case["parent"], "operator": case["operator"],
                          "expected": want, "actual": got, "passed": ok,
                          "failure_type": fail})
        summary.update(status="evaluated", passed=sum(x["passed"] for x in tests),
                       total=len(tests), all_passed=all(x["passed"] for x in tests),
                       failure_types=dict(Counter(x["failure_type"] for x in tests if not x["passed"])),
                       tests=tests)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        summary.update(status="static_error", error=str(exc))
    except (RuntimeError, OSError) as exc:
        summary.update(status="infrastructure_error", error=str(exc))
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2B-2: mutate reviewed valid inputs and label with the Phase 2A Docker reference oracle."
    )
    parser.add_argument("--task-id", choices=SUPPORTED_TASKS, required=True)
    parser.add_argument("--runs", nargs="+", required=True, help="Existing Phase 1 candidate folders")
    parser.add_argument("--mutations", type=int, default=40, help="Number of unique new inputs (default 40)")
    parser.add_argument("--batch-size", type=int, default=10, help="Tests per Docker invocation (max 30)")
    parser.add_argument("--seed", type=int, default=2026, help="Deterministic input-generation seed")
    parser.add_argument("--include-diagnostics", action="store_true",
                        help="Explicitly allow synthetic fault-injection candidates")
    parser.add_argument("--dry-run", action="store_true",
                        help="Generate and list inputs but do not load private reference or run Docker")
    args = parser.parse_args()
    if not 1 <= args.mutations <= 500:
        parser.error("--mutations must be between 1 and 500")
    if not 1 <= args.batch_size <= min(phase2a.MAX_CASES, 30):
        parser.error(f"--batch-size must be between 1 and {min(phase2a.MAX_CASES, 30)}")

    try:
        paths = phase2a.candidate_files(args.runs, args.task_id)
        files = [p for p in paths if args.include_diagnostics or not candidate_is_diagnostic(p)]
        if not files:
            parser.error("No eligible candidates; use --include-diagnostics only for synthetic diagnostics")
        reviewed = phase2a.load_development_cases(args.task_id)
        corpus, attempts = build_corpus(args.task_id, reviewed, args.mutations, args.seed)
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Task: {args.task_id}")
    print(f"Candidates: {len(files)} (synthetic diagnostics opt-in: {args.include_diagnostics})")
    print(f"Reviewed seed inputs: {len(reviewed)}")
    print(f"Unique mutated development inputs: {len(corpus)} (attempts: {attempts})")
    print(f"Seed: {args.seed} | Docker batch size: {args.batch_size}")
    if args.dry_run:
        for c in corpus[:8]:
            print(f"  {c['name']}: {c['operator']} from {c['parent']}: {c['args']}")
        print("DRY RUN: no Docker, reference solution, or candidate execution")
        return

    phase2a.ensure_docker()
    reference, entry = phase2a.load_reference(args.task_id)
    # First check source cases against their independently reviewed expected outputs.
    print(f"Checking {len(reviewed)} reviewed seed inputs against reference oracle...")
    source_cases = [{"entry_point": entry, "args": c["args"]} for c in reviewed]
    source_out = execute_batchwise(reference, source_cases, args.batch_size)
    for seed_case, output in zip(reviewed, source_out):
        expected_type = seed_case.get("expected_type", type(seed_case["expected"]).__name__)
        if not phase2a.matching_result(output, seed_case["expected"], expected_type):
            raise RuntimeError(f"Reference disagreed with reviewed seed {seed_case['name']}: {output}")
    # Label the new inputs by reference execution. Candidate never sees the reference code.
    print(f"Labeling {len(corpus)} mutated inputs using the Docker reference oracle...")
    case_payload = [{"entry_point": entry, "args": c["args"]} for c in corpus]
    oracle = execute_batchwise(reference, case_payload, args.batch_size)
    for i, r in enumerate(oracle):
        if r.get("status") != "ok":
            raise RuntimeError(f"Reference could not label mutation {corpus[i]['name']}: {r}")
        if r.get("type") not in ("bool", "list"):
            raise RuntimeError(f"Unexpected reference output type for mutation {corpus[i]['name']}: {r}")
    expected = [r["value"] for r in oracle]
    expected_types = [r["type"] for r in oracle]
    reports = []
    for path in files:
        result = evaluate(path, args.task_id, entry, corpus, expected, expected_types, args.batch_size)
        reports.append(result)
        if result["status"] == "evaluated":
            print(f"{path.name:20} {result['passed']:3}/{result['total']} passed | "
                  f"failures: {result['total'] - result['passed']}")
        else:
            print(f"{path.name:20} {result['status']}: {result['error']}")

    output_dir = ROOT / "results" / "phase2b"
    output_dir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    prefix = f"{args.task_id.replace('/', '_').lower()}_mutation_{tag}"
    corpus_file = output_dir / f"{prefix}_inputs.json"
    report_file = output_dir / f"{prefix}_report.json"
    inputs = {"task_id": args.task_id, "suite": "reference_validated_mutation_development",
              "random_seed": args.seed, "requested_mutations": args.mutations,
              "generation_attempts": attempts, "reviewed_seed_cases": len(reviewed),
              "inputs_sha256": digest(corpus), "cases": corpus}
    report = {"task_id": args.task_id, "suite": "reference_validated_mutation_development",
              "official_or_held_out": False,
              "oracle": "HumanEval canonical solution in isolated Docker",
              "method": "specification_aware_mutation", "random_seed": args.seed,
              "input_corpus_sha256": inputs["inputs_sha256"],
              "docker_image": phase2a.IMAGE, "case_timeout_seconds": phase2a.CASE_TIMEOUT,
              "batch_size": args.batch_size, "candidate_count": len(files),
              "mutated_case_count": len(corpus),
              "created_utc": datetime.now(timezone.utc).isoformat(), "results": reports}
    corpus_file.write_text(json.dumps(inputs, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print("\nSaved input corpus:", corpus_file.relative_to(ROOT))
    print("Saved validation report:", report_file.relative_to(ROOT))
    print("DEVELOPMENT results only; do not use these as official or held-out scores.")


if __name__ == "__main__":
    main()
