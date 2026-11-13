"""Read-only development evaluator: unified metrics and failure records."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
from dataclasses import asdict
from uuid import uuid4
import json
import time
from .models import Case, TaskSpec, CostLedger, result_matches, canonical, sha256_text
from .adapters import public_task, load_development_suite, readiness
from .candidates import discover, static_check
from .sandbox import DockerSandbox, MAX_CASES_PER_BATCH


def batches(rows, n):
    for index in range(0, len(rows), n):
        yield rows[index:index+n]


def evaluate(root: Path, dataset: str, task_id: str, runs: list[str],
             sandbox: DockerSandbox, *, cases_path: str | None = None,
             batch_size: int = 10, include_diagnostics: bool = False,
             execute: bool = True, output_path: str | None = None) -> dict:
    root = root.resolve()
    if not 1 <= batch_size <= MAX_CASES_PER_BATCH:
        raise ValueError(f"Batch size must be in 1..{MAX_CASES_PER_BATCH}")
    spec = public_task(root, dataset, task_id)
    candidates = discover(root, runs, task_id, include_diagnostics=include_diagnostics)
    try:
        cases, provenance, spec = load_development_suite(root, spec, cases_path)
    except FileNotFoundError:
        if execute:
            raise
        cases, provenance = [], "missing_independent_development_suite"
    status = readiness(spec, len(cases) if cases else None)
    summary = {"suite": "independently_reviewed_development", "official_or_held_out": False,
               "schema_version": "2d.1", "task_id": task_id, "dataset": dataset,
               "interface": spec.interface, "task_spec": asdict(spec),
               "development_suite_provenance": provenance,
               "development_suite_sha256": sha256_text(canonical([asdict(c) for c in cases])),
               "candidate_count": len(candidates), "case_count": len(cases),
               "readiness": status, "created_utc": datetime.now(timezone.utc).isoformat(),
               "sandbox_image": sandbox.image, "case_timeout_seconds": sandbox.timeout,
               "results": []}
    for item in candidates:
        ok, error = static_check(item.code, spec.entry_point, spec.interface)
        summary["results"].append({"candidate": str(item.path.relative_to(root)),
            "method": item.method, "code_sha256": item.sha256,
            "status": "pending" if ok else "static_error", "static_error": error,
            "diagnostic": bool(item.metadata.get("diagnostic_only") or
                               item.metadata.get("source") == "synthetic_fault_injection")})
    if not execute:
        summary["execution_skipped"] = True
        return summary
    if spec.interface not in ("callable", "leetcode_method"):
        raise RuntimeError(f"Cannot run task interface yet: {spec.interface}")
    if spec.requires_dependencies:
        raise RuntimeError("BigCodeBench requires a pinned, audited dependency image. "
                           "Do not run dependency-heavy tasks in the minimal runner.")
    sandbox.ensure_ready()
    ledger = CostLedger()
    for result, candidate in zip(summary["results"], candidates):
        if result["status"] == "static_error":
            continue
        raw = []
        start = time.perf_counter()
        try:
            for part in batches(cases, batch_size):
                response, duration = sandbox.run(candidate.code, spec.entry_point,
                    spec.interface, [{"args": case.args} for case in part])
                ledger.record_executions("candidate", len(part), duration)
                raw.extend(response)
            checks = []
            for case, observed in zip(cases, raw):
                passed = result_matches(observed, case, spec)
                checks.append({"name": case.name, "input_sha256": sha256_text(canonical(case.args)),
                               "args": case.args, "expected": case.expected,
                               "actual": observed, "passed": passed,
                               "failure_type": None if passed else
                               ("wrong_answer" if observed.get("status") == "ok"
                                else observed.get("status", "unknown"))})
            result.update(status="evaluated", passed=sum(x["passed"] for x in checks),
                          total=len(checks), all_passed=all(x["passed"] for x in checks),
                          failures=dict(Counter(x["failure_type"] for x in checks if not x["passed"])),
                          checks=checks, wall_seconds=round(time.perf_counter()-start, 3))
        except (RuntimeError, OSError, ValueError) as exc:
            result.update(status="infrastructure_error", error=str(exc)[:500])
    summary["ledger"] = ledger.snapshot()
    summary["limits"] = {"candidate_executions_match_budget": False,
                           "private_oracle_access": False,
                           "notes": "Reviewed expected answers only; no protected tests read."}
    if output_path:
        path = (root / output_path).resolve()
        if not path.is_relative_to(root / "results"):
            raise ValueError("Reports must be inside project results/")
    else:
        tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
        path = root / "results" / "phase2d" / (task_id.replace("/", "_") + "_" + tag + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    summary["report_path"] = str(path)
    return summary
