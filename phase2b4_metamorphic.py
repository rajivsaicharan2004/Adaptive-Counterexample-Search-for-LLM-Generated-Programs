#!/usr/bin/env python3
"""Phase 2B-4: reference-checked metamorphic DEVELOPMENT testing.

Supports HumanEval/0 (close elements) and HumanEval/1 (parentheses groups).
Reuses the existing Phase 2A Docker executor and Phase 2B-3 corpus reader.
No LLM calls; no candidate execution on the host; no held-out tests.

A metamorphic relation compares the behavior of one program on two related
inputs. Reference-oracle mismatches are also reported separately: satisfying a
metamorphic relation does NOT establish functional correctness.
"""

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from uuid import uuid4

import phase2a_validator as base
import phase2b3_differential as differential

ROOT = Path(__file__).resolve().parent
SUPPORTED = ("HumanEval/0", "HumanEval/1")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def sha256(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def execute(code, entry_point, argument_lists, batch_size):
    """Run every input inside the existing Docker sandbox, never on the host."""
    outcomes = []
    for batch in batches(argument_lists, batch_size):
        cases = [{"entry_point": entry_point, "args": args} for args in batch]
        outcomes.extend(base.docker_execute(code, cases))
    if len(outcomes) != len(argument_lists):
        raise RuntimeError("Docker returned the wrong number of execution outcomes")
    return outcomes


def split_groups(value):
    """Parse only valid, balanced, top-level groups, ignoring whitespace."""
    compact = value.replace(" ", "")
    result, depth, start = [], 0, None
    for index, ch in enumerate(compact):
        if ch == "(":
            if depth == 0:
                start = index
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                result.append(compact[start:index + 1])
        else:
            return None
    return result if depth == 0 and result else None


def add_spaces(text, rng):
    """Create whitespace variation without changing parentheses structure."""
    return (" " * rng.randint(0, 2) +
            "".join(ch + " " * rng.randint(0, 2) for ch in text) +
            " " * rng.randint(0, 2))


def transform_zero(args, operation, rng):
    values, threshold = args
    values = list(values)
    if operation == "reverse":
        updated = [list(reversed(values)), threshold]
        relation = "equal"
    elif operation == "rotate":
        updated = [values[1:] + values[:1], threshold]
        relation = "equal"
    elif operation == "reflect":
        updated = [[-value for value in values], threshold]
        relation = "equal"
    elif operation == "scale_two":
        updated = [[2 * value for value in values], 2 * threshold]
        relation = "equal"
    elif operation == "translate":
        # Quarter-grid values have exact binary floating-point representation.
        # Restrict this operator to avoid artificial boundary changes due to
        # adding an offset to arbitrary floating-point numbers.
        if any(abs(value * 4 - round(value * 4)) > 1e-9 for value in values):
            return None
        offset = rng.choice([-2.0, -1.0, 1.0, 2.0])
        updated = [[value + offset for value in values], threshold]
        relation = "equal"
    elif operation == "threshold_up":
        increase = rng.choice([0.25, 0.5, 1.0, 2.0])
        updated = [values, threshold + increase]
        # If a pair is close at threshold t, it must be close at t + increase.
        relation = "monotone_true"
    else:
        raise ValueError(f"Unknown HumanEval/0 transformation: {operation}")
    if (canonical(updated) == canonical(args)
            or not differential.valid_input("HumanEval/0", updated)):
        return None
    return updated, relation, {}


def transform_one(args, operation, rng):
    source = args[0]
    groups = split_groups(source)
    if not groups:
        return None
    if operation == "remove_spaces":
        updated, relation, meta = [source.replace(" ", "")], "equal", {}
    elif operation == "insert_spaces":
        updated, relation, meta = [add_spaces("".join(groups), rng)], "equal", {}
    elif operation == "append_group":
        group = rng.choice(["()", "(())", "(()())"])
        updated, relation, meta = [source + " " + group], "append", {"group": group}
    elif operation == "prepend_group":
        group = rng.choice(["()", "(())", "(()())"])
        updated, relation, meta = [group + " " + source], "prepend", {"group": group}
    elif operation == "reverse_groups":
        updated, relation, meta = ["".join(reversed(groups))], "reverse_list", {}
    elif operation == "wrap_first":
        updated = ["(" + groups[0] + ")" + "".join(groups[1:])]
        relation, meta = "wrap_first", {}
    else:
        raise ValueError(f"Unknown HumanEval/1 transformation: {operation}")
    if (canonical(updated) == canonical(args)
            or not differential.valid_input("HumanEval/1", updated)):
        return None
    return updated, relation, meta


def generate_pairs(task_id, cases, requested, seed):
    """Generate a reproducible, nearly balanced mix of distinct transformations."""
    operations = (["reverse", "rotate", "reflect", "scale_two", "translate", "threshold_up"]
                  if task_id == "HumanEval/0" else
                  ["remove_spaces", "insert_spaces", "append_group",
                   "prepend_group", "reverse_groups", "wrap_first"])
    rng = random.Random(seed)
    seen, pairs = set(), []
    attempts = 0
    while len(pairs) < requested and attempts < max(2000, 150 * requested):
        # Rotate operations across attempts, not successes, so an exhausted
        # operator cannot prevent reaching the requested pair count.
        operation = operations[attempts % len(operations)]
        case = rng.choice(cases)
        attempts += 1
        transform = (transform_zero if task_id == "HumanEval/0" else transform_one)
        outcome = transform(case["args"], operation, rng)
        if outcome is None:
            continue
        followup, relation, info = outcome
        marker = canonical([operation, case["args"], followup])
        if marker in seen:
            continue
        seen.add(marker)
        pairs.append({
            "name": f"mr_{len(pairs) + 1:04d}",
            "source_case": case["name"], "operation": operation,
            "relation": relation, "relation_info": info,
            "base_args": case["args"], "followup_args": followup,
        })
    if len(pairs) != requested:
        raise RuntimeError(f"Generated only {len(pairs)}/{requested} distinct valid pairs "
                           f"in {attempts} attempts; try fewer pairs or another corpus")
    return pairs, attempts


def index_inputs(pairs):
    """Deduplicate executions while keeping pair-to-input links."""
    inputs, indices = [], {}
    for pair in pairs:
        for key in ("base_args", "followup_args"):
            signature = canonical(pair[key])
            if signature not in indices:
                indices[signature] = len(inputs)
                inputs.append(pair[key])
            pair["base_index" if key == "base_args" else "followup_index"] = indices[signature]
    return inputs


def relation_holds(base_result, follow_result, relation, info):
    """Compare actual outputs; does not use trusted expected outputs."""
    if base_result.get("status") != "ok" or follow_result.get("status") != "ok":
        return None  # Execution failure, not a proven semantic MR violation.
    a, b = base_result.get("value"), follow_result.get("value")
    ta, tb = base_result.get("type"), follow_result.get("type")
    if relation == "equal":
        return ta == tb and type(a) is type(b) and a == b
    if relation == "monotone_true":
        return ta == tb == "bool" and type(a) is bool and type(b) is bool and (not a or b)
    if ta != "list" or tb != "list" or type(a) is not list or type(b) is not list:
        return False
    if relation == "append":
        return b == a + [info["group"]]
    if relation == "prepend":
        return b == [info["group"]] + a
    if relation == "reverse_list":
        return b == list(reversed(a))
    if relation == "wrap_first":
        return bool(a) and isinstance(a[0], str) and b == ["(" + a[0] + ")"] + a[1:]
    raise ValueError(f"Unknown metamorphic relation: {relation}")


def is_diagnostic(path):
    return differential.is_diagnostic(path)


def evaluate(path, entry_point, pairs, arguments, oracle, batch_size):
    result = {"candidate": str(path.relative_to(ROOT)), "diagnostic": is_diagnostic(path)}
    try:
        code = path.read_text(encoding="utf-8")
        result["code_sha256"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
        tree = ast.parse(code)
        functions = {node.name for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if entry_point not in functions:
            raise ValueError(f"Expected top-level function {entry_point!r} not found")
        observed = execute(code, entry_point, arguments, batch_size)
        checks = []
        for pair in pairs:
            i, j = pair["base_index"], pair["followup_index"]
            a, b = observed[i], observed[j]
            relation_pass = relation_holds(a, b, pair["relation"], pair["relation_info"])
            oracle_a = base.matching_result(a, oracle[i]["value"], oracle[i]["type"])
            oracle_b = base.matching_result(b, oracle[j]["value"], oracle[j]["type"])
            checks.append({
                "name": pair["name"], "operation": pair["operation"],
                "relation": pair["relation"],
                "base_args": pair["base_args"], "followup_args": pair["followup_args"],
                "base_observed": a, "followup_observed": b,
                "metamorphic_pass": relation_pass,
                "base_oracle_pass": oracle_a, "followup_oracle_pass": oracle_b,
                "reference_verified_candidate_failure": not (oracle_a and oracle_b),
            })
        violations = sum(t["metamorphic_pass"] is False for t in checks)
        nonexecutions = sum(t["metamorphic_pass"] is None for t in checks)
        confirmed = sum(t["reference_verified_candidate_failure"] for t in checks)
        result.update(status="evaluated", pair_count=len(checks),
                      metamorphic_violations=violations, execution_failures=nonexecutions,
                      reference_verified_failing_pairs=confirmed,
                      unique_inputs_executed=len(arguments), checks=checks)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        result.update(status="static_error", error=str(exc))
    except (RuntimeError, OSError) as exc:
        result.update(status="infrastructure_error", error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2B-4: Docker-isolated metamorphic development testing")
    parser.add_argument("--task-id", choices=SUPPORTED, required=True)
    parser.add_argument("--runs", nargs="+", required=True, help="Phase 1 candidate run folders")
    parser.add_argument("--inputs", help="Existing Phase 2B *_inputs.json under results/phase2b")
    parser.add_argument("--pairs", type=int, default=40, help="Number of metamorphic pairs (default 40)")
    parser.add_argument("--max-cases", type=int, default=500, help="Max source corpus cases")
    parser.add_argument("--batch-size", type=int, default=10, help="Docker inputs per invocation")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--include-diagnostics", action="store_true",
                        help="Opt in to synthetic deliberately faulty candidates")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview generated pairs without Docker or oracle access")
    args = parser.parse_args()
    if not 1 <= args.pairs <= 300:
        parser.error("--pairs must be between 1 and 300")
    if not 1 <= args.max_cases <= 500:
        parser.error("--max-cases must be between 1 and 500")
    if not 1 <= args.batch_size <= min(base.MAX_CASES, 20):
        parser.error(f"--batch-size must be between 1 and {min(base.MAX_CASES, 20)}")

    try:
        paths = base.candidate_files(args.runs, args.task_id)
        paths = [p for p in paths if args.include_diagnostics or not is_diagnostic(p)]
        if not paths:
            parser.error("No eligible candidate files (synthetic diagnostics require --include-diagnostics)")
        cases, source = differential.read_cases(args.task_id, args.inputs, args.max_cases)
        pairs, attempts = generate_pairs(args.task_id, cases, args.pairs, args.seed)
        arguments = index_inputs(pairs)
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    print(f"Task: {args.task_id}")
    print(f"Candidates: {len(paths)} (diagnostics opt-in: {args.include_diagnostics})")
    print(f"Source corpus: {source} ({len(cases)} cases)")
    print(f"Metamorphic pairs: {len(pairs)} | unique inputs to execute: {len(arguments)}")
    print(f"Seed: {args.seed} | batch size: {args.batch_size} | attempts: {attempts}")
    if args.dry_run:
        for pair in pairs[:8]:
            print(f" - {pair['name']} ({pair['operation']}): "
                  f"{pair['base_args']} -> {pair['followup_args']}")
        print("DRY RUN: no Docker containers, oracle, or generated code executed")
        return

    base.ensure_docker()
    reference, entry_point = base.load_reference(args.task_id)
    print(f"Running reference oracle on {len(arguments)} distinct development inputs...")
    oracle = execute(reference, entry_point, arguments, args.batch_size)
    for idx, output in enumerate(oracle):
        if output.get("status") != "ok":
            raise RuntimeError(f"Reference oracle failed for input #{idx}: {output}")
    # A metamorphic claim is not valid merely because a program agreed with it.
    # Validate each relation on the trusted reference BEFORE scoring candidates.
    for pair in pairs:
        actual_relation = relation_holds(oracle[pair["base_index"]],
                                        oracle[pair["followup_index"]],
                                        pair["relation"], pair["relation_info"])
        if actual_relation is not True:
            raise RuntimeError(
                f"Reference contradicts metamorphic relation {pair['name']} "
                f"({pair['operation']}). Review input contract / transformation; "
                "candidate scores have NOT been computed.")

    reports = []
    for path in paths:
        report = evaluate(path, entry_point, pairs, arguments, oracle, args.batch_size)
        reports.append(report)
        if report["status"] == "evaluated":
            print(f"{path.name:20s} MR violations: {report['metamorphic_violations']:2d} | "
                  f"oracle-confirmed failing pairs: {report['reference_verified_failing_pairs']:2d} | "
                  f"execution failures: {report['execution_failures']:2d}" +
                  (" [diagnostic]" if report["diagnostic"] else ""))
        else:
            print(f"{path.name:20s} {report['status']}: {report['error']}")

    dest = ROOT / "results" / "phase2b"
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    prefix = args.task_id.replace("/", "_").lower() + "_metamorphic_" + stamp
    corpus_file = dest / f"{prefix}_inputs.json"
    report_file = dest / f"{prefix}_report.json"
    corpus_file.write_text(json.dumps({
        "task_id": args.task_id, "suite": "metamorphic_development", "seed": args.seed,
        "source": source, "pair_count": len(pairs), "unique_inputs": len(arguments),
        "inputs_sha256": sha256(arguments), "pairs": pairs, "cases": [
            {"name": f"input_{i:04d}", "args": value} for i, value in enumerate(arguments, 1)],
    }, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    report_file.write_text(json.dumps({
        "task_id": args.task_id, "suite": "metamorphic_development",
        "official_or_held_out": False, "reference_oracle": "HumanEval canonical solution in Docker",
        "source": source, "seed": args.seed, "pair_count": len(pairs),
        "unique_input_count": len(arguments), "input_corpus_sha256": sha256(arguments),
        "docker_image": base.IMAGE, "case_timeout_seconds": base.CASE_TIMEOUT,
        "batch_size": args.batch_size, "candidate_count": len(paths),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_file": str(corpus_file.relative_to(ROOT)),
        "operation_counts": dict(Counter(pair["operation"] for pair in pairs)),
        "metamorphic_violations_total": sum(r.get("metamorphic_violations", 0) for r in reports),
        "reference_verified_failing_pairs_total": sum(
            r.get("reference_verified_failing_pairs", 0) for r in reports),
        "results": reports,
    }, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("\nSaved metamorphic input corpus:", corpus_file.relative_to(ROOT))
    print("Saved validation report:", report_file.relative_to(ROOT))
    print("These are DEVELOPMENT results, not official or held-out benchmark scores.")
    print("MR violations and oracle-confirmed failures are reported separately.")


if __name__ == "__main__":
    main()
