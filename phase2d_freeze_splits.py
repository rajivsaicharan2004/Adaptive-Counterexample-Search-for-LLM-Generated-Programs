#!/usr/bin/env python3
"""Explicitly freeze a reviewed public-task split manifest, without hidden test data."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description="Freeze reviewed development/validation/holdout partitions")
    p.add_argument("--file",default="results/phase2d/splits.json")
    p.add_argument("--acknowledge-review",action="store_true",
                   help="Affirm near-duplicate grouping, split policy, and temporal holdouts reviewed")
    a=p.parse_args()
    path=(ROOT/a.file).resolve()
    if not path.is_relative_to((ROOT/"results/phase2d").resolve()):
        p.error("Only manifests inside results/phase2d are allowed")
    if not path.is_file():p.error("Missing draft split manifest")
    doc=json.loads(path.read_text(encoding="utf-8"))
    if doc.get("status")=="frozen":
        print("Split manifest already frozen; no changes made")
        return
    if doc.get("status")!="draft_requires_review_and_freeze":p.error("Unexpected split status")
    if not a.acknowledge_review:
        p.error("Inspect manifest manually first, then rerun with --acknowledge-review")
    tasks=doc.get("tasks")
    if not isinstance(tasks,dict) or not tasks:p.error("Missing task assignments")
    if any(entry.get("partition") not in
           ("development","validation","held_out","held_out_temporal_pending")
           for entry in tasks.values()):
        p.error("Invalid partition label")
    backup=path.with_suffix(".draft_backup.json")
    if backup.exists():p.error("Backup already exists; refusing to overwrite")
    backup.write_bytes(path.read_bytes())
    doc["status"]="frozen"
    doc["frozen_utc"]=datetime.now(timezone.utc).isoformat()
    doc["review_assertion"]="Explicit --acknowledge-review by user; not independently audited by software"
    path.write_text(json.dumps(doc,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Frozen:",path.relative_to(ROOT))
    print("Preserved draft backup:",backup.relative_to(ROOT))
    print("Keep this assignment fixed throughout model tuning and final evaluation")

if __name__=="__main__":main()
