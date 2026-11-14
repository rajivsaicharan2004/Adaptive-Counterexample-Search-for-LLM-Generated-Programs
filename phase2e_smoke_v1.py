#!/usr/bin/env python3
"""Phase 2E: fail-closed, development-only Docker correctness smoke test.

Place this file in the project root beside phase2a_validator.py and
phase2d_quarantine_guard.py. Candidate code is NEVER executed on the host.
"""
import argparse
import ast
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import phase2a_validator as validator
from phase2d_quarantine_guard import require_task_permission

ROOT = Path(__file__).resolve().parent
REGISTRY_REL = Path("results/phase2e/candidate_registry_v1_1.json")
REGISTRY_SHA256 = "930ebc77561e7bb4fea4de8c73d46048a24df5eaa543ae031af74eedcbe63fd6"
PINNED_IMAGE = (
    "python:3.11-slim@sha256:"
    "07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535"
)
TASKS = {"HumanEval/0": ("has_close_elements", 9),
         "HumanEval/1": ("separate_paren_groups", 42)}
SMOKE_TASK = "HumanEval/0"
SMOKE_SHA256 = "467367f297f7ffd21194846829a1f7df77de3aab9445e45ece7e03d8f1b95fac"
PROMPT_METHODS = {"direct", "sampling", "diverse", "plan"}
SEARCH_METHODS = {"beam", "mcts", "evolution", "adaptive"}


def fail(message):
    raise RuntimeError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verified_path(relative, extension):
    if not isinstance(relative, str):
        fail("Registry path is not a string")
    part = Path(relative)
    if (part.is_absolute() or ".." in part.parts
            or part.suffix != extension
            or tuple(part.parts[:2]) != ("generated", "phase1")):
        fail(f"Invalid generated-file path: {relative!r}")
    target = (ROOT / part).resolve(strict=True)
    generated_root = (ROOT / "generated" / "phase1").resolve(strict=True)
    if not target.is_relative_to(generated_root) or not target.is_file():
        fail(f"Path escapes generated/phase1 or is not a file: {relative}")
    return target


def verify_registry():
    raw = (ROOT / REGISTRY_REL).read_bytes()
    if sha256(raw) != REGISTRY_SHA256:
        fail("Registry SHA-256 changed: stop and investigate, do not rebaseline")
    doc = json.loads(raw)
    if (doc.get("protocol") != "phase2e_candidate_registry_v1_1"
            or doc.get("status") != "development_pilot_not_correctness_evaluated"
            or set(doc.get("tasks", {})) != set(TASKS)):
        fail("Unexpected registry protocol, status, or tasks")

    # The quarantine review is provisional. Its verified policy must remain unchanged.
    for task_id in TASKS:
        print(require_task_permission(ROOT, task_id, "evaluate"))

    verified = {}
    for task_id, (entry, expected_n) in TASKS.items():
        task = doc["tasks"][task_id]
        candidates = task.get("candidates")
        if (task.get("entry_point") != entry
                or not isinstance(candidates, list)
                or task.get("candidate_count") != expected_n
                or len(candidates) != expected_n):
            fail(f"Unexpected candidate count or entry point for {task_id}")

        seen_hashes = set()
        verified[task_id] = {}
        for candidate in candidates:
            digest = candidate.get("source_sha256")
            if (not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or digest in seen_hashes
                    or candidate.get("candidate_id") != f"{task_id}:{digest[:16]}"):
                fail(f"Invalid or duplicate candidate identifier for {task_id}")
            seen_hashes.add(digest)

            occurrences = candidate.get("occurrences")
            if (not isinstance(occurrences, list) or not occurrences
                    or len(occurrences) != candidate.get("occurrence_count")):
                fail(f"Invalid occurrences for {task_id}:{digest[:16]}")
            paths = set()
            classes = set()
            for occurrence in occurrences:
                code_path = verified_path(occurrence.get("path"), ".py")
                meta_path = verified_path(occurrence.get("metadata_path"), ".json")
                if meta_path != code_path.with_suffix(".json"):
                    fail(f"Candidate/metadata path mismatch: {code_path}")
                code_bytes = code_path.read_bytes()
                metadata_bytes = meta_path.read_bytes()
                if sha256(code_bytes) != digest or not code_bytes.endswith(b"\n"):
                    fail(f"Candidate file hash or newline mismatch: {code_path}")
                if sha256(metadata_bytes) != occurrence.get("metadata_sha256"):
                    fail(f"Metadata file changed: {meta_path}")
                metadata = json.loads(metadata_bytes)
                phase1_digest = sha256(code_bytes[:-1])
                if (metadata.get("code_sha256") != phase1_digest
                        or occurrence.get("phase1_recorded_code_sha256") != phase1_digest
                        or occurrence.get("saved_file_sha256") != digest
                        or occurrence.get("code_hash_normalization") != "remove_exactly_one_final_LF"):
                    fail(f"Phase 1 hash provenance mismatch: {code_path}")
                if (metadata.get("task_id") != task_id
                        or metadata.get("status") != "generated"
                        or metadata.get("syntax_ok") is not True
                        or metadata.get("entry_point_present") is False
                        or metadata.get("method") != occurrence.get("method")
                        or metadata.get("model") != occurrence.get("model")
                        or metadata.get("run_id") != occurrence.get("run_id")):
                    fail(f"Candidate metadata mismatch: {code_path}")
                method = metadata["method"]
                if method not in PROMPT_METHODS | SEARCH_METHODS:
                    fail(f"Unrecognized method: {method}")
                cls = "search_derived" if method in SEARCH_METHODS else "prompt_generated"
                if occurrence.get("provenance_class") != cls:
                    fail(f"Provenance class mismatch: {code_path}")
                classes.add(cls)
                parsed = ast.parse(code_bytes.decode("utf-8"), filename=str(code_path))
                top_functions = {n.name for n in parsed.body
                                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                if entry not in top_functions:
                    fail(f"Expected entry point missing: {code_path}")
                paths.add(occurrence["path"])
            if (candidate.get("representative_path") not in paths
                    or candidate.get("provenance_classes") != sorted(classes)
                    or candidate.get("correctness_status") != "not_evaluated"):
                fail(f"Candidate summary mismatch: {task_id}:{digest[:16]}")
            verified[task_id][digest] = candidate
    print("Registry verified: 51 unique candidates; all recorded copies and metadata checked")
    return verified


def check_sandbox_contract():
    if validator.IMAGE != PINNED_IMAGE:
        fail("Sandbox image digest differs from the established Phase 2A image")
    # Fail closed if the previously inspected Docker restrictions are removed.
    tree = ast.parse(Path(validator.__file__).read_text(encoding="utf-8"))
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == "docker_execute"]
    if len(functions) != 1:
        fail("Cannot inspect the Docker executor")
    tokens = {n.value for n in ast.walk(functions[0])
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    required = {"--rm", "-i", "--pull=never", "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                "--pids-limit=32", "--memory=128m", "--memory-swap=128m",
                "--cpus=0.5", "--user=65534:65534"}
    if not required.issubset(tokens):
        fail("Docker executor no longer has all expected safety flags")


def run_smoke(verified):
    candidate = verified[SMOKE_TASK].get(SMOKE_SHA256)
    if candidate is None:
        fail("Pinned smoke candidate is absent from verified registry")
    code_path = verified_path(candidate["representative_path"], ".py")
    check_sandbox_contract()
    validator.ensure_docker()
    cases = validator.load_development_cases(SMOKE_TASK)
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        fail("Unexpected number or shape of reviewed development cases")
    for case in cases:
        if (not isinstance(case, dict) or not isinstance(case.get("name"), str)
                or not isinstance(case.get("args"), list) or "expected" not in case):
            fail("Malformed reviewed development case")

    reference_code, entry = validator.load_reference(SMOKE_TASK)
    if entry != TASKS[SMOKE_TASK][0]:
        fail("Reference entry point disagrees with registry")
    inputs = [{"entry_point": entry, "args": case["args"]} for case in cases]
    print(f"\nRunning the canonical reference in Docker on {len(cases)} reviewed cases...")
    t0 = time.perf_counter()
    oracle = validator.docker_execute(reference_code, inputs)
    oracle_wall = time.perf_counter() - t0
    for case, response in zip(cases, oracle):
        expected_type = case.get("expected_type", type(case["expected"]).__name__)
        if not validator.matching_result(response, case["expected"], expected_type):
            fail(f"Reference oracle disagrees with reviewed development case {case['name']!r}")

    print("Reference self-check passed. Running ONE genuine Phase 1 candidate in Docker...")
    t0 = time.perf_counter()
    evaluation = validator.evaluate_candidate(
        code_path, SMOKE_TASK, entry, cases, [r["value"] for r in oracle]
    )
    candidate_wall = time.perf_counter() - t0
    if evaluation.get("status") != "evaluated":
        fail(f"Candidate evaluation did not complete normally: {evaluation.get('status')}"
             f" ({evaluation.get('error', '')})")
    if evaluation.get("total") != len(cases):
        fail("Candidate result count differs from development suite")

    correctness = ("failure_observed_on_reviewed_development_cases"
                   if not evaluation["all_passed"] else "no_failure_observed_on_these_cases")
    report = {
        "protocol": "phase2e_correctness_smoke_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "development_pilot_only_not_official_or_heldout",
        "correctness_label": correctness,
        "case_suite": "phase2a_manually_curated_development",
        "case_count": len(cases),
        "candidate_id": candidate["candidate_id"],
        "candidate_source_sha256": SMOKE_SHA256,
        "candidate_path": candidate["representative_path"],
        "registry_sha256": REGISTRY_SHA256,
        "evaluator_script_sha256": sha256(Path(__file__).read_bytes()),
        "phase2a_validator_sha256": sha256(Path(validator.__file__).read_bytes()),
        "phase2d_quarantine_guard_sha256": sha256(
            (ROOT / "phase2d_quarantine_guard.py").read_bytes()),
        "docker_image": validator.IMAGE,
        "reference_oracle_calls": len(cases),
        "candidate_calls": len(cases),
        "oracle_batch_wall_seconds": round(oracle_wall, 4),
        "candidate_batch_wall_seconds": round(candidate_wall, 4),
        "cost_note": "Batch times include Docker overhead; not an end-to-end strategy comparison.",
        "evidence_limit": (
            "A passing candidate is not proven correct. Development tests may have "
            "influenced search-derived generation; these are not held-out claims."
        ),
        "evaluation": evaluation,
    }
    output_dir = ROOT / "results" / "phase2e"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"smoke_v1_{stamp}_{uuid4().hex[:8]}.json"
    serialized = json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with output.open("xb") as handle:
        handle.write(serialized)
    print(f"\nCandidate: {candidate['candidate_id']}")
    print(f"Development cases passed: {evaluation['passed']}/{evaluation['total']}")
    print(f"Evidence label: {correctness}")
    failures = [test for test in evaluation["tests"] if not test["passed"]]
    if failures:
        example = failures[0]
        print("First counterexample (reviewed development input):")
        print(" ", json.dumps({"name": example["name"], "args": example["input"],
                                 "expected": example["expected"],
                                 "actual": example["actual"],
                                 "failure_type": example["failure_type"]}))
    print("Evidence saved:", output.relative_to(ROOT))
    print("Evidence SHA256:", sha256(serialized))
    print("Only the reference and ONE candidate were executed, both inside Docker.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true",
                        help="Actually run one pinned HumanEval/0 candidate via Docker")
    args = parser.parse_args()
    verified = verify_registry()
    if not args.smoke:
        print("\nDRY RUN PASSED: no Docker or candidate executions performed.")
        print("Next: .venv/bin/python phase2e_smoke_v1.py --smoke")
        return
    run_smoke(verified)


if __name__ == "__main__":
    main()
