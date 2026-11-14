#!/usr/bin/env python3
"""Minimize a reproducible development counterexample; every candidate run in Docker."""
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
import argparse
import json
import time
from phase2d.adapters import public_task
from phase2d.candidates import discover
from phase2d.models import Case, CostLedger, result_matches
from phase2d.oracles import development_oracle
from phase2d.strategies import shrink_failure, valid_args, SUPPORTED
from phase2d.sandbox import DockerSandbox

ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description="Docker-backed greedy development counterexample shrinking")
    p.add_argument("--dataset",choices=("humaneval","mbpp"),required=True)
    p.add_argument("--task-id",required=True)
    p.add_argument("--run",required=True)
    p.add_argument("--args-json",required=True,help='JSON positional arguments, e.g. "[[1,20,1.1],0.2]"')
    p.add_argument("--max-checks",type=int,default=40)
    p.add_argument("--include-diagnostics",action="store_true")
    args=p.parse_args()
    if args.task_id not in SUPPORTED:
        p.error("No reviewed pilot oracle/input contract for this task")
    if not 1<=args.max_checks<=1000: p.error("max-checks must be 1..1000")
    input_args=json.loads(args.args_json)
    if not valid_args(args.task_id,input_args): p.error("Input violates reviewed contract")
    # phase2d_quarantine_guard:v1
    from phase2d_quarantine_guard import require_task_permission
    require_task_permission(ROOT, args.task_id, 'evaluate')
    spec=public_task(ROOT,args.dataset,args.task_id)
    candidate=discover(ROOT,[args.run],args.task_id,include_diagnostics=args.include_diagnostics)[0]
    sandbox=DockerSandbox(); sandbox.ensure_ready()
    ledger=CostLedger(); cache={}
    def fails(input_value):
        key=json.dumps(input_value,sort_keys=True,separators=(",",":"))
        if key in cache:return cache[key]
        result,elapsed=sandbox.run(candidate.code,spec.entry_point,spec.interface,[{"args":input_value}])
        ledger.record_executions("candidate",1,elapsed)
        begin=time.perf_counter()
        expected=development_oracle(args.task_id,input_value)
        ledger.record_executions("reference",1,time.perf_counter()-begin)
        failed=not result_matches(result[0],Case("shrink_trial",input_value,expected),spec)
        cache[key]=failed
        return failed
    result=shrink_failure(args.task_id,input_args,fails,max_checks=args.max_checks)
    output=ROOT/"results/phase2d"
    output.mkdir(parents=True,exist_ok=True)
    name=f"shrink_{args.task_id.replace('/','_')}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:6]}.json"
    path=output/name
    result.update({"candidate":str(candidate.path.relative_to(ROOT)),
                   "candidate_sha256":candidate.sha256,
                   "official_or_held_out":False,"ledger":ledger.snapshot()})
    path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Original:",input_args)
    print("Minimized:",result["minimized"])
    print("Cost:",ledger.snapshot())
    print("Saved:",path.relative_to(ROOT))
    print("This is a greedy DEVELOPMENT minimization, not a proof of global minimality")


if __name__=="__main__":main()
