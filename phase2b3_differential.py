#!/usr/bin/env python3
"""Phase 2B-3: oracle-checked differential testing for HumanEval/0 and /1.

Compares saved Phase 1 candidates on identical DEVELOPMENT inputs using the
existing Phase 2A Docker sandbox. A disagreement is not automatically a bug:
the independent reference oracle labels candidate failures on each valid input.

No model calls; no official held-out tests; no generated code runs on the host.
"""

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import uuid4

import phase2a_validator as base

ROOT = Path(__file__).resolve().parent
SUPPORTED = ("HumanEval/0", "HumanEval/1")


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def sha256(data):
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def valid_input(task_id, args):
    """Conservative input contracts for the two existing pilot tasks only."""
    if task_id == "HumanEval/0":
        if not isinstance(args, list) or len(args) != 2:
            return False
        numbers, threshold = args
        return (isinstance(numbers, list) and len(numbers) <= 16
                and all(type(n) in (int, float) and math.isfinite(n) and abs(n) <= 300
                        for n in numbers)
                and type(threshold) in (int, float) and math.isfinite(threshold)
                and 0 <= threshold <= 300)
    if task_id == "HumanEval/1":
        if not isinstance(args, list) or len(args) != 1:
            return False
        value = args[0]
        if not isinstance(value, str) or not 0 < len(value) <= 240:
            return False
        if any(ch not in "() " for ch in value):
            return False
        depth = 0
        groups = 0
        for ch in value:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return False
                if depth == 0:
                    groups += 1
        return depth == 0 and 1 <= groups <= 12
    return False


def read_cases(task_id, input_file, max_cases):
    """Read reviewed cases or replay a Phase 2B input corpus as-is."""
    if input_file is None:
        raw = base.load_development_cases(task_id)
        source = "phase2a_reviewed_development"
    else:
        path = Path(input_file).expanduser().resolve()
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Input corpus is unavailable or unsafe: {path}")
        # Reuse only locally generated files under results/phase2b by default.
        allowed = (ROOT / "results" / "phase2b").resolve()
        if not path.is_relative_to(allowed):
            raise ValueError(f"Input corpus must be under {allowed}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("task_id") != task_id:
            raise ValueError("Input corpus task ID does not match --task-id")
        raw = payload.get("cases")
        source = str(path.relative_to(ROOT))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Input corpus must contain a nonempty 'cases' list")
    if len(raw) > max_cases:
        raise ValueError(f"Input corpus has {len(raw)} cases; increase --max-cases deliberately")
    cases = []
    seen = set()
    for i, row in enumerate(raw, 1):
        if not isinstance(row, dict) or not valid_input(task_id, row.get("args")):
            raise ValueError(f"Case #{i} violates the pilot input contract: {row!r}")
        args = row["args"]
        k = canonical(args)
        if k in seen:
            continue
        seen.add(k)
        # Recompute oracle outputs; never trust expected fields from an unreviewed corpus.
        new_case = {"name": str(row.get("name", f"case_{i:04d}")), "args": args}
        if input_file is None:
            new_case["expected"] = row["expected"]
            if "expected_type" in row:
                new_case["expected_type"] = row["expected_type"]
        cases.append(new_case)
    if not cases:
        raise ValueError("No unique valid cases were found")
    return cases, source


def batches(items, batch_size):
    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def execute(code, task_cases, batch_size):
    results = []
    for batch in batches(task_cases, batch_size):
        results.extend(base.docker_execute(code, batch))
    if len(results) != len(task_cases):
        raise RuntimeError("Docker returned an unexpected result count")
    return results


def is_diagnostic(path):
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return (meta.get("diagnostic_only") is True
            or meta.get("source") == "synthetic_fault_injection"
            or "diagnostic" in path.parent.name.lower())


def behavior(result):
    """A comparison key; non-success results also count as behavioral differences."""
    status = result.get("status", "unknown")
    if status == "ok":
        return canonical(["ok", result.get("type"), result.get("value")])
    if status == "exception":
        return canonical(["exception", result.get("error_type")])
    return canonical([status])


def evaluate(path, entry, task_cases, oracle, batch_size):
    report = {"candidate": str(path.relative_to(ROOT)),
              "diagnostic": is_diagnostic(path)}
    try:
        code = path.read_text(encoding="utf-8")
        report["code_sha256"] = sha256(code)
        tree = ast.parse(code)
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if entry not in defined:
            raise ValueError(f"Missing top-level function {entry!r}")
        observed = execute(code, task_cases, batch_size)
        checks = []
        for got, want in zip(observed, oracle):
            passed = base.matching_result(got, want["value"], want["type"])
            status = got.get("status")
            checks.append({"actual": got, "passed": passed,
                           "failure_type": None if passed else
                           ("wrong_answer" if status == "ok" else status or "unknown")})
        report.update(status="evaluated", passed=sum(t["passed"] for t in checks),
                      total=len(checks), checks=checks)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        report.update(status="static_error", error=str(exc))
    except (RuntimeError, OSError) as exc:
        report.update(status="infrastructure_error", error=str(exc))
    return report


def analyze(cases, oracle, reports):
    eligible = [r for r in reports if r["status"] == "evaluated"]
    disagreements = []
    for i, case in enumerate(cases):
        signatures = {}
        for report in eligible:
            observed = report["checks"][i]
            signatures[report["candidate"]] = behavior(observed["actual"])
        if len(set(signatures.values())) < 2:
            continue
        groups = {}
        for candidate, signature in signatures.items():
            groups.setdefault(signature, []).append(candidate)
        failed = [r["candidate"] for r in eligible if not r["checks"][i]["passed"]]
        statuses = [r["checks"][i]["actual"].get("status") for r in eligible]
        disagreement_type = ("output_disagreement" if all(s == "ok" for s in statuses)
                             else "execution_disagreement")
        disagreements.append({
            "case_name": case["name"], "args": case["args"],
            "oracle": oracle[i], "type": disagreement_type,
            "distinct_behaviors": len(groups), "behavior_groups": list(groups.values()),
            "reference_verified_failing_candidates": failed,
        })
    return disagreements


def main():
    parser = argparse.ArgumentParser(description=(
        "Phase 2B-3 differential testing with a reference oracle and existing Docker sandbox"))
    parser.add_argument("--task-id", choices=SUPPORTED, required=True)
    parser.add_argument("--runs", nargs="+", required=True, help="Existing Phase 1 run folders")
    parser.add_argument("--inputs", type=str,
                        help="Optional Phase 2B *_inputs.json corpus under results/phase2b")
    parser.add_argument("--max-cases", type=int, default=100,
                        help="Max distinct inputs accepted (default 100)")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Inputs per Docker invocation (default 10)")
    parser.add_argument("--include-diagnostics", action="store_true",
                        help="Explicitly include artificial faulty programs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show inputs and candidate files; do not start Docker")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= min(base.MAX_CASES, 30):
        parser.error(f"--batch-size must be between 1 and {min(base.MAX_CASES,30)}")
    if not 1 <= args.max_cases <= 500:
        parser.error("--max-cases must be between 1 and 500")
    try:
        files = base.candidate_files(args.runs, args.task_id)
        if not args.include_diagnostics:
            files = [p for p in files if not is_diagnostic(p)]
        if len(files) < 2:
            parser.error("Differential testing requires at least two eligible candidates")
        cases, source = read_cases(args.task_id, args.inputs, args.max_cases)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Task: {args.task_id}")
    print(f"Candidates: {len(files)} (diagnostics opt-in: {args.include_diagnostics})")
    print(f"Input source: {source} | Unique inputs: {len(cases)}")
    if args.dry_run:
        for p in files:
            print(" -", p.relative_to(ROOT))
        print("DRY RUN: no Docker or reference execution")
        return
    base.ensure_docker()
    reference, entry = base.load_reference(args.task_id)
    prepared = [{"entry_point": entry, "args": c["args"]} for c in cases]
    print(f"Running independent reference oracle on {len(cases)} development inputs...")
    oracle = execute(reference, prepared, args.batch_size)
    for case, result in zip(cases, oracle):
        if result.get("status") != "ok":
            raise RuntimeError(f"Oracle did not return a value for {case['name']}: {result}")
        if "expected" in case:
            expected_type = case.get("expected_type", type(case["expected"]).__name__)
            if not base.matching_result(result, case["expected"], expected_type):
                raise RuntimeError(f"Oracle disagrees with reviewed case {case['name']}: {result}")
    results = []
    for p in files:
        r = evaluate(p, entry, prepared, oracle, args.batch_size)
        results.append(r)
        suffix = (f"{r['passed']}/{r['total']} passed" if r["status"] == "evaluated"
                  else f"{r['status']}: {r['error']}")
        print(f"{p.name:20s} {suffix}" + (" [diagnostic]" if r["diagnostic"] else ""))
    disagreements = analyze(cases, oracle, results)
    failures = sum(r["total"] - r["passed"] for r in results if r["status"] == "evaluated")
    print(f"\nDiffering inputs: {len(disagreements)}/{len(cases)}")
    print(f"Reference-verified candidate-test failures: {failures}")
    for d in disagreements[:5]:
        print(f" - {d['case_name']}: {d['type']} (failing candidates: "
              f"{len(d['reference_verified_failing_candidates'])})")
    output = ROOT / "results" / "phase2b"
    output.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    destination = output / f"{args.task_id.replace('/','_').lower()}_differential_{tag}_report.json"
    destination.write_text(json.dumps({
        "task_id": args.task_id,
        "suite": "differential_development", "official_or_held_out": False,
        "input_source": source, "input_corpus_sha256": sha256(canonical(cases)),
        "docker_image": base.IMAGE,
        "case_timeout_seconds": base.CASE_TIMEOUT,
        "batch_size": args.batch_size,
        "case_count": len(cases), "candidate_count": len(files),
        "evaluated_count": sum(r["status"] == "evaluated" for r in results),
        "disagreement_case_count": len(disagreements),
        "reference_verified_candidate_test_failures": failures,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "cases": cases, "oracle_outputs": oracle,
        "disagreements": disagreements, "results": results,
    }, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("Saved report:", destination.relative_to(ROOT))
    print("Development evidence only; no held-out benchmark tests were used.")


if __name__ == "__main__":
    main()
