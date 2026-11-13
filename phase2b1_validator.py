#!/usr/bin/env python3
"""Phase 2B-1: Hypothesis-generated development inputs, validated in Phase 2A Docker.

Supported tasks: HumanEval/0 and HumanEval/1.
This script does NOT execute generated programs on the host or access hidden tests.
It reuses phase2a_validator.py's reference loader and isolated Docker executor.
"""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import hypothesis
from hypothesis import given, settings, strategies as st

import phase2a_validator as base

ROOT = Path(__file__).resolve().parent
SUPPORTED_TASKS = ("HumanEval/0", "HumanEval/1")


@st.composite
def close_elements_args(draw):
    """Valid, finite, modest-size numerical inputs with targeted threshold cases."""
    quarters = draw(st.lists(st.integers(-120, 120), min_size=0, max_size=12))
    numbers = [x / 4.0 for x in quarters]
    mode = draw(st.sampled_from(("regular", "zero", "pair_boundary", "near_pair")))
    if mode == "zero":
        threshold = 0.0
    elif mode in ("pair_boundary", "near_pair") and len(numbers) >= 2:
        i = draw(st.integers(0, len(numbers) - 1))
        j = draw(st.integers(0, len(numbers) - 2))
        if j >= i:
            j += 1
        distance = abs(numbers[i] - numbers[j])
        delta = (
            draw(st.sampled_from((-0.25, 0.0, 0.25)))
            if mode == "near_pair"
            else 0.0
        )
        threshold = max(0.0, distance + delta)
    else:
        threshold = draw(st.integers(0, 120)) / 4.0
    return [numbers, float(threshold)]


PAREN_GROUP = st.recursive(
    st.just("()"),
    lambda children: st.lists(children, min_size=1, max_size=3).map(
        lambda parts: "(" + "".join(parts) + ")"
    ),
    max_leaves=12,
)


@st.composite
def separate_paren_args(draw):
    """Generate one or more disjoint balanced groups with optional spaces."""
    groups = draw(st.lists(PAREN_GROUP, min_size=1, max_size=4))
    raw = "".join(groups)
    spaces = draw(
        st.lists(
            st.integers(0, 2),
            min_size=len(raw) + 1,
            max_size=len(raw) + 1,
        )
    )
    text = "".join(" " * spaces[i] + char for i, char in enumerate(raw))
    return [text + " " * spaces[-1]]


def generate_cases(task_id, requested):
    """Collect Hypothesis-generated valid inputs (no oracle or Docker calls yet)."""
    strategy = (
        close_elements_args()
        if task_id == "HumanEval/0"
        else separate_paren_args()
    )
    unique = {}

    @settings(max_examples=requested, derandomize=True, deadline=None, database=None)
    @given(args=strategy)
    def collect(args):
        key = json.dumps(
            args,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        unique.setdefault(key, args)

    collect()
    return [
        {"name": f"hypothesis_{i:04d}", "args": args}
        for i, args in enumerate(unique.values(), 1)
    ]


def batches(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def check_candidate(path, task_id, entry, cases, oracle, batch_size):
    report = {"candidate": str(path.relative_to(ROOT)), "task_id": task_id}
    try:
        code = path.read_text(encoding="utf-8")
        tree = ast.parse(code)
        functions = {
            node.name for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if entry not in functions:
            raise ValueError(f"Expected top-level function {entry!r} was not found")

        checks = []
        for case_batch, oracle_batch in zip(
            batches(cases, batch_size),
            batches(oracle, batch_size),
        ):
            inputs = [
                {"entry_point": entry, "args": case["args"]}
                for case in case_batch
            ]
            actual = base.docker_execute(code, inputs)
            for case, trusted, got in zip(case_batch, oracle_batch, actual):
                correct = base.matching_result(
                    got,
                    trusted["value"],
                    trusted["type"],
                )
                status = got.get("status")
                checks.append({
                    "name": case["name"],
                    "input": case["args"],
                    "expected": trusted["value"],
                    "actual": got,
                    "passed": correct,
                    "failure_type": None if correct else (
                        "wrong_answer" if status == "ok" else status or "unknown"
                    ),
                })

        report.update(
            status="evaluated",
            passed=sum(check["passed"] for check in checks),
            total=len(checks),
            all_passed=all(check["passed"] for check in checks),
            tests=checks,
        )
    except (SyntaxError, ValueError, UnicodeError) as exc:
        report.update(status="static_error", error=str(exc))
    except (RuntimeError, OSError) as exc:
        report.update(status="infrastructure_error", error=str(exc))
    return report


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Phase 2B-1: Hypothesis-generated development testing "
            "using Phase 2A Docker."
        )
    )
    parser.add_argument("--task-id", choices=SUPPORTED_TASKS, required=True)
    parser.add_argument(
        "--runs",
        nargs="+",
        required=True,
        help="Saved Phase 1 run directories",
    )
    parser.add_argument(
        "--cases",
        type=int,
        default=40,
        help="Hypothesis generation budget (default: 40)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Test inputs per isolated Docker batch (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate inputs and list candidates, but do not run Docker",
    )
    parser.add_argument(
        "--include-diagnostics",
        action="store_true",
        help="Explicitly allow synthetic diagnostic candidates",
    )
    args = parser.parse_args()
    if not 1 <= args.cases <= 500:
        parser.error("--cases must be between 1 and 500")
    if not 1 <= args.batch_size <= 20:
        parser.error("--batch-size must be between 1 and 20")

    try:
        files = base.candidate_files(args.runs, args.task_id)
        if not files:
            parser.error("No candidate files found")
        if not args.include_diagnostics:
            for path in files:
                meta = json.loads(
                    path.with_suffix(".json").read_text(encoding="utf-8")
                )
                if (
                    meta.get("diagnostic_only")
                    or meta.get("source") == "synthetic_fault_injection"
                ):
                    parser.error(
                        "Diagnostic candidate excluded. "
                        "Use --include-diagnostics to test it."
                    )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    cases = generate_cases(args.task_id, args.cases)
    print(f"Task: {args.task_id}")
    print(f"Candidates: {len(files)}")
    print(f"Hypothesis requested examples: {args.cases}")
    print(f"Unique valid generated inputs: {len(cases)}")
    for path in files:
        print(" -", path.relative_to(ROOT))
    if args.dry_run:
        print("DRY RUN: no Docker containers started, no reference solutions loaded.")
        return

    output = ROOT / "results" / "phase2b"
    output.mkdir(parents=True, exist_ok=True)
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_" + uuid4().hex[:6]
    )
    prefix = args.task_id.replace("/", "_").lower() + "_" + run_id
    input_file = output / f"{prefix}_inputs.json"
    input_payload = {
        "task_id": args.task_id,
        "source": "hypothesis_generated_development",
        "requested_examples": args.cases,
        "actual_unique_examples": len(cases),
        "hypothesis_version": hypothesis.__version__,
        "cases": cases,
    }
    input_file.write_text(
        json.dumps(input_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    digest = hashlib.sha256(input_file.read_bytes()).hexdigest()
    print("Saved input corpus:", input_file.relative_to(ROOT))

    base.ensure_docker()
    reference, entry = base.load_reference(args.task_id)
    oracle = []
    print(f"Running reference oracle on {len(cases)} generated development inputs...")
    for batch in batches(cases, args.batch_size):
        inputs = [
            {"entry_point": entry, "args": case["args"]}
            for case in batch
        ]
        batch_outputs = base.docker_execute(reference, inputs)
        for case, result in zip(batch, batch_outputs):
            if result.get("status") != "ok":
                raise RuntimeError(
                    f"Reference oracle failed on {case['name']}: {result}. "
                    "Review input contract before candidate scoring."
                )
        oracle.extend(batch_outputs)

    reports = []
    for path in files:
        report = check_candidate(
            path,
            args.task_id,
            entry,
            cases,
            oracle,
            args.batch_size,
        )
        reports.append(report)
        if report["status"] == "evaluated":
            print(f"{path.name:20s} {report['passed']:3}/{report['total']} passed")
        else:
            print(f"{path.name:20s} {report['status']}: {report['error']}")

    report_file = output / f"{prefix}_report.json"
    report_file.write_text(
        json.dumps({
            "task_id": args.task_id,
            "suite": "hypothesis_generated_development",
            "oracle": "HumanEval canonical reference in separate Docker execution",
            "hypothesis_version": hypothesis.__version__,
            "requested_examples": args.cases,
            "unique_cases": len(cases),
            "batch_size": args.batch_size,
            "input_file": str(input_file.relative_to(ROOT)),
            "input_file_sha256": digest,
            "candidate_count": len(files),
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "docker_image": base.IMAGE,
            "results": reports,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("Saved report:", report_file.relative_to(ROOT))
    print("These are DEVELOPMENT results, not official or held-out benchmark scores.")
    print(
        "Phase 2B-1 covers property-based input generation + oracle checking; "
        "shrinking, mutation, differential, and metamorphic methods come next."
    )


if __name__ == "__main__":
    main()
