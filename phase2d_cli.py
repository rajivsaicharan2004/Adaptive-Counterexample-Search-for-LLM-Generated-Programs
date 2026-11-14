#!/usr/bin/env python3
"""Unified development evaluator. Run from the project root."""
import argparse
from pathlib import Path
from collections import defaultdict
from phase2d.engine import evaluate
from phase2d.sandbox import DockerSandbox
from phase2d.adapters import public_task, readiness, load_development_suite

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description="Phase 2D unified development evaluator")
    p.add_argument("--dataset", choices=("humaneval", "mbpp", "bigcodebench", "livecodebench"), required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--runs", nargs="+", help="Saved Phase 1 run directories")
    p.add_argument("--cases-file", help="Independently reviewed development suite JSON")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--include-diagnostics", action="store_true", help="Explicit diagnostic opt-in")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--readiness", action="store_true", help="Report evaluation readiness without candidates")
    p.add_argument("--splits-file", default="results/phase2d/splits.json", help="Optional task partition manifest")
    args = p.parse_args()
    if args.readiness:
        spec = public_task(ROOT, args.dataset, args.task_id)
        try:
            cases, provenance, spec = load_development_suite(ROOT, spec, args.cases_file)
        except FileNotFoundError:
            cases, provenance = None, "missing"
        state = readiness(spec, len(cases) if cases is not None else None)
        print(f"Task: {args.task_id} | interface: {spec.interface}")
        print(f"Reviewed cases: {len(cases) if cases is not None else 'MISSING'}")
        print(f"Provenance: {provenance}")
        for warning in state["warnings"]:
            print("BLOCKER:", warning)
        print("READY" if state["ready"] else "NOT READY")
        return
    # phase2d_quarantine_guard:v1
    from phase2d_quarantine_guard import require_task_permission
    require_task_permission(ROOT, args.task_id, 'evaluate')
    split_file = (ROOT / args.splits_file).resolve()
    if split_file.is_file():
        import json
        manifest = json.loads(split_file.read_text(encoding="utf-8"))
        task = manifest.get("tasks", {}).get(args.task_id)
        if not task or task.get("partition") != "development":
            p.error("Requested task is not assigned to the DEVELOPMENT partition. "
                    "Do not tune using validation or held-out tasks.")
        if manifest.get("status") != "frozen" and args.task_id not in ("HumanEval/0", "HumanEval/1", "MBPP/545"):
            p.error("Split manifest is still a draft. Only the three existing pilot tasks "
                    "may be evaluated before the manifest is reviewed and frozen.")
        print("Split manifest:", split_file.relative_to(ROOT), "| partition: development")
    else:
        print("CAUTION: no frozen split manifest found; using pilot development suites only")
    if not args.runs:
        p.error("--runs required unless --readiness is used")
    report = evaluate(ROOT, args.dataset, args.task_id, args.runs, DockerSandbox(),
                      cases_path=args.cases_file, batch_size=args.batch_size,
                      include_diagnostics=args.include_diagnostics,
                      execute=not args.dry_run)
    print(f"Task: {report['task_id']} | cases: {report['case_count']} | "
          f"candidates: {report['candidate_count']}")
    for item in report["results"]:
        score = (f"{item['passed']}/{item['total']}" if item["status"] == "evaluated"
                 else item["status"])
        print(f"  {Path(item['candidate']).name:22s} {score}")
    if args.dry_run:
        print("DRY RUN: no Docker, no model calls, no private tests")
    else:
        print("Ledger:", report["ledger"])
        print("Saved:", report["report_path"])
        print("DEVELOPMENT ONLY: not an official benchmark score")


if __name__ == "__main__":
    main()
