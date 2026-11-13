#!/usr/bin/env python3
"""Phase 2A: Docker-isolated, reference-oracle HumanEval development validator.

HumanEval/0 uses the original eight curated development tests. Other tasks need
an explicitly reviewed, per-task JSON file in data/development/humaneval/.
Official hidden tests are never loaded or used to guide candidate selection.
"""

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
IMAGE = (
    "python:3.11-slim@sha256:"
    "07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535"
)
CASE_TIMEOUT = 3
BATCH_TIMEOUT = 45
DOCKER_INFO_TIMEOUT = 20
MAX_CODE_BYTES = 256_000
MAX_OUTPUT_BYTES = 64_000
MAX_CASES = 30

# Original eight HumanEval/0 DEVELOPMENT cases: preserved for regression checks.
DEV_CASES_0 = [
    {"name": "empty", "args": [[], 0.5], "expected": False},
    {"name": "singleton", "args": [[1.0], 0.5], "expected": False},
    {"name": "separated_values", "args": [[1.0, 2.0, 3.0], 0.5], "expected": False},
    {"name": "close_pair", "args": [[1.0, 1.3, 1.8], 0.5], "expected": True},
    {"name": "unsorted_close_pair", "args": [[10.0, 1.0, 1.2], 0.25], "expected": True},
    {"name": "exact_threshold", "args": [[1.0, 2.0], 1.0], "expected": False},
    {"name": "duplicate_values", "args": [[2.5, 2.5], 0.1], "expected": True},
    {"name": "negative_values", "args": [[-4.0, -3.75, 10.0], 0.3], "expected": True},
]

# This code is executed only inside the restricted Docker container.
CHILD_RUNNER = r'''
import json
import sys
payload = json.load(sys.stdin)
try:
    namespace = {"__name__": "__main__"}
    exec(compile(payload["code"], "<candidate>", "exec"), namespace)
    result = namespace[payload["entry_point"]](*payload["args"])
    encoded = json.dumps(result, allow_nan=False)
    print(json.dumps({"status": "ok", "value": json.loads(encoded),
                      "type": type(result).__name__}))
except BaseException as exc:
    print(json.dumps({"status": "exception", "error_type": type(exc).__name__,
                      "error": str(exc)[:300]}))
'''

CONTAINER_RUNNER = r'''
import json
import subprocess
import sys
payload = json.load(sys.stdin)
results = []
child_env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONHASHSEED": "0",
             "PYTHONIOENCODING": "utf-8"}
for case in payload["cases"]:
    child_input = {"code": payload["code"], "entry_point": case["entry_point"],
                   "args": case["args"]}
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", payload["child_runner"]],
            input=json.dumps(child_input), text=True, capture_output=True,
            timeout=payload["case_timeout"], env=child_env, close_fds=True,
        )
    except subprocess.TimeoutExpired:
        results.append({"status": "timeout"})
        continue
    if completed.returncode != 0:
        results.append({"status": "process_error", "exit_code": completed.returncode,
                        "stderr": completed.stderr[-1000:]})
        continue
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1]) if lines else {}
    except (ValueError, TypeError):
        result = {}
    if not isinstance(result, dict) or result.get("status") not in {"ok", "exception"}:
        results.append({"status": "invalid_output",
                        "stdout": completed.stdout[-1000:],
                        "stderr": completed.stderr[-1000:]})
    else:
        results.append(result)
print(json.dumps(results, separators=(",", ":"), allow_nan=False))
'''


def validate_task_id(task_id):
    if not re.fullmatch(r"HumanEval/(?:[0-9]|[1-9][0-9]|1[0-5][0-9]|16[0-3])", task_id):
        raise ValueError("--task-id must be HumanEval/0 through HumanEval/163")
    return task_id


def load_development_cases(task_id):
    if task_id == "HumanEval/0":
        cases = DEV_CASES_0
    else:
        cases_root = ROOT / "data" / "development" / "humaneval"
        path = cases_root / (task_id.replace("/", "_") + ".json")
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(
                f"Missing reviewed development tests for {task_id}: {path.relative_to(ROOT)}. "
                "Create a JSON object with 'task_id' and nonempty 'cases' (each "
                "with 'name', 'args', 'expected'). Do not copy official held-out tests."
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("task_id") != task_id:
            raise ValueError(f"Development test file task ID mismatch: {path}")
        cases = payload.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError(f"Expected 1 to {MAX_CASES} development cases for {task_id}")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("name"), str):
            raise ValueError("Each case must have a string 'name'")
        if not case["name"] or case["name"] in seen:
            raise ValueError("Development case names must be nonempty and unique")
        seen.add(case["name"])
        if not isinstance(case.get("args"), list) or "expected" not in case:
            raise ValueError(f"Case {case['name']}: expected list 'args' and 'expected' value")
        if "expected_type" in case and not isinstance(case["expected_type"], str):
            raise ValueError(f"Case {case['name']}: expected_type must be a string")
        json.dumps(case, allow_nan=False)
    return cases


def ensure_docker():
    try:
        completed = subprocess.run(["docker", "info"], capture_output=True,
                                   text=True, timeout=DOCKER_INFO_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Docker is unavailable: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError("Docker daemon is unavailable: " + completed.stderr[-1000:])
    try:
        subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True,
                       text=True, timeout=DOCKER_INFO_TIMEOUT, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"Required pinned image is unavailable locally ({IMAGE}). Pull this exact image."
        ) from exc


def docker_execute(code, cases):
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError(f"Candidate exceeds {MAX_CODE_BYTES} bytes")
    payload = {"code": code, "cases": cases, "child_runner": CHILD_RUNNER,
               "case_timeout": CASE_TIMEOUT}
    container_name = f"phase2a-{uuid4().hex[:16]}"
    command = [
        "docker", "run", "--rm", "-i", "--name", container_name, "--pull=never",
        "--network=none", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true", "--pids-limit=32",
        "--memory=128m", "--memory-swap=128m", "--cpus=0.5",
        "--user=65534:65534", "--ulimit=nofile=64:64", "--ulimit=core=0",
        "--env=PYTHONHASHSEED=0", "--env=PYTHONIOENCODING=utf-8",
        IMAGE, "python", "-I", "-S", "-B", "-c", CONTAINER_RUNNER,
    ]
    # Preserve the original 45-second minimum, but account for longer suites.
    batch_timeout = max(BATCH_TIMEOUT, CASE_TIMEOUT * len(cases) + 15)
    try:
        completed = subprocess.run(command, input=json.dumps(payload), capture_output=True,
                                   text=True, timeout=batch_timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["docker", "rm", "--force", container_name],
                       capture_output=True, text=True,
                       timeout=DOCKER_INFO_TIMEOUT, check=False)
        raise RuntimeError(f"Docker batch exceeded {batch_timeout} seconds") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start Docker: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError("Sandbox execution failed: " + completed.stderr[-1500:])
    if len(completed.stdout.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("Sandbox response exceeded the output limit")
    try:
        results = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Invalid sandbox response: " + completed.stdout[-350:]) from exc
    if not isinstance(results, list) or len(results) != len(cases):
        raise RuntimeError("Sandbox returned the wrong number of test results")
    return results


def candidate_files(run_paths, task_id):
    allowed_root = (ROOT / "generated" / "phase1").resolve()
    pattern = re.compile(r"^(direct|sampling|diverse|plan)_\d{3}\.py$")
    found = []
    for run_arg in run_paths:
        run = (ROOT / run_arg).resolve()
        if not run.is_dir() or not run.is_relative_to(allowed_root):
            raise ValueError(f"Not a Phase 1 run folder: {run_arg}")
        for file in sorted(run.iterdir()):
            if not pattern.fullmatch(file.name):
                continue
            if file.is_symlink() or not file.is_file():
                raise ValueError(f"Symlink or non-file candidate rejected: {file}")
            metadata_path = file.with_suffix(".json")
            if metadata_path.is_symlink() or not metadata_path.is_file():
                raise ValueError(f"Missing or unsafe metadata for candidate: {file}")
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            if meta.get("task_id") != task_id:
                raise ValueError(f"Expected {task_id} but found {meta.get('task_id')!r} in {metadata_path}")
            found.append(file)
    return list(dict.fromkeys(found))


def load_reference(task_id):
    path = ROOT / "data" / "private" / "humaneval_evaluation.jsonl"
    if not path.is_file():
        raise FileNotFoundError("Missing data/private/humaneval_evaluation.jsonl. "
                                "Run scripts/prepare_problems.py first.")
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("task_id") == task_id:
                reference = record.get("reference_solution")
                entry_point = record.get("entry_point")
                if not isinstance(reference, str) or not isinstance(entry_point, str):
                    raise ValueError(f"{task_id} reference record is malformed")
                # Some benchmark exports store only a function body. Reject those
                # rather than accidentally mis-score candidates.
                try:
                    tree = ast.parse(reference)
                except SyntaxError as exc:
                    raise ValueError(f"{task_id} reference is not a complete Python module") from exc
                names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                if entry_point not in names:
                    raise ValueError(f"{task_id} reference has no callable {entry_point!r}; "
                                     "check reference data assembly")
                return reference, entry_point
    raise ValueError(f"{task_id} not found in private evaluation data")


def matching_result(result, expected, expected_type):
    return (result.get("status") == "ok"
            and result.get("type") == expected_type
            and type(result.get("value")) is type(expected)
            and result.get("value") == expected)


def evaluate_candidate(path, task_id, entry, cases, expected):
    result = {"candidate": str(path.relative_to(ROOT)), "task_id": task_id}
    try:
        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code)
        names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if entry not in names:
            raise ValueError(f"Required function {entry!r} not found")
        actual = docker_execute(code, [{"entry_point": entry, "args": case["args"]}
                                       for case in cases])
        checks = []
        for case, want, got in zip(cases, expected, actual):
            expected_type = case.get("expected_type", type(want).__name__)
            passed = matching_result(got, want, expected_type)
            failure_type = None if passed else ("wrong_answer" if got.get("status") == "ok"
                                                else got.get("status") or "unknown")
            checks.append({"name": case["name"], "input": case["args"],
                           "expected": want, "actual": got,
                           "passed": passed, "failure_type": failure_type})
        result.update(status="evaluated", passed=sum(x["passed"] for x in checks),
                      total=len(checks), all_passed=all(x["passed"] for x in checks),
                      tests=checks)
    except (SyntaxError, ValueError, UnicodeError) as exc:
        result.update(status="static_error", error=str(exc))
    except (RuntimeError, OSError) as exc:
        result.update(status="infrastructure_error", error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Docker-isolated Phase 2A validator with reviewed per-task development cases."
    )
    parser.add_argument("--task-id", default="HumanEval/0", help="HumanEval/0 to HumanEval/163")
    parser.add_argument("--runs", nargs="+", required=True, help="Phase 1 run folders for this task")
    parser.add_argument("--dry-run", action="store_true", help="List candidates without running Docker")
    args = parser.parse_args()
    try:
        task_id = validate_task_id(args.task_id)
        files = candidate_files(args.runs, task_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if not files:
        parser.error("No candidate .py files found in the selected Phase 1 folders")
    print(f"Found {len(files)} candidates for {task_id}")
    if args.dry_run:
        for path in files:
            print(" -", path.relative_to(ROOT))
        print("Dry run completed: no Docker containers started")
        return
    cases = load_development_cases(task_id)
    ensure_docker()
    reference_code, entry = load_reference(task_id)
    inputs = [{"entry_point": entry, "args": case["args"]} for case in cases]
    print(f"Running reference oracle on {len(inputs)} development inputs...")
    oracle = docker_execute(reference_code, inputs)
    for case, response in zip(cases, oracle):
        expected_type = case.get("expected_type", type(case["expected"]).__name__)
        if not matching_result(response, case["expected"], expected_type):
            raise RuntimeError(f"Reference oracle disagrees with reviewed development case "
                               f"{case['name']}: {response}")
    expected = [x["value"] for x in oracle]
    reports = []
    for path in files:
        report = evaluate_candidate(path, task_id, entry, cases, expected)
        reports.append(report)
        if report["status"] == "evaluated":
            print(f"{path.name:20s} {report['passed']:2d}/{report['total']} passed")
        else:
            print(f"{path.name:20s} {report['status']}: {report['error']}")
    output = ROOT / "results" / "phase2a"
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_file = output / f"{task_id.replace('/', '_').lower()}_{stamp}_{uuid4().hex[:6]}.json"
    payload = {"task_id": task_id, "suite": "manually_curated_development",
               "oracle": "HumanEval canonical solution (independent Docker execution)",
               "case_timeout_seconds": CASE_TIMEOUT,
               "batch_timeout_seconds": max(BATCH_TIMEOUT, CASE_TIMEOUT * len(cases) + 15),
               "docker_image": IMAGE, "test_count": len(cases),
               "candidate_count": len(files),
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "results": reports}
    report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("\nSaved report:", report_file.relative_to(ROOT))
    print("These are DEVELOPMENT results, not official or held-out benchmark scores.")


if __name__ == "__main__":
    main()
