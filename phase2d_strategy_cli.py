#!/usr/bin/env python3
"""Phase 2D PILOT strategies with explicit budgets, oracle provenance, and JSON reports.

DO NOT use on held-out benchmark tasks. Only 3 manually reviewed pilot specs.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import os
import time

from phase2d.models import CostLedger, Case, result_matches
from phase2d.adapters import public_task, load_development_suite
from phase2d.candidates import discover
from phase2d.sandbox import DockerSandbox
from phase2d import strategies
from phase2d.oracles import development_oracle

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description="PILOT testing strategies (development only)")
    p.add_argument("--dataset", choices=("humaneval", "mbpp"), required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--runs", nargs="+", required=True, help="First run provides target candidate; second provides probe")
    p.add_argument("--method", choices=("property", "mutation", "metamorphic", "coverage", "differential", "llm"), required=True)
    p.add_argument("--budget", type=int, default=20, help="Maximum candidate/probe executions (or input-generation limit in dry-run)")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--max-model-calls", type=int, default=0,
                   help="Explicitly opt in to one LLM test-generation call")
    p.add_argument("--model", help="Gemini model ID; defaults to .env setting")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.task_id not in strategies.SUPPORTED:
        p.error("Pilot strategies only support HumanEval/0, HumanEval/1, MBPP/545; add reviewed contract first")
    if not 2 <= args.budget <= 200:
        p.error("Budget must be 2..200")
    if not 1 <= args.batch_size <= 20:
        p.error("Batch size must be 1..20")
    spec = public_task(ROOT, args.dataset, args.task_id)
    reviewed, provenance, spec = load_development_suite(ROOT, spec)
    candidates = discover(ROOT, args.runs, args.task_id)
    target = candidates[0]
    probe = candidates[1] if len(candidates) >= 2 else None
    if args.method == "differential" and probe is None:
        p.error("Differential testing requires at least two candidates across --runs")
    seeds = [c.args for c in reviewed if strategies.valid_args(args.task_id, c.args)]
    if not seeds:
        p.error("No valid development seeds")
    ledger = CostLedger()
    count = args.budget if args.method in ("property", "mutation", "coverage", "llm") else args.budget // 2
    if args.method in ("property", "differential", "metamorphic"):
        initial = strategies.property_inputs(args.task_id, count if args.method == "property" else max(3,count), args.seed)
    elif args.method in ("mutation", "coverage"):
        initial = strategies.mutation_inputs(args.task_id, seeds, count, args.seed)
    elif args.method == "llm":
        if args.max_model_calls < 1:
            p.error("LLM testing requires explicit --max-model-calls 1")
        if args.dry_run:
            print("DRY RUN: would request 1 public-prompt-only LLM test generation call")
            return
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from google import genai
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            p.error("Gemini API key missing in .env")
        model = args.model or os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
        llm = strategies.llm_test_inputs(spec, count, genai.Client(api_key=key), model, ledger)
        initial = llm["inputs"]
    if args.method == "metamorphic":
        pairs = strategies.metamorphic_pairs(args.task_id, initial, count, args.seed)
        inputs = [v for pair in pairs for v in (pair["base_args"], pair["followup_args"])]
    else:
        pairs = []
        inputs = initial
    print(f"Task: {spec.task_id} | method: {args.method} | budget: {args.budget}")
    print(f"Candidate: {target.path.name} | input count: {len(inputs)}")
    if args.dry_run:
        print("Sample inputs:", inputs[:3])
        print("No Docker or private data accessed")
        return
    sandbox = DockerSandbox()
    sandbox.ensure_ready()
    details = {}
    if args.method == "coverage":
        details = strategies.coverage_guided_inputs(spec.task_id, target.code, spec.entry_point,
                  spec.interface, seeds, sandbox, ledger, budget=count, seed_value=args.seed)
    elif args.method == "differential":
        details = strategies.disagreement_rank(target.code, probe.code, spec.entry_point,
                  spec.interface, inputs, sandbox, ledger, max_executions=args.budget)
        confirmed = []
        for row in details["disagreements"]:
            expected = development_oracle(spec.task_id, row["args"])
            ledger.record_executions("reference", 1, 0)
            if row["candidate"].get("status") != "ok" or row["candidate"].get("value") != expected:
                confirmed.append(row["args"])
        details["reference_confirmed_target_disagreements"] = confirmed
    else:
        observed = []
        for index in range(0, len(inputs), args.batch_size):
            part = inputs[index:index+args.batch_size]
            got, elapsed = sandbox.run(target.code, spec.entry_point, spec.interface,
                                        [{"args": x} for x in part])
            ledger.record_executions("candidate", len(part), elapsed)
            observed.extend(got)
        mismatches = []
        for i, (input_args, got) in enumerate(zip(inputs, observed)):
            started = time.perf_counter()
            expected = development_oracle(spec.task_id, input_args)
            ledger.record_executions("reference", 1, time.perf_counter()-started)
            if not result_matches(got, Case(f"case_{i}", input_args, expected), spec):
                mismatches.append({"case_index": i, "args": input_args,
                                   "actual": got, "expected": expected})
        details = {"oracle_confirmed_wrong_executions": len(mismatches),
                   "first_five_counterexamples": mismatches[:5], "total_cases": len(inputs)}
        if pairs:
            import phase2b4_metamorphic as mr
            violations = 0
            invalid_reference_relations = 0
            for i, pair in enumerate(pairs):
                if mr.relation_holds(observed[2*i], observed[2*i+1],
                                     pair["relation"], pair["relation_info"]) is False:
                    violations += 1
                a = {"status":"ok", "value":development_oracle(spec.task_id,pair["base_args"]),
                     "type":type(development_oracle(spec.task_id,pair["base_args"])).__name__}
                b = {"status":"ok", "value":development_oracle(spec.task_id,pair["followup_args"]),
                     "type":type(development_oracle(spec.task_id,pair["followup_args"])).__name__}
                if mr.relation_holds(a,b,pair["relation"],pair["relation_info"]) is not True:
                    invalid_reference_relations += 1
            details["metamorphic_relation_violations"] = violations
            details["invalid_reference_relations"] = invalid_reference_relations
    outdir = ROOT / "results" / "phase2d"
    outdir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    path = outdir / f"strategy_{spec.task_id.replace('/','_')}_{args.method}_{tag}.json"
    payload = {"suite":"pilot_strategy_development", "official_or_held_out":False,
               "task_id":spec.task_id,"method":args.method,"seed":args.seed,
               "candidate_code_sha256":target.sha256,"inputs":inputs,"pairs":pairs,
               "development_oracle":"public-specification manually reviewed pilot rule",
               "ledger":ledger.snapshot(),"details":details}
    path.write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    print("Results:", {k:v for k,v in details.items() if not isinstance(v,list)})
    print("Budget ledger:",ledger.snapshot())
    print("Saved:",path.relative_to(ROOT))
    print("DEVELOPMENT ONLY; no protected evaluation scores")


if __name__ == "__main__":
    main()
