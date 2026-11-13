#!/usr/bin/env python3
"""Replay a saved PILOT corpus on a candidate using the standardized Docker runner."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
from uuid import uuid4
import argparse
import json
import time
from phase2d.adapters import public_task
from phase2d.candidates import discover
from phase2d.models import Case, CostLedger, result_matches
from phase2d.oracles import development_oracle
from phase2d.strategies import valid_args, SUPPORTED
from phase2d.sandbox import DockerSandbox

ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description="Replay an existing Phase 2D strategy input corpus")
    p.add_argument("--report",required=True)
    p.add_argument("--run",required=True)
    p.add_argument("--batch-size",type=int,default=10)
    args=p.parse_args()
    if not 1<=args.batch_size<=20:p.error("batch-size must be 1..20")
    src=(ROOT/args.report).resolve()
    if not src.is_relative_to((ROOT/"results/phase2d").resolve()):
        p.error("Source report must be under results/phase2d")
    payload=json.loads(src.read_text(encoding="utf-8"))
    task=payload.get("task_id")
    if (payload.get("suite")!="pilot_strategy_development" or
        payload.get("official_or_held_out") is not False or task not in SUPPORTED):
        p.error("Expected a supported development-only strategy report")
    inputs=payload.get("inputs")
    if not isinstance(inputs,list) or not inputs or any(not valid_args(task,x) for x in inputs):
        p.error("Missing/invalid saved corpus")
    dataset="mbpp" if task.startswith("MBPP/") else "humaneval"
    spec=public_task(ROOT,dataset,task)
    candidate=discover(ROOT,[args.run],task)[0]
    ledger=CostLedger()
    sandbox=DockerSandbox();sandbox.ensure_ready()
    counts=Counter();first=[]
    for start in range(0,len(inputs),args.batch_size):
        group=inputs[start:start+args.batch_size]
        values,elapsed=sandbox.run(candidate.code,spec.entry_point,spec.interface,
                                    [{"args":x} for x in group])
        ledger.record_executions("candidate",len(group),elapsed)
        for offset,(input_value,got) in enumerate(zip(group,values)):
            begin=time.perf_counter()
            expected=development_oracle(task,input_value)
            ledger.record_executions("reference",1,time.perf_counter()-begin)
            passed=result_matches(got,Case("replay",input_value,expected),spec)
            counts["pass" if passed else "failure"]+=1
            if not passed and len(first)<5:
                first.append({"index":start+offset,"args":input_value,
                              "actual":got,"expected":expected})
    report={"suite":"pilot_development_replay","official_or_held_out":False,
            "source_corpus":str(src.relative_to(ROOT)),"task_id":task,
            "candidate":str(candidate.path.relative_to(ROOT)),
            "candidate_sha256":candidate.sha256,"cases":len(inputs),
            "passed":counts["pass"],"failed":counts["failure"],
            "ledger":ledger.snapshot(),"first_five_failures":first}
    dest=ROOT/"results/phase2d"/f"replay_{task.replace('/','_')}_{uuid4().hex[:8]}.json"
    dest.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(f"Replayed {len(inputs)} inputs: {counts['pass']} passed, {counts['failure']} failed")
    print("Saved:",dest.relative_to(ROOT))
    print("DEVELOPMENT-only replay")


if __name__=="__main__":main()
