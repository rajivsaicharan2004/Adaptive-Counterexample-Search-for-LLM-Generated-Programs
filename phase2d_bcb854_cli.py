#!/usr/bin/env python3
"""Review-only BigCodeBench/854 adapter. Executes NO candidate code until
--execute is explicitly requested AFTER split manifest freeze and suite review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from phase2d.bcb854 import (TASK_ID, ENTRY_POINT, compare,
    conservative_source_review, independently_derived_expectation)
from phase2d.candidates import discover, static_check
from phase2d.sandbox import DockerSandbox

ROOT = Path(__file__).resolve().parent
PROPOSAL = ROOT / "proposals" / "bcb854_review.json"
REVIEWED = ROOT / "data" / "development" / "bigcodebench" / "BigCodeBench_854.json"
MANIFEST = ROOT / "results" / "phase2d" / "splits.json"


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_state() -> tuple[str, str, str]:
    if not MANIFEST.is_file():
        return "missing", "missing", "missing"
    data = json_load(MANIFEST)
    entry = data.get("tasks", {}).get(TASK_ID, {})
    partition = entry.get("partition", "missing") if isinstance(entry, dict) else "missing"
    return str(data.get("status", "missing")), str(partition), sha256(MANIFEST.read_bytes()).hexdigest()


def validate_reviewed(raw: dict) -> list[dict]:
    if raw.get("task_id") != TASK_ID:
        raise ValueError("Wrong task ID in suite")
    if raw.get("provenance") != "independently_reviewed_development":
        raise ValueError("Only explicitly reviewed development suites may be evaluated")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 100:
        raise ValueError("Reviewed suite must contain 1..100 cases")
    names = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("args"), list) or len(case["args"]) != 1:
            raise ValueError("Each case must contain exactly one JSON-serializable argument")
        if not isinstance(case.get("expected"), dict):
            raise ValueError("Each case must specify an expected outcome")
        if case.get("name") in names or not isinstance(case.get("name"), str):
            raise ValueError("Case names must be unique strings")
        names.add(case["name"])
        if case["expected"] != independently_derived_expectation(case["args"][0]):
            raise ValueError("Reviewed case differs from independent bounded oracle")
        json.dumps(case, allow_nan=False)
    return cases


def check_only() -> None:
    state, partition, fingerprint = manifest_state()
    print("Task:", TASK_ID)
    print("Manifest status:", state)
    print("Assigned partition:", partition)
    print("Manifest SHA256:", fingerprint)
    print("Proposed suite:", PROPOSAL.relative_to(ROOT))
    if PROPOSAL.is_file():
        proposal = json_load(PROPOSAL)
        print("Proposed cases:", len(proposal.get("cases", [])))
        print("Proposed provenance:", proposal.get("provenance"))
    else:
        print("Proposed suite: MISSING")
    print("Reviewed suite:", "present" if REVIEWED.is_file() else "MISSING")
    print("NO generated candidate execution, Docker, network, or model call.")
    if state != "frozen":
        print("EXECUTION BLOCKED: split manifest remains under review.")


def execute(runs: list[str], batch_size: int) -> None:
    # phase2d_quarantine_guard:v1
    from phase2d_quarantine_guard import require_task_permission
    require_task_permission(ROOT, TASK_ID, 'evaluate')
    status, partition, fingerprint = manifest_state()
    if status != "frozen" or partition != "development":
        raise SystemExit("BLOCKED: requires frozen manifest and development partition. Draft unchanged.")
    if not REVIEWED.is_file():
        raise SystemExit("BLOCKED: reviewed suite is missing. Proposed cases do not authorize execution.")
    rows = validate_reviewed(json_load(REVIEWED))
    if not 1 <= batch_size <= 20:
        raise SystemExit("Batch size must be 1..20")
    candidates = discover(ROOT, runs, TASK_ID)
    if not candidates:
        raise SystemExit("No BigCodeBench/854 candidates found")
    sandbox = DockerSandbox()
    sandbox.ensure_ready()
    results = []
    ledger = {"candidate_executions": 0, "model_calls": 0}
    for item in candidates:
        valid, problem = static_check(item.code, ENTRY_POINT, "callable")
        out = {"candidate": str(item.path.relative_to(ROOT)), "method": item.method,
               "source_sha256": item.sha256}
        if not valid:
            out.update(status="static_error", error=problem)
            results.append(out)
            continue
        flags = conservative_source_review(item.code)
        if flags:
            out.update(status="blocked_static_side_effect_risk", reasons=flags)
            results.append(out)
            continue
        # This AST gate is not a security proof. Docker is network-disabled,
        # but a human source review and hardened VM are still recommended.
        checks = []
        for offset in range(0, len(rows), batch_size):
            chunk = rows[offset:offset + batch_size]
            actual, elapsed = sandbox.run(item.code, ENTRY_POINT, "callable",
                [{"args": row["args"]} for row in chunk], describe_types=True)
            ledger["candidate_executions"] += len(chunk)
            for row, got in zip(chunk, actual):
                checks.append({"name": row["name"], "result": compare(got, row["expected"]),
                               "observed": got})
        out.update(status="evaluated", checks=checks,
                   semantic_passed=sum(x["result"]["semantic_pass"] for x in checks),
                   strict_passed=sum(x["result"]["strict_pass"] for x in checks),
                   total=len(checks))
        results.append(out)
    report = {"schema_version": "bcb854.dev.1", "official_evaluation": False,
              "task_id": TASK_ID, "manifest_sha256": fingerprint,
              "suite_sha256": sha256(REVIEWED.read_bytes()).hexdigest(),
              "generated_utc": datetime.now(timezone.utc).isoformat(),
              "ledger": ledger, "results": results}
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    location = ROOT / "results" / "phase2d" / f"BigCodeBench_854_development_{tag}.json"
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in results:
        print(row["candidate"], row.get("status"), row.get("semantic_passed"),
              row.get("strict_passed"), "/", row.get("total"))
    print("DEVELOPMENT ONLY. Report:", location)


def main() -> None:
    ap = argparse.ArgumentParser(description="BigCodeBench/854 offline proposal review or approved development execution")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--review", action="store_true", help="Read-only manifest and proposed-suite report (default)")
    group.add_argument("--execute", action="store_true", help="Requires frozen development manifest and reviewed suite")
    ap.add_argument("--runs", nargs="+", help="Phase 1 run directories, only for --execute")
    ap.add_argument("--batch-size", type=int, default=10)
    args = ap.parse_args()
    if args.execute:
        if not args.runs:
            ap.error("--execute requires --runs")
        execute(args.runs, args.batch_size)
    else:
        check_only()


if __name__ == "__main__":
    main()
