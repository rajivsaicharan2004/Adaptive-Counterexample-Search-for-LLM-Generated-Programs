#!/usr/bin/env python3
"""Create an auditable development/validation/holdout manifest from PUBLIC tasks.

Groups identical normalized prompts together; cannot detect all semantic
near-duplicates. LiveCodeBench is held out by default until time-based splits
are implemented using authoritative dates.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parent
DATASETS=("humaneval","mbpp","bigcodebench","livecodebench")
PINNED_DEV={"HumanEval/0","HumanEval/1","MBPP/545"}


def public_rows(root):
    rows=[]
    for dataset in DATASETS:
        direct=root/"data"/"public"/(dataset+".jsonl")
        fallback=root/"data"/"public"/"problems.jsonl"
        path=direct if direct.is_file() else fallback
        if not path.is_file():
            raise FileNotFoundError(f"Missing prepared public dataset: {dataset}")
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    rec=json.loads(line)
                    if rec.get("dataset")==dataset:
                        rows.append((dataset,rec["task_id"],rec["prompt"]))
    return rows


def generate_splits(rows, seed: int, *, holdout_livecodebench: bool = True) -> dict:
    groups=defaultdict(list)
    for dataset,task_id,prompt in rows:
        normalized=re.sub(r"\s+"," ",prompt.lower()).strip()
        fingerprint=hashlib.sha256(normalized.encode()).hexdigest()
        groups[fingerprint].append((dataset,task_id))
    assigned={}
    for digest,members in groups.items():
        # Avoid exact-prompt leakage across datasets; sticky curated pilots.
        if any(task in PINNED_DEV for _,task in members):
            split="development"
        elif holdout_livecodebench and any(ds=="livecodebench" for ds,_ in members):
            split="held_out_temporal_pending"
        else:
            value=int(hashlib.sha256(f"{seed}:{digest}".encode()).hexdigest()[:12],16)/16**12
            split="development" if value<0.2 else "validation" if value<0.4 else "held_out"
        for dataset,task in members:
            assigned[task]={"dataset":dataset,"partition":split,"public_prompt_sha256":digest}
    return {"schema_version":"2d.1","status":"draft_requires_review_and_freeze",
            "seed":seed,"split_method":"identical_normalized_prompt_group_hash",
            "heldout_evaluation_inputs_included":False,
            "warnings":["This is a draft. Inspect near-duplicate tasks across datasets before freezing.",
                        "LiveCodeBench temporal evaluation requires authoritative release timestamps.",
                        "Do not use held-out tasks to tune model/test generation or controller behavior."],
            "counts":dict(Counter(v["partition"] for v in assigned.values())),
            "tasks":assigned}


def main():
    p=argparse.ArgumentParser(description="Draft task splits; public prompts only")
    p.add_argument("--seed",type=int,default=2026)
    p.add_argument("--output",default="results/phase2d/splits.json")
    args=p.parse_args()
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to((ROOT/"results").resolve()):
        p.error("Output must be within results/")
    data=generate_splits(public_rows(ROOT),args.seed)
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():
        p.error(f"Refusing to overwrite an existing split manifest: {out}")
    out.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Saved DRAFT split manifest:",out.relative_to(ROOT))
    print("Partition counts:",data["counts"])
    print("Review and freeze before large experiments. No hidden evaluation material accessed.")


if __name__=="__main__":main()
