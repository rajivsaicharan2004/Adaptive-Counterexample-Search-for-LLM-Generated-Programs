#!/usr/bin/env python3
"""Summarize standard development-only evaluator reports and Phase 1 model usage."""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import csv
import json
import statistics

ROOT=Path(__file__).resolve().parent


def summarize(candidate_reports: Path, out_dir: Path):
    rows=[]
    candidate_count=Counter()
    for path in sorted(candidate_reports.glob("*.json")):
        try:
            obj=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):continue
        if obj.get("suite")!="independently_reviewed_development" or obj.get("official_or_held_out") is not False:
            continue
        for result in obj.get("results",[]):
            if result.get("diagnostic"):
                continue
            success=result.get("status")=="evaluated"
            name=result.get("method","unknown")
            row={"dataset":obj.get("dataset"),"task_id":obj.get("task_id"),
                 "method":name,"candidate":result.get("candidate"),
                 "code_sha256":result.get("code_sha256"),"status":result.get("status"),
                 "passed":result.get("passed","") if success else "",
                 "total":result.get("total","") if success else "",
                 "development_case_pass_rate":result["passed"]/result["total"] if success and result["total"] else "",
                 "all_passed_development":int(result["all_passed"]) if success else "",
                 "wall_seconds":result.get("wall_seconds","") if success else "",
                 "source_report":str(path)}
            rows.append(row)
    out_dir.mkdir(parents=True,exist_ok=True)
    output=out_dir/"candidate_development_metrics.csv"
    if rows:
        with output.open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]))
            writer.writeheader();writer.writerows(rows)
    else:
        output.write_text("dataset,task_id,method,candidate,status\n",encoding="utf-8")
    # Aggregate only per-candidate metrics, not pass@k or official success.
    groups=defaultdict(list)
    for row in rows:
        groups[(row["dataset"],row["method"])].append(row)
    summary=[]
    for (dataset,method),group in sorted(groups.items()):
        evaluated=[x for x in group if x["status"]=="evaluated"]
        rates=[x["development_case_pass_rate"] for x in evaluated]
        summary.append({"dataset":dataset,"method":method,"n_candidates":len(group),
                        "n_evaluated":len(evaluated),
                        "n_all_passed_development":sum(x["all_passed_development"] for x in evaluated),
                        "mean_development_case_pass_rate":round(statistics.mean(rates),5) if rates else "",
                        "n_distinct_code_hashes":len({x["code_sha256"] for x in group})})
    outfile=out_dir/"method_development_summary.csv"
    if summary:
        with outfile.open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    else: outfile.write_text("dataset,method,n_candidates\n",encoding="utf-8")
    print("Development candidate records:",len(rows))
    print("Saved:",output,"and",outfile)
    print("These are reviewed-development pass rates, NOT held-out accuracy or pass@k")


def phase1_tokens(root: Path, out_dir: Path):
    output=[]
    for file in sorted((root/"generated/phase1").glob("*/*.json")):
        if file.name in ("manifest.json","advanced_manifest.json"):
            continue
        try:
            data=json.loads(file.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):continue
        if not isinstance(data,dict) or data.get("method") not in (
            "direct","sampling","diverse","plan","mcts","evolution","beam","adaptive"):
            continue
        stages=data.get("stages",[])
        total={name:0 for name in ("prompt_token_count","candidates_token_count",
                                     "thoughts_token_count","total_token_count")}
        seconds=0.0
        for stage in stages:
            usage=stage.get("usage") or {}
            for name in total:
                total[name]+=usage.get(name) or 0
            seconds+=stage.get("latency_seconds") or 0
        output.append({"task_id":data.get("task_id"),"method":data.get("method"),
                       "candidate":str(file.relative_to(root)),
                       "status":data.get("status"),"api_stages_logged":len(stages),
                       "latency_seconds_sum":round(seconds,4), **total})
    out_dir.mkdir(parents=True,exist_ok=True)
    dest=out_dir/"phase1_model_usage.csv"
    if output:
        with dest.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    else:dest.write_text("task_id,method,candidate,status\n",encoding="utf-8")
    print("Phase 1 candidate metadata records:",len(output),"| saved:",dest)
    print("Token usage depends on model API reporting; unpriced stages are NOT zero-cost")


def main():
    p=argparse.ArgumentParser(description="Summarize reproducible development metrics")
    p.add_argument("--reports-dir",default="results/phase2d")
    p.add_argument("--out-dir",default="results/phase2d")
    args=p.parse_args()
    summarize(ROOT/args.reports_dir,ROOT/args.out_dir)
    phase1_tokens(ROOT,ROOT/args.out_dir)


if __name__=="__main__":main()
