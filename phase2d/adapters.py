"""Dataset-agnostic public task loading and strictly development-only suites."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import json
import re
from .models import TaskSpec, Case, DATASETS

MBPP_545_VALUES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 16, 17, 31, 32, 33, 63, 64, 65]
HUMANEVAL_0_CASES = [
    ("empty", [[], 0.5], False),
    ("singleton", [[1.0], 0.5], False),
    ("separated", [[1.0, 2.0, 3.0], 0.5], False),
    ("close_pair", [[1.0, 1.3, 1.8], 0.5], True),
    ("unsorted_pair", [[10.0, 1.0, 1.2], 0.25], True),
    ("exact_threshold", [[1.0, 2.0], 1.0], False),
    ("duplicate", [[2.5, 2.5], 0.1], True),
    ("negative", [[-4.0, -3.75, 10.0], 0.3], True),
]


def task_filename(task_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", task_id) + ".json"


def public_task(root: Path, dataset: str, task_id: str) -> TaskSpec:
    if dataset not in DATASETS:
        raise ValueError("Unsupported dataset")
    path = root / "data" / "public" / (dataset + ".jsonl")
    if not path.is_file():
        path = root / "data" / "public" / "problems.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"Public problem dataset missing: {dataset}")
    found = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("dataset") == dataset and record.get("task_id") == task_id:
                found = record
                break
    if found is None:
        raise ValueError(f"Task not found: {dataset}/{task_id}")
    prompt, entry = found.get("prompt"), found.get("entry_point")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Missing public problem prompt")
    if entry is not None and not isinstance(entry, str):
        raise ValueError("Invalid entry_point")
    interface = ("leetcode_method" if dataset == "livecodebench" and "/leetcode/" in task_id
                 else "callable" if entry else "stdin_stdout")
    # BigCodeBench frequently requires external dependencies beyond python:3.11-slim.
    requires_dependencies = dataset == "bigcodebench"
    return TaskSpec(dataset=dataset, task_id=task_id, prompt=prompt,
                    entry_point=entry, interface=interface,
                    starter_code=found.get("starter_code") or "",
                    requires_dependencies=requires_dependencies,
                    metadata={"public_dataset_path": str(path.relative_to(root)),
                              "public_record_fields": sorted(found.keys())})


def load_development_suite(root: Path, spec: TaskSpec, path: str | None = None) -> tuple[list[Case], str, TaskSpec]:
    """No official tests or private reference solutions can be read via this loader."""
    filename = task_filename(spec.task_id)
    default_path = root / "data" / "development" / spec.dataset / filename
    src = Path(path).expanduser().resolve() if path else default_path
    if src.is_file():
        raw = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("task_id") != spec.task_id:
            raise ValueError("Development suite task ID mismatch")
        if raw.get("provenance") != "independently_reviewed_development":
            raise ValueError("Development suites must declare independently_reviewed_development provenance")
        settings = raw.get("comparator", {})
        if settings:
            if not isinstance(settings, dict):
                raise ValueError("Invalid comparator configuration")
            mode = settings.get("mode", "exact")
            if mode not in ("exact", "numeric", "unordered_list"):
                raise ValueError("Invalid comparison mode")
            abs_tol = float(settings.get("abs_tol", 0))
            rel_tol = float(settings.get("rel_tol", 0))
            if abs_tol < 0 or rel_tol < 0:
                raise ValueError("Comparison tolerances cannot be negative")
            spec = replace(spec, comparison=mode, abs_tol=abs_tol, rel_tol=rel_tol)
        rows, provenance = raw.get("cases"), str(src)
    elif spec.task_id == "HumanEval/0" and spec.dataset == "humaneval":
        rows = [{"name": name, "args": args, "expected": want, "expected_type": "bool"}
                for name, args, want in HUMANEVAL_0_CASES]
        provenance = "builtin_reviewed_humaneval_0"
    elif spec.task_id == "MBPP/545" and spec.dataset == "mbpp":
        # Independently derived from the public specification, not official assertions.
        def toggle(n: int) -> int:
            return n ^ (1 | (1 << (n.bit_length() - 1)))
        rows = [{"name": f"positive_integer_{n}", "args": [n],
                 "expected": toggle(n), "expected_type": "int"}
                for n in MBPP_545_VALUES]
        provenance = "builtin_reviewed_mbpp_545"
    else:
        raise FileNotFoundError(f"Missing reviewed development suite at {src}. "
                                "Do not use official held-out assertions in its place.")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError("Expected 1..500 independently reviewed development cases")
    cases = []
    seen = set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not isinstance(row.get("args"), list) or "expected" not in row:
            raise ValueError(f"Invalid development case {i}")
        name = row.get("name", f"case_{i}")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("Development case names must be unique")
        seen.add(name)
        json.dumps(row, allow_nan=False)
        cases.append(Case(name, row["args"], row["expected"], row.get("expected_type")))
    return cases, provenance, spec


def readiness(spec: TaskSpec, case_count: int | None = None) -> dict:
    warnings = []
    if spec.interface == "stdin_stdout":
        warnings.append("stdin/stdout runner not implemented in this release")
    if spec.interface == "leetcode_method":
        warnings.append("LeetCode class-method invocation is supported for JSON arguments; custom judge behavior requires adapter")
    if spec.requires_dependencies:
        warnings.append("BigCodeBench dependency closure not audited; pin task-specific Docker image before executing")
    if case_count is None:
        warnings.append("Independently reviewed development cases are missing")
    return {"task": spec.task_id, "interface": spec.interface,
            "development_cases": case_count, "ready": not warnings, "warnings": warnings}
