#!/usr/bin/env python3
"""Read-only cross-dataset Phase 1 integration preflight.

Checks the public JSONL adapters, required fields, and both generator CLIs.
Does NOT call a model, execute generated code, read private evaluation data,
or assert that a benchmark's evaluator is ready.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
DATASETS = ("humaneval", "mbpp", "bigcodebench", "livecodebench")
GENERATOR_SCRIPTS = ("phase1_generator.py", "phase1_advanced.py")


def select_public_path(dataset: str) -> Path:
    direct = ROOT / "data" / "public" / f"{dataset}.jsonl"
    if direct.is_file():
        return direct
    fallback = ROOT / "data" / "public" / "problems.jsonl"
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(
        f"Missing data/public/{dataset}.jsonl and data/public/problems.jsonl"
    )


def audit_records(dataset: str) -> dict[str, Any]:
    path = select_public_path(dataset)
    good = []
    problems = []
    ids = set()
    seen_errors = []
    for line_no, raw in enumerate(path.open(encoding="utf-8"), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            seen_errors.append(f"line {line_no}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(row, dict) or row.get("dataset") != dataset:
            continue
        task_id = row.get("task_id")
        prompt = row.get("prompt")
        entry = row.get("entry_point")
        starter = row.get("starter_code")
        if not isinstance(task_id, str) or not task_id.strip():
            seen_errors.append(f"line {line_no}: missing/non-string task_id")
            continue
        if task_id in ids:
            seen_errors.append(f"line {line_no}: duplicate task_id {task_id!r}")
            continue
        ids.add(task_id)
        if not isinstance(prompt, str) or not prompt.strip():
            seen_errors.append(f"line {line_no}: missing/empty prompt ({task_id})")
            continue
        if entry is not None and not isinstance(entry, str):
            seen_errors.append(f"line {line_no}: invalid entry_point type ({task_id})")
            continue
        if starter is not None and not isinstance(starter, str):
            seen_errors.append(f"line {line_no}: invalid starter_code type ({task_id})")
            continue
        interface = "callable" if entry else "stdin_stdout_or_unspecified"
        item = {"task_id": task_id, "prompt_length": len(prompt),
                "entry_point": entry, "interface": interface,
                "starter_code_present": bool(starter), "line_number": line_no,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
        good.append(item)
        problems.append(item)

    if not good:
        raise ValueError(f"No valid {dataset} problem records in {path}")
    # Pick a case near the median prompt length: a schema smoke test, not a
    # claim that this task represents the dataset's difficulty distribution.
    callable_records = [r for r in good if r["interface"] == "callable"]
    pool = callable_records if callable_records else good
    representative = sorted(pool, key=lambda r: (r["prompt_length"], r["task_id"]))[len(pool) // 2]
    return {
        "dataset": dataset, "file": str(path.relative_to(ROOT)),
        "record_count": len(good), "interface_counts": dict(Counter(r["interface"] for r in good)),
        "starter_code_count": sum(r["starter_code_present"] for r in good),
        "errors_count": len(seen_errors), "errors_preview": seen_errors[:10],
        "selected_task": representative,
        "selection_rule": "median prompt length of callable tasks if available; else all tasks",
    }


def smoke_generator(script: str, dataset: str, task_id: str) -> dict[str, Any]:
    path = ROOT / script
    if not path.is_file():
        return {"status": "missing_script", "script": script}
    command = [sys.executable, script, "--dataset", dataset, "--task-id", task_id,
               "--dry-run", "--max-calls", "1"]
    if script == "phase1_generator.py":
        command.extend(["--method", "direct"])
    else:
        command.extend(["--method", "mcts", "--candidates", "1"])
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                text=True, timeout=35, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"script": script, "status": "execution_error", "error": str(exc)}
    return {"script": script, "status": "pass" if result.returncode == 0 else "fail",
            "exit_code": result.returncode,
            "output_tail": (result.stdout + "\n" + result.stderr)[-1800:]}


def main() -> None:
    p = argparse.ArgumentParser(description="Read-only public dataset + generator CLI audit")
    p.add_argument("--datasets", nargs="+", choices=DATASETS, default=list(DATASETS))
    p.add_argument("--output", default="results/phase1_cross_dataset/preflight.json")
    p.add_argument("--skip-cli", action="store_true", help="Only inspect JSONL schemas")
    args = p.parse_args()
    print("Phase 1 cross-dataset preflight: NO API, NO Docker, NO private data")
    reports = []
    for dataset in args.datasets:
        print(f"\n--- {dataset} ---")
        try:
            audit = audit_records(dataset)
        except (OSError, ValueError) as exc:
            reports.append({"dataset": dataset, "status": "failed", "error": str(exc)})
            print("DATASET ERROR:", exc)
            continue
        task = audit["selected_task"]
        audit["generator_checks"] = (
            [] if args.skip_cli else
            [smoke_generator(script, dataset, task["task_id"]) for script in GENERATOR_SCRIPTS]
        )
        audit["status"] = (
            "preflight_pass" if not audit["errors_count"] and
            all(x["status"] == "pass" for x in audit["generator_checks"])
            else "attention_needed"
        ) if not args.skip_cli else ("schema_pass" if not audit["errors_count"] else "attention_needed")
        # Phase 2A currently only supports HumanEval; the other adapters are
        # intentionally NOT asserted to exist just because generation loads.
        audit["evaluator_status"] = (
            "HumanEval-only validator exists; selected task needs reviewed development cases"
            if dataset == "humaneval" else
            "NOT VALIDATED: dataset-specific evaluator adapter is not yet integrated"
        )
        reports.append(audit)
        print("Records:", audit["record_count"], "| Interfaces:", audit["interface_counts"])
        print("Selected task:", task["task_id"], "| Interface:", task["interface"],
              "| Entry point:", task["entry_point"])
        print("Schema issues:", audit["errors_count"])
        for check in audit["generator_checks"]:
            print("  ", check["script"], "dry-run:", check["status"])
            if check["status"] != "pass":
                print(check.get("output_tail", check.get("error", ""))[-600:])
        print("Evaluator:", audit["evaluator_status"])
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT):
        p.error("--output must be within the project")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({
        "study": "phase1_cross_dataset_interface_preflight",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "no_model_calls": True, "no_docker": True, "no_private_evaluation_data": True,
        "limitations": [
            "A dry-run verifies prompt loading, not candidate correctness.",
            "The selected task is a schema smoke-test sample, not an unbiased performance sample.",
            "HumanEval-only Phase 2A does not evaluate MBPP, BigCodeBench, or LiveCodeBench.",
        ],
        "datasets": reports,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nSaved audit:", output.relative_to(ROOT))
    print("Next: inspect evaluator readiness and only then run one paid generation per dataset.")
    if any(r.get("status") in ("failed", "attention_needed") for r in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
