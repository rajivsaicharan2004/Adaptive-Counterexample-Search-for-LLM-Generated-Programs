#!/usr/bin/env python3
"""Phase 2E.4: frozen DEVELOPMENT challenge, oracle and real-program evaluation.

Place in the project root beside phase2e_smoke_v1.py, phase2a_validator.py,
and phase2d_quarantine_guard.py. Default is read-only preflight.

--oracle-only: verify reviewed development reference cases and execute the
  reference on frozen challenge inputs IN DOCKER; no candidate execution.
--run: repeat oracle checks, then evaluate only registered unique candidates
  IN DOCKER, storing complete diagnostics and incremental checkpoints.

This is a development diagnostic, not an independent or held-out score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import phase2e_smoke_v1 as smoke

ROOT = Path(__file__).resolve().parent
CHALLENGE_REL = Path("results/phase2e/challenge_inputs_v1.json")
CHALLENGE_SHA256 = "b4ad3356981184d91bf0eb9c19b5b9529ebd631faffacc7959c61bc59072b4b3"
BATCH_SIZE = 16  # Separate from Phase 2A's reviewed-test MAX_CASES=30.
OUTPUT_DIR = ROOT / "results" / "phase2e"
TASKS = tuple(smoke.TASKS)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True,
                       indent=2, allow_nan=False) + "\n").encode("utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_permission(task_id: str) -> None:
    # Re-check at the actual execution boundary, not only during preflight.
    smoke.require_task_permission(ROOT, task_id, "evaluate")


def load_frozen_suite() -> dict[str, list[dict]]:
    path = ROOT / CHALLENGE_REL
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Frozen challenge file is missing or is a symlink")
    raw = path.read_bytes()
    if sha256(raw) != CHALLENGE_SHA256:
        raise RuntimeError("CHALLENGE HASH CHANGED: do not update the pinned hash")
    doc = json.loads(raw)
    if (not isinstance(doc, dict)
            or doc.get("protocol") != "phase2e_challenge_inputs_v1"
            or doc.get("status") != "development_inputs_frozen_before_candidate_execution"
            or doc.get("official_or_held_out") is not False
            or doc.get("expected_values_included") is not False
            or doc.get("cases_per_task") != 128
            or set(doc.get("tasks", {})) != set(TASKS)):
        raise RuntimeError("Unexpected frozen challenge manifest")

    cases_by_task = {}
    all_names = set()
    for task_id in TASKS:
        entry = smoke.TASKS[task_id][0]
        item = doc["tasks"][task_id]
        if not isinstance(item, dict) or item.get("entry_point") != entry:
            raise RuntimeError(f"Challenge entry-point mismatch: {task_id}")
        cases = item.get("cases")
        if not isinstance(cases, list) or len(cases) != 128:
            raise RuntimeError(f"Challenge should have 128 cases: {task_id}")
        distinct_inputs = set()
        for i, case in enumerate(cases, 1):
            prefix = "challenge_he0" if task_id == "HumanEval/0" else "challenge_he1"
            name = f"{prefix}_{i:03d}"
            if (not isinstance(case, dict)
                    or set(case) != {"name", "args", "expected_type"}
                    or case.get("name") != name or name in all_names
                    or not isinstance(case.get("args"), list)):
                raise RuntimeError(f"Malformed/future-modified challenge case: {task_id} / {name}")
            all_names.add(name)
            args = case["args"]
            if task_id == "HumanEval/0":
                if (case["expected_type"] != "bool" or len(args) != 2
                        or not isinstance(args[0], list)
                        or not 0 <= len(args[0]) <= 12
                        or not all(type(n) in (int, float) and -100 <= n <= 100
                                   for n in args[0])
                        or type(args[1]) not in (int, float)
                        or not 0 <= args[1] <= 8):
                    raise RuntimeError(f"Malformed HumanEval/0 input: {name}")
            else:
                if (case["expected_type"] != "list" or len(args) != 1
                        or not isinstance(args[0], str)
                        or not 1 <= len(args[0]) <= 20000
                        or any(c not in "() " for c in args[0])):
                    raise RuntimeError(f"Malformed HumanEval/1 input: {name}")
                # Challenge V1 accepts only whitespace-separated balanced groups.
                for g in args[0].split():
                    depth = 0
                    for c in g:
                        depth += 1 if c == "(" else -1
                        if depth < 0:
                            raise RuntimeError(f"Unbalanced challenge input: {name}")
                    if depth != 0:
                        raise RuntimeError(f"Unbalanced challenge input: {name}")
            key = json.dumps(args, separators=(",", ":"), sort_keys=True,
                             allow_nan=False)
            if key in distinct_inputs:
                raise RuntimeError(f"Duplicate input in frozen challenge: {task_id}")
            distinct_inputs.add(key)
        cases_by_task[task_id] = cases
    return cases_by_task


def chunks(items: list, n: int = BATCH_SIZE):
    for offset in range(0, len(items), n):
        yield offset, items[offset:offset + n]


def oracle_for_task(task_id: str, cases: list[dict]):
    """Verify reviewed reference cases, then label all frozen challenge inputs."""
    require_permission(task_id)
    entry = smoke.TASKS[task_id][0]
    reviewed = smoke.validator.load_development_cases(task_id)
    if not isinstance(reviewed, list) or not reviewed:
        raise RuntimeError(f"Missing reviewed development self-check: {task_id}")
    reference_code, reference_entry = smoke.validator.load_reference(task_id)
    if reference_entry != entry:
        raise RuntimeError(f"Reference entry-point mismatch: {task_id}")

    reviewed_requests = [{"entry_point": entry, "args": case["args"]}
                         for case in reviewed]
    t0 = time.perf_counter()
    reviewed_outputs = smoke.validator.docker_execute(reference_code, reviewed_requests)
    reviewed_wall = time.perf_counter() - t0
    for case, response in zip(reviewed, reviewed_outputs):
        if (not isinstance(response, dict)
                or not smoke.validator.matching_result(
                    response, case["expected"],
                    case.get("expected_type", type(case["expected"]).__name__))):
            raise RuntimeError(
                f"Reference disagrees with reviewed development case: {task_id}/{case['name']}")

    outputs = []
    chunk_wall = []
    for offset, subset in chunks(cases):
        require_permission(task_id)
        requests = [{"entry_point": entry, "args": case["args"]}
                    for case in subset]
        t0 = time.perf_counter()
        responses = smoke.validator.docker_execute(reference_code, requests)
        duration = time.perf_counter() - t0
        for case, response in zip(subset, responses):
            if not isinstance(response, dict) or response.get("status") != "ok":
                raise RuntimeError(
                    f"Reference failed on frozen challenge: {task_id}/{case['name']}")
            actual_type = type(response.get("value")).__name__
            if (response.get("type") != case["expected_type"]
                    or actual_type != case["expected_type"]):
                raise RuntimeError(
                    f"Reference output type mismatch: {task_id}/{case['name']}")
        outputs.extend(r["value"] for r in responses)
        chunk_wall.append(round(duration, 6))
    if len(outputs) != len(cases):
        raise RuntimeError(f"Oracle output count mismatch: {task_id}")

    evidence = [{"name": c["name"], "args": c["args"],
                 "expected": value, "expected_type": c["expected_type"]}
                for c, value in zip(cases, outputs)]
    return {
        "reference_code_sha256": sha256(reference_code.encode("utf-8")),
        "reviewed_self_check_count": len(reviewed),
        "reviewed_self_check_status": "passed",
        "reviewed_reference_wall_seconds": round(reviewed_wall, 6),
        "challenge_cases": len(cases),
        "challenge_reference_chunk_wall_seconds": chunk_wall,
        "challenge_reference_batches": len(chunk_wall),
        "challenge_reference_calls": len(cases),
        "oracle_evidence_sha256": sha256(json_bytes(evidence)),
        "oracle_evidence": evidence,
    }


def evaluate_candidate(task_id: str, candidate: dict,
                       cases: list[dict], oracle_evidence: list[dict]):
    require_permission(task_id)
    path = smoke.verified_path(candidate["representative_path"], ".py")
    original = path.read_bytes()
    if sha256(original) != candidate["source_sha256"]:
        raise RuntimeError(f"Candidate source changed after registry check: {path}")
    code = original.decode("utf-8")  # NEVER exec, import or eval on host.
    entry = smoke.TASKS[task_id][0]
    tests = []
    chunk_wall = []
    for offset, subset in chunks(cases):
        require_permission(task_id)
        requests = [{"entry_point": entry, "args": c["args"]} for c in subset]
        t0 = time.perf_counter()
        responses = smoke.validator.docker_execute(code, requests)
        chunk_wall.append(round(time.perf_counter() - t0, 6))
        for i, (case, result) in enumerate(zip(subset, responses)):
            if not isinstance(result, dict):
                raise RuntimeError(f"Malformed Docker response from {candidate['candidate_id']}")
            oracle = oracle_evidence[offset + i]
            if case["name"] != oracle["name"] or case["args"] != oracle["args"]:
                raise RuntimeError("Oracle and frozen challenge input order differ")
            passed = smoke.validator.matching_result(
                result, oracle["expected"], oracle["expected_type"])
            failure_kind = (None if passed else
                            "wrong_answer" if result.get("status") == "ok" else
                            result.get("status") or "unknown_execution_failure")
            tests.append({"name": case["name"], "args": case["args"],
                          "expected": oracle["expected"],
                          "actual": result, "passed": passed,
                          "failure_type": failure_kind})
    if len(tests) != len(cases):
        raise RuntimeError(f"Candidate result count mismatch: {candidate['candidate_id']}")
    failures = [t for t in tests if not t["passed"]]
    return {
        "candidate_id": candidate["candidate_id"],
        "source_sha256": candidate["source_sha256"],
        "representative_path": candidate["representative_path"],
        "occurrence_count": candidate["occurrence_count"],
        "provenance_classes": candidate["provenance_classes"],
        "methods_in_occurrences": sorted({o["method"] for o in candidate["occurrences"]}),
        "status": "evaluated",
        "evidence_label": ("failure_observed_on_frozen_development_challenge" if failures
                           else "no_failure_observed_on_frozen_development_challenge"),
        "passed": len(tests) - len(failures),
        "total": len(tests),
        "wrong_answers": sum(t["failure_type"] == "wrong_answer" for t in failures),
        "execution_failures": sum(t["failure_type"] != "wrong_answer" for t in failures),
        "first_failure": failures[0] if failures else None,
        "candidate_challenge_calls": len(cases),
        "candidate_docker_batches": len(chunk_wall),
        "candidate_chunk_wall_seconds": chunk_wall,
        "tests": tests,
    }


def new_report_path(mode: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIR / f"challenge_evaluator_v1_{mode}_{stamp}_{uuid4().hex[:8]}.json"


def checkpoint(data: dict, output: Path) -> str:
    payload = json_bytes(data)
    temporary = output.with_name(output.name + ".tmp." + uuid4().hex[:8])
    try:
        with temporary.open("xb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return sha256(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--oracle-only", action="store_true",
                      help="Run reference self-check and oracle only in Docker")
    mode.add_argument("--run", action="store_true",
                      help="Run reference self-check, oracle, then candidates in Docker")
    parser.add_argument("--task-id", choices=TASKS, default=None)
    parser.add_argument("--max-per-task", type=int, default=0,
                        help="First N candidates per selected task, sorted by SHA; 0 = all")
    args = parser.parse_args()
    if args.max_per_task < 0:
        parser.error("--max-per-task must be nonnegative")
    if not args.run and args.max_per_task:
        parser.error("--max-per-task requires --run")
    if not (args.oracle_only or args.run) and args.task_id is not None:
        parser.error("--task-id needs --oracle-only or --run")

    # Entire registry, copied source, all provenance JSON and V3 policy are checked.
    verified = smoke.verify_registry()
    smoke.check_sandbox_contract()
    challenge = load_frozen_suite()
    print(f"Frozen challenge SHA256 verified: {CHALLENGE_SHA256}")
    for task_id in TASKS:
        print(f"{task_id}: {len(challenge[task_id])} unique frozen inputs")
    if not (args.oracle_only or args.run):
        print("READ-ONLY PREFLIGHT PASSED. No Docker, oracle or candidate execution.")
        return

    selected_tasks = [args.task_id] if args.task_id else list(TASKS)
    selection = {}
    for task_id in selected_tasks:
        entries = [verified[task_id][key] for key in sorted(verified[task_id])]
        selection[task_id] = entries[:args.max_per_task] if args.max_per_task else entries
    mode_label = "batch" if args.run else "oracle_only"
    output = new_report_path(mode_label)
    report = {
        "protocol": "phase2e_frozen_development_challenge_evaluator_v1",
        "mode": mode_label,
        "scope": "development_diagnostic_only_not_official_not_validation_not_heldout",
        "status": "planned",
        "created_utc": utc_now(),
        "completed_utc": None,
        "challenge_relpath": str(CHALLENGE_REL),
        "challenge_sha256": CHALLENGE_SHA256,
        "registry_relpath": str(smoke.REGISTRY_REL),
        "registry_sha256": smoke.REGISTRY_SHA256,
        "evaluator_script_sha256": sha256(Path(__file__).read_bytes()),
        "smoke_verifier_sha256": sha256(Path(smoke.__file__).read_bytes()),
        "phase2a_validator_sha256": sha256(Path(smoke.validator.__file__).read_bytes()),
        "quarantine_guard_sha256": sha256((ROOT / "phase2d_quarantine_guard.py").read_bytes()),
        "docker_image": smoke.validator.IMAGE,
        "case_timeout_seconds": smoke.validator.CASE_TIMEOUT,
        "case_chunk_size": BATCH_SIZE,
        "selection": {"task_ids": selected_tasks,
                      "max_candidates_per_task": args.max_per_task if args.run else None,
                      "ordering": "source_sha256 ascending"},
        "tasks": {},
        "totals": {"reference_self_check_calls": 0, "challenge_reference_calls": 0,
                   "candidate_challenge_calls": 0, "candidate_docker_batches": 0,
                   "candidates_evaluated": 0, "candidates_with_failure": 0,
                   "candidates_without_observed_failure": 0},
        "caveats": [
            "Frozen inputs are development diagnostics and not held out.",
            "A reference agreement is not a proof of candidate correctness.",
            "Task count is 2; search-derived candidates may share ancestry.",
            "The development diagnostic outcome must not guide the construction of a future independent evaluation set.",
            "No end-to-end cost-matched strategy comparison is performed here.",
            "This evaluator performs all 128 challenge inputs per candidate; it does not stop early.",
        ],
    }
    checkpoint(report, output)
    print("Created checkpoint:", output.relative_to(ROOT))
    try:
        smoke.validator.ensure_docker()
        report["status"] = "running"
        checkpoint(report, output)
        for task_id in selected_tasks:
            require_permission(task_id)
            cases = challenge[task_id]
            oracle = oracle_for_task(task_id, cases)
            print(f"{task_id}: reference self-check passed ({oracle['reviewed_self_check_count']} reviewed cases); "
                  f"oracle labeled {oracle['challenge_cases']} frozen cases", flush=True)
            report["tasks"][task_id] = {"entry_point": smoke.TASKS[task_id][0],
                                         "oracle": oracle, "candidates": []}
            report["totals"]["reference_self_check_calls"] += oracle["reviewed_self_check_count"]
            report["totals"]["challenge_reference_calls"] += oracle["challenge_reference_calls"]
            checkpoint(report, output)
            if args.oracle_only:
                continue
            for i, candidate in enumerate(selection[task_id], 1):
                result = evaluate_candidate(task_id, candidate, cases, oracle["oracle_evidence"])
                report["tasks"][task_id]["candidates"].append(result)
                totals = report["totals"]
                totals["candidates_evaluated"] += 1
                totals["candidate_challenge_calls"] += result["candidate_challenge_calls"]
                totals["candidate_docker_batches"] += result["candidate_docker_batches"]
                totals["candidates_with_failure" if result["first_failure"] else
                       "candidates_without_observed_failure"] += 1
                checkpoint(report, output)
                print(f"  {i}/{len(selection[task_id])}: {result['passed']}/{result['total']} "
                      f"{result['candidate_id']} ({result['evidence_label']})", flush=True)
        report["status"] = "completed"
        report["completed_utc"] = utc_now()
        final_sha = checkpoint(report, output)
        print("\nEVALUATION COMPLETED")
        print("Candidates evaluated:", report["totals"]["candidates_evaluated"])
        print("Candidates with verified challenge failures:", report["totals"]["candidates_with_failure"])
        print("Candidates with no observed challenge failure:", report["totals"]["candidates_without_observed_failure"])
        print("Report:", output.relative_to(ROOT))
        print("SHA256:", final_sha)
        print("Development diagnostic only; no held-out or correctness-generalization claims.")
    except (RuntimeError, OSError, ValueError, UnicodeError, KeyError, TypeError) as exc:
        report["status"] = "aborted_infrastructure_or_provenance_error"
        report["completed_utc"] = utc_now()
        report["abort_reason"] = f"{type(exc).__name__}: {exc}"
        checkpoint(report, output)
        print("\nEVALUATION ABORTED: incomplete candidates are not assigned outcomes")
        print("Checkpoint:", output.relative_to(ROOT))
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
