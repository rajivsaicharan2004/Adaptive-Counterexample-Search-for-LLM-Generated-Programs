#!/usr/bin/env python3
"""Read-only public-prompt lexical overlap review for a provisional development task.

This is a candidate finder, not a semantic-duplicate detector or a split approval.
Never reads official/private tests, generates code, invokes a model, or executes
candidate programs. Never changes the split manifest.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import re

DATASETS = ("humaneval", "mbpp", "bigcodebench", "livecodebench")
TOKEN = re.compile(r"[a-z][a-z0-9_]*|\d+")


def normalized_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.lower()).strip()


def terms(text: str) -> frozenset[str]:
    # A lexical heuristic only. Boilerplate is naturally downweighted by IDF.
    return frozenset(t for t in TOKEN.findall(text.lower()) if len(t) >= 3)


def weight_jaccard(a: frozenset[str], b: frozenset[str], idf: dict[str, float]) -> float:
    union = a | b
    if not union:
        return 1.0
    return sum(idf[t] for t in a & b) / sum(idf[t] for t in union)


def load_public(root: Path) -> list[dict]:
    result = []
    ids = set()
    for dataset in DATASETS:
        path = root / "data" / "public" / f"{dataset}.jsonl"
        if not path.is_file():
            raise SystemExit(f"Missing public dataset: {path}")
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            tid = row["task_id"]
            if tid in ids:
                raise SystemExit(f"Duplicate task ID in public data: {tid}")
            ids.add(tid)
            if row.get("dataset") != dataset:
                raise SystemExit(f"Unexpected dataset for {tid} at {path}:{lineno}")
            prompt = row["prompt"]
            if not isinstance(prompt, str):
                raise SystemExit(f"Non-text public prompt: {tid}")
            result.append({"task_id": tid, "dataset": dataset,
                           "prompt": prompt, "terms": terms(prompt),
                           "hash": sha256(normalized_prompt(prompt).encode()).hexdigest()})
    return result


def check_manifest(root: Path, rows: list[dict]) -> tuple[dict, dict]:
    path = root / "results" / "phase2d" / "splits.json"
    if not path.is_file():
        raise SystemExit(f"Split manifest missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = manifest.get("tasks")
    if not isinstance(entries, dict):
        raise SystemExit("Malformed split manifest: missing tasks mapping")
    expected_ids = {row["task_id"] for row in rows}
    if set(entries) != expected_ids:
        raise SystemExit(f"Manifest/public task mismatch: {len(expected_ids - set(entries))} missing, "
                         f"{len(set(entries) - expected_ids)} extra")
    for row in rows:
        entry = entries[row["task_id"]]
        if not isinstance(entry, dict) or entry.get("public_prompt_sha256") != row["hash"]:
            raise SystemExit(f"Public prompt hash mismatch: {row['task_id']}")
        if entry.get("dataset") != row["dataset"]:
            raise SystemExit(f"Dataset mismatch: {row['task_id']}")
    return manifest, entries


def review(root: Path, target_id: str, top: int) -> None:
    rows = load_public(root)
    manifest, assignments = check_manifest(root, rows)
    task = next((row for row in rows if row["task_id"] == target_id), None)
    if task is None:
        raise SystemExit(f"Target not found among public tasks: {target_id}")
    status = manifest.get("status", "missing")
    partition = assignments[target_id].get("partition", "missing")
    print(f"Manifest: {status}; target: {target_id} ({partition})")
    print(f"Public tasks: {len(rows)}; manifest IDs and public hashes VERIFIED")
    print("No manifest modification, candidate execution, model/API calls, or private data access.")
    if status != "draft_requires_review_and_freeze":
        print("NOTICE: Manifest no longer has the expected DRAFT status. Review provenance.")
    if partition != "development":
        print("NOTICE: Target is NOT provisionally assigned to development.")

    df = Counter(term for row in rows for term in row["terms"])
    n = len(rows)
    idf = {term: math.log((n + 1) / (count + 1)) + 1 for term, count in df.items()}
    ranked = []
    for row in rows:
        if row["task_id"] == target_id:
            continue
        similarity = weight_jaccard(task["terms"], row["terms"], idf)
        ranked.append((similarity, row))
    ranked.sort(key=lambda item: (-item[0], item[1]["task_id"]))

    print("\nTOP LEXICAL OVERLAPS (human review only; NOT semantic-duplicate verdicts)")
    print("Similarity is weighted token Jaccard; different wording can evade this screening.")
    for i, (score, row) in enumerate(ranked[:top], 1):
        other_partition = assignments[row["task_id"]].get("partition", "missing")
        cross_partition = "CROSS-PARTITION" if other_partition != partition else "same-partition"
        snippet = re.sub(r"\s+", " ", row["prompt"]).strip()[:220]
        print(f"{i:2d}. {row['task_id']:<35} score={score:.3f} "
              f"partition={other_partition:<27} {cross_partition}")
        print(f"    {snippet}")
    print("\nREVIEW REQUIRED: manually inspect relevant public prompts, especially overlaps across partitions.")
    print("Do not freeze splits or promote the /854 test suite based on this lexical report alone.")


def self_test() -> None:
    a = terms("Compute all permutations and factorial sums")
    b = terms("factorial sums over permutations")
    c = terms("sort files with timestamps")
    idf = {t: 1.0 for t in a | b | c}
    assert weight_jaccard(a, a, idf) == 1.0
    assert weight_jaccard(a, b, idf) > weight_jaccard(a, c, idf)
    assert normalized_prompt("One\n  TWO") == "one two"
    print("Self-test PASS; no filesystem reads or writes.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only lexical overlap shortlist for public tasks")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument("--task-id", default="BigCodeBench/854")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.top <= 100:
        ap.error("--top must be in 1..100")
    review(args.root.resolve(), args.task_id, args.top)


if __name__ == "__main__":
    main()
