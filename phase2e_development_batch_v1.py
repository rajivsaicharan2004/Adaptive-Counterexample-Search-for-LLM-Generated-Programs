#!/usr/bin/env python3
"""Phase 2E: versioned, development-only correctness audit for unique Phase 1 programs.

Place beside phase2e_smoke_v1.py, phase2a_validator.py, and
phase2d_quarantine_guard.py in the project root. Candidate code and the
reference oracle run ONLY through the existing restricted Docker executor.

Default invocation is READ-ONLY PREFLIGHT; Docker runs require --run explicitly.
No held-out or official benchmark evaluation is performed.
"""

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import phase2e_smoke_v1 as smoke

ROOT = Path(__file__).resolve().parent
REPORT_DIR = ROOT / "results" / "phase2e"
TASKS = tuple(smoke.TASKS)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def new_report_path():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPORT_DIR / f"development_batch_v1_{stamp}_{uuid4().hex[:8]}.json"


def snapshot(report, output):
    """Atomically checkpoint this run; never replace unrelated reports."""
    payload = (json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
               + "\n").encode("utf-8")
    temporary = output.with_name(output.name + ".tmp." + uuid4().hex[:8])
    try:
        with temporary.open("xb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return digest(payload)


def development_cases(task_id):
    """Retrieve the original reviewed development cases, not new private tests."""
    cases = smoke.validator.load_development_cases(task_id)
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise RuntimeError(f"Invalid development suite size for {task_id}")
    seen_names = set()
    for case in cases:
        if (not isinstance(case, dict)
                or not isinstance(case.get("name"), str)
                or not isinstance(case.get("args"), list)
                or "expected" not in case
                or case["name"] in seen_names):
            raise RuntimeError(f"Malformed or duplicate reviewed development case for {task_id}")
        seen_names.add(case["name"])
    return cases


def reference_self_check(task_id, entry, cases):
    """Never evaluate candidates if the reference contradicts a reviewed answer."""
    reference_code, reference_entry = smoke.validator.load_reference(task_id)
    if reference_entry != entry:
        raise RuntimeError(f"Reference entry point disagrees with registry: {task_id}")
    request = [{"entry_point": entry, "args": case["args"]} for case in cases]
    started = time.perf_counter()
    oracle = smoke.validator.docker_execute(reference_code, request)
    wall = time.perf_counter() - started
    for case, response in zip(cases, oracle):
        if not isinstance(response, dict):
            raise RuntimeError(f"Malformed Docker reference response for {task_id}")
        expected_type = case.get("expected_type", type(case["expected"]).__name__)
        if not smoke.validator.matching_result(response, case["expected"], expected_type):
            raise RuntimeError(
                f"Reference self-check failed on {task_id} / {case['name']}; "
                "candidate evaluation is prohibited"
            )
    return [response["value"] for response in oracle], request, wall


def evaluate(registered, task_id, entry, cases, expected, request):
    """Execute the verified source through Docker only, never on the host."""
    path = smoke.verified_path(registered["representative_path"], ".py")
    source_bytes = path.read_bytes()
    if digest(source_bytes) != registered["source_sha256"]:
        raise RuntimeError(f"Source changed after registry verification: {path}")
    if not source_bytes.endswith(b"\n"):
        raise RuntimeError(f"Candidate newline provenance changed: {path}")

    # Source.decode does NOT execute anything. docker_execute is the sole
    # candidate execution boundary.
    source = source_bytes.decode("utf-8")
    started = time.perf_counter()
    actual = smoke.validator.docker_execute(source, request)
    elapsed = time.perf_counter() - started
    if len(actual) != len(cases):
        raise RuntimeError("Docker response has wrong number of cases")

    tests = []
    for case, want, got in zip(cases, expected, actual):
        if not isinstance(got, dict):
            raise RuntimeError("Malformed Docker candidate response")
        expected_type = case.get("expected_type", type(want).__name__)
        passed = smoke.validator.matching_result(got, want, expected_type)
        if passed:
            failure_type = None
        elif got.get("status") == "ok":
            failure_type = "wrong_answer"
        else:
            failure_type = got.get("status") or "unknown_execution_failure"
        tests.append({
            "name": case["name"], "args": case["args"],
            "expected": want, "actual": got,
            "passed": passed, "failure_type": failure_type,
        })

    passed_count = sum(t["passed"] for t in tests)
    label = ("no_failure_observed_on_reviewed_development_cases" if passed_count == len(tests)
             else "failure_observed_on_reviewed_development_cases")
    return {
        "candidate_id": registered["candidate_id"],
        "source_sha256": registered["source_sha256"],
        "representative_path": registered["representative_path"],
        "occurrence_count": registered["occurrence_count"],
        "provenance_classes": registered["provenance_classes"],
        "methods_in_occurrences": sorted(set(
            o["method"] for o in registered["occurrences"])),
        "run_ids_in_occurrences": sorted(set(
            str(o["run_id"]) for o in registered["occurrences"])),
        "status": "evaluated",
        "evidence_label": label,
        "passed": passed_count,
        "total": len(tests),
        "candidate_test_executions": len(tests),
        "candidate_docker_batches": 1,
        "candidate_batch_wall_seconds": round(elapsed, 4),
        "first_failure": next((t for t in tests if not t["passed"]), None),
        "tests": tests,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="Explicitly authorize Docker evaluation; omitted means read-only preflight")
    parser.add_argument("--task-id", choices=TASKS, default=None,
                        help="Evaluate only one permitted development task (default: both)")
    parser.add_argument("--max-per-task", type=int, default=0,
                        help="Evaluate first N unique candidates/task; 0 means all (default)")
    args = parser.parse_args()
    if args.max_per_task < 0:
        parser.error("--max-per-task must be zero or positive")
    if not args.run and (args.task_id is not None or args.max_per_task):
        parser.error("--task-id and --max-per-task require --run")

    # These checks verify every original registry record, copied source,
    # recorded metadata hash and quarantine policy; no generated code is run.
    verified = smoke.verify_registry()
    smoke.check_sandbox_contract()
    print("Sandbox source contract verified (without starting Docker)")
    if not args.run:
        print("READ-ONLY PREFLIGHT PASSED. No Docker or candidate executions.")
        return

    selected_tasks = [args.task_id] if args.task_id is not None else list(TASKS)
    plan = {}
    for task_id in selected_tasks:
        all_candidates = [verified[task_id][h] for h in sorted(verified[task_id])]
        chosen = all_candidates[:args.max_per_task] if args.max_per_task else all_candidates
        if not chosen:
            raise RuntimeError(f"No eligible candidates for {task_id}")
        plan[task_id] = chosen

    report = {
        "protocol": "phase2e_development_correctness_batch_v1",
        "scope": "development_only_not_official_not_heldout",
        "status": "planned",
        "created_utc": utc_now(),
        "completed_utc": None,
        "registry_relpath": str(smoke.REGISTRY_REL),
        "registry_sha256": smoke.REGISTRY_SHA256,
        "batch_script_sha256": digest(Path(__file__).read_bytes()),
        "smoke_verifier_sha256": digest(Path(smoke.__file__).read_bytes()),
        "validator_sha256": digest(Path(smoke.validator.__file__).read_bytes()),
        "quarantine_guard_sha256": digest((ROOT / "phase2d_quarantine_guard.py").read_bytes()),
        "docker_image": smoke.validator.IMAGE,
        "selection": {
            "task_ids": selected_tasks,
            "max_candidates_per_task": args.max_per_task,
            "candidate_counts": {t: len(plan[t]) for t in selected_tasks},
            "order": "source_sha256 ascending per task",
        },
        "tasks": {},
        "totals": {"candidates_evaluated": 0, "candidates_with_failure": 0,
                   "candidates_without_observed_failure": 0,
                   "candidate_test_executions": 0, "reference_test_executions": 0,
                   "candidate_docker_batches": 0, "reference_docker_batches": 0},
        "caveats": [
            "Passing reviewed development tests does not establish correctness.",
            "The 51 implementations are from two tasks; some share search ancestry.",
            "Reviewed development cases may have influenced search-derived candidates.",
            "No official, validation, held-out, or temporal task is evaluated.",
            "This is NOT a matched comparison of testing strategies.",
            "Docker batch wall times include process startup and system overhead.",
        ],
    }
    output = new_report_path()
    snapshot(report, output)
    print(f"Created checkpoint: {output.relative_to(ROOT)}")

    try:
        # Keep all execution behind the same existing Docker executor used by
        # the successful Phase 2E smoke test. No unsafe fallback is allowed.
        smoke.validator.ensure_docker()
        report["status"] = "running"
        snapshot(report, output)

        for task_id in selected_tasks:
            print(f"\nTASK {task_id}: {len(plan[task_id])} unique candidates")
            smoke.require_task_permission(ROOT, task_id, "evaluate")
            cases = development_cases(task_id)
            entry = smoke.TASKS[task_id][0]
            expected, request, oracle_wall = reference_self_check(
                task_id, entry, cases)
            print(f"Reference self-check passed: {len(cases)} reviewed cases")
            report["tasks"][task_id] = {
                "entry_point": entry,
                "case_suite": "phase2a_manually_curated_development",
                "case_count": len(cases),
                "reference_self_check": "passed",
                "reference_test_executions": len(cases),
                "reference_docker_batches": 1,
                "reference_batch_wall_seconds": round(oracle_wall, 4),
                "candidates": [],
            }
            report["totals"]["reference_test_executions"] += len(cases)
            report["totals"]["reference_docker_batches"] += 1
            snapshot(report, output)

            for i, registered in enumerate(plan[task_id], start=1):
                # Revalidate the policy even when processing a long batch.
                smoke.require_task_permission(ROOT, task_id, "evaluate")
                record = evaluate(registered, task_id, entry, cases, expected, request)
                report["tasks"][task_id]["candidates"].append(record)
                counts = report["totals"]
                counts["candidates_evaluated"] += 1
                counts["candidate_test_executions"] += record["candidate_test_executions"]
                counts["candidate_docker_batches"] += record["candidate_docker_batches"]
                if record["first_failure"] is None:
                    counts["candidates_without_observed_failure"] += 1
                else:
                    counts["candidates_with_failure"] += 1
                snapshot(report, output)
                print(f"  {i:2d}/{len(plan[task_id])}: {record['passed']}/{record['total']} "
                      f"{record['candidate_id']} ({record['evidence_label']})", flush=True)

        report["status"] = "completed"
        report["completed_utc"] = utc_now()
        final_sha = snapshot(report, output)
        print("\nBATCH COMPLETED")
        print("Candidates evaluated:", report["totals"]["candidates_evaluated"])
        print("Candidates with development-test failures:",
              report["totals"]["candidates_with_failure"])
        print("Candidates with no observed failure:",
              report["totals"]["candidates_without_observed_failure"])
        print("Report:", output.relative_to(ROOT))
        print("SHA256:", final_sha)
        print("Development-only evidence. No correctness or held-out claims.")
    except (RuntimeError, OSError, ValueError, UnicodeError) as exc:
        report["status"] = "aborted_infrastructure_or_provenance_error"
        report["completed_utc"] = utc_now()
        report["abort_reason"] = f"{type(exc).__name__}: {exc}"
        snapshot(report, output)
        print("\nBATCH ABORTED: no incomplete candidate was labeled correct or incorrect")
        print("Checkpoint:", output.relative_to(ROOT))
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
