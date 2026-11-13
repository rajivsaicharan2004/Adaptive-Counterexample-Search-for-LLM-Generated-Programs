#!/usr/bin/env python3
"""Development-only offline baselines and genuine-candidate failure corpus.

Replays recorded first-hit costs. It does NOT create new counterexamples and
is NOT independent evaluation. Never include synthetic diagnostics in the
'genuine failures' export.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import random

ROOT = Path(__file__).resolve().parent
METHODS = ("property", "mutation", "differential", "metamorphic")


def simulate(first_costs: dict, total_budget: int, policy: str, seed: int) -> dict:
    """Replay fixed ordered traces with action costs 1 or 2.

    Assumption: pre-generated method-specific input sequences are invariant to
    interleaving. This is a retrospective simulator, NOT an online controller.
    """
    rng = random.Random(seed)
    spent = {m: 0 for m in METHODS}
    prices = {"property":1, "mutation":1, "differential":2, "metamorphic":2}
    remaining = total_budget
    round_index = 0
    while remaining:
        possible = [m for m in METHODS if prices[m] <= remaining]
        if not possible:
            break
        if policy.startswith("fixed_"):
            method = policy.removeprefix("fixed_")
            if method not in possible:
                break
        elif policy == "round_robin":
            method = next((METHODS[(round_index+i) % len(METHODS)]
                           for i in range(len(METHODS))
                           if METHODS[(round_index+i) % len(METHODS)] in possible),None)
            round_index = (METHODS.index(method)+1) % len(METHODS)
        elif policy == "random":
            method = rng.choice(possible)
        else:
            raise ValueError("Unknown policy")
        amount = prices[method]
        spent[method] += amount
        remaining -= amount
        earliest = first_costs.get(method)
        if earliest is not None and spent[method] >= earliest:
            return {"detected":True,"first_failure_total_cost":total_budget-remaining,
                    "executions_by_method":spent,"policy":policy}
    return {"detected":False,"first_failure_total_cost":None,
            "executions_by_method":spent,"policy":policy}


def replay_fault_benchmark(reports_dir: Path, out_dir: Path, budgets: list[int], seed: int) -> None:
    reports = sorted(reports_dir.glob("fault_benchmark_*_report.json"))
    runs = []
    for path in reports:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("suite") != "synthetic_fault_detection_development" or raw.get("official_or_held_out") is not False:
            continue
        if len(raw.get("mutants",[])) != 10:
            continue
        runs.append((path,raw))
    if not runs:
        raise ValueError("No two-task synthetic development benchmark reports found")
    # One latest report per seed and execution cap: don't double-count repeats.
    by_key = {}
    for path,doc in runs:
        key = (doc["seed"],doc["candidate_executions_per_mutant_per_method"])
        by_key[key] = (path,doc)
    policies = tuple("fixed_"+m for m in METHODS) + ("round_robin","random")
    all_rows=[]
    for (source_seed, cap), (path,doc) in sorted(by_key.items()):
        for mutant in doc["mutants"]:
            costs = {name:r["first_verified_failure_at_candidate_executions"]
                     for name,r in mutant["methods"].items()}
            for budget in budgets:
                if budget > cap:
                    continue
                for policy in policies:
                    sim = simulate(costs,budget,policy,seed+source_seed)
                    all_rows.append({"source_seed":source_seed,"task_id":mutant["task_id"],
                                     "mutant_id":mutant["mutant_id"],"budget":budget,
                                     "policy":policy,"detected":int(sim["detected"]),
                                     "first_failure_cost":sim["first_failure_total_cost"] or "",
                                     "source_report":str(path)})
    out_dir.mkdir(parents=True,exist_ok=True)
    target=out_dir/"offline_baselines.csv"
    with target.open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(all_rows[0]))
        writer.writeheader(); writer.writerows(all_rows)
    grouped=defaultdict(list)
    for row in all_rows:
        grouped[(row["budget"],row["policy"])].append(row["detected"])
    print("Retrospective synthetic-mutant detection rates (NOT held-out evaluation)")
    for budget in budgets:
        print(f"  Budget {budget}:"," | ".join(
            f"{policy}={sum(grouped[(budget,policy)])/len(grouped[(budget,policy)]):.2f}"
            for policy in policies if grouped[(budget,policy)]))
    print("Saved:",target)
    print("Limitations: unchanged method-specific input orders, no oracle-cost matching, "
          "reused mutants, different signals; simulation only.")


def export_genuine_failures(reports_dir: Path, out: Path) -> None:
    rows=[]
    for path in sorted(reports_dir.glob("*.json")):
        try:
            data=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):
            continue
        if data.get("suite") != "independently_reviewed_development" or data.get("official_or_held_out") is not False:
            continue
        for item in data.get("results",[]):
            if item.get("diagnostic") or item.get("status") != "evaluated":
                continue
            failed=[x for x in item.get("checks",[]) if not x.get("passed")]
            if not failed:
                continue
            rows.append({"task_id":data["task_id"],"candidate":item["candidate"],
                         "method":item["method"],"code_sha256":item["code_sha256"],
                         "case_count":item["total"],"failed_cases":len(failed),
                         "failure_types":sorted({x["failure_type"] for x in failed}),
                         "source_report":str(path),"synthetic":False,
                         "held_out":False})
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row,ensure_ascii=False)+"\n")
    print(f"Exported {len(rows)} genuine candidate failure records to {out}")
    print("Development-only. Absence of failures is NOT evidence of benchmark correctness.")


def main():
    p=argparse.ArgumentParser(description="Phase 2D development experiment tools")
    sub=p.add_subparsers(dest="command",required=True)
    r=sub.add_parser("offline-baselines")
    r.add_argument("--reports-dir",default="results/phase2b")
    r.add_argument("--out-dir",default="results/phase2d")
    r.add_argument("--budgets",nargs="+",type=int,default=[4,10,20,40])
    r.add_argument("--seed",type=int,default=2026)
    e=sub.add_parser("export-real-failures")
    e.add_argument("--reports-dir",default="results/phase2d")
    e.add_argument("--output",default="results/phase2d/genuine_failure_corpus.jsonl")
    args=p.parse_args()
    if args.command=="offline-baselines":
        replay_fault_benchmark(ROOT/args.reports_dir,ROOT/args.out_dir,args.budgets,args.seed)
    else:
        export_genuine_failures(ROOT/args.reports_dir,ROOT/args.output)


if __name__=="__main__":
    main()
