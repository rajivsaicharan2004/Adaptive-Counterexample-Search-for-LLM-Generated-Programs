#!/usr/bin/env python3
"""Record six human-reviewed PUBLIC prompt overlap leads without changing splits.

Default: read-only validation and preview. --write exclusively creates
results/phase2d/global_overlap_audit_v1/manual_review.json using exclusive
creation; never overwrites, reassigns, or enables candidate execution.

Requires phase2d_global_overlap_audit.py in the project root.
All checks use PUBLIC prompts, the draft manifest, and the exported lexical
report only. No candidate programs, model calls, Docker, network, or private data.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from phase2d_global_overlap_audit import load_and_verify, sha256_file

EXPECTED_STATUS = "draft_requires_review_and_freeze"
REPORT_REL = Path("results/phase2d/global_overlap_audit_v1/global_overlap_report.json")
OUTPUT_REL = Path("results/phase2d/global_overlap_audit_v1/manual_review.json")

# These decisions are provisional prompt-level reviews, not verified official
# benchmark equivalence judgments. Scores are fetched from the original report.
REVIEWS = [
    {
        "a": "MBPP/758", "b": "MBPP/779",
        "partition_a": "validation", "partition_b": "development",
        "entry_a": "unique_sublists", "entry_b": "unique_sublists",
        "text_a": ["count number of unique lists"],
        "text_b": ["count the number of unique lists"],
        "verdict": "equivalent_public_specification",
        "evidence": "Both request the number of unique sublists, and both specify the same entry point; only wording differs.",
        "uncertainty": "Return behavior, duplicate equality semantics, and official tests not inspected.",
        "development_task": "MBPP/779",
    },
    {
        "a": "MBPP/817", "b": "MBPP/883",
        "partition_a": "held_out", "partition_b": "development",
        "entry_a": "div_of_nums", "entry_b": "div_of_nums",
        "text_a": ["divisible by m or n"],
        "text_b": ["divisible by m and n"],
        "verdict": "near_equivalent_solution_transfer",
        "evidence": "Same divisible-number filtering structure and entry point; OR versus AND changes correct behavior.",
        "uncertainty": "Not semantically equivalent; different Boolean conditions are observable on some inputs.",
        "development_task": "MBPP/883",
    },
    {
        "a": "MBPP/931", "b": "MBPP/935",
        "partition_a": "held_out", "partition_b": "development",
        "entry_a": "sum_series", "entry_b": "series_sum",
        "text_a": ["³"],
        "text_b": ["²"],
        "verdict": "near_equivalent_solution_transfer",
        "evidence": "Both sum powers of 1..n; exponents 3 and 2 and entry-point names differ.",
        "uncertainty": "Not semantically equivalent; different mathematical functions.",
        "development_task": "MBPP/935",
    },
    {
        "a": "MBPP/534", "b": "MBPP/607",
        "partition_a": "development", "partition_b": "validation",
        "entry_a": "search_literal", "entry_b": "find_literals",
        "text_a": ["literals string"],
        "text_b": ["literals string", "regex"],
        "verdict": "needs_contract_review",
        "evidence": "Both locate a literal substring, but one explicitly requires regex and expected output contracts are unspecified.",
        "uncertainty": "Must inspect public examples and output semantics before deciding equivalence.",
        "development_task": "MBPP/534",
    },
    {
        "a": "MBPP/415", "b": "MBPP/922",
        "partition_a": "held_out", "partition_b": "development",
        "entry_a": "max_Product", "entry_b": "max_product",
        "text_a": ["highest product", "pair"],
        "text_b": ["highest product", "pair"],
        "verdict": "equivalent_public_specification",
        "evidence": "Same highest-product integer pair task; differences are capitalization and wording.",
        "uncertainty": "Output order and tie behavior not specified in these public prompts.",
        "development_task": "MBPP/922",
    },
    {
        "a": "BigCodeBench/894", "b": "BigCodeBench/895",
        "partition_a": "held_out", "partition_b": "development",
        "entry_a": "task_func", "entry_b": "task_func",
        "text_a": ["Histogram of Random Integers", "ARRAY_SIZE = 10000"],
        "text_b": ["Histogram of Random Values", "ARRAY_SIZE = 10000"],
        "verdict": "near_equivalent_solution_transfer",
        "evidence": "Identical random-array statistics and histogram workflow; only chart title and axis labels differ.",
        "uncertainty": "Not identical as visual-output specifications; randomized outputs require controlled comparison.",
        "development_task": "BigCodeBench/895",
    },
]


def load_public_details(root: Path):
    """Read only candidate task IDs needed for entry point and excerpt checks."""
    desired = {item[key] for item in REVIEWS for key in ("a", "b")}
    found = {}
    for dataset in ("mbpp", "bigcodebench"):
        filename = root / "data" / "public" / (dataset + ".jsonl")
        with filename.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    row = json.loads(line)
                    if row.get("task_id") in desired:
                        if row["task_id"] in found:
                            raise ValueError("Duplicate task ID: " + row["task_id"])
                        found[row["task_id"]] = row
    if set(found) != desired:
        raise ValueError("Missing reviewed tasks: " + repr(sorted(desired - set(found))))
    return found


def paired_key(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


def build_record(root: Path):
    tasks, manifest, hashes = load_and_verify(root)  # all 3333 IDs + prompt hashes
    if manifest.get("status") != EXPECTED_STATUS:
        raise ValueError("Unexpected manifest status; no review record should be written")
    task_index = {t.task_id: t for t in tasks}
    public = load_public_details(root)
    report_path = root / REPORT_REL
    with report_path.open(encoding="utf-8") as fh:
        report = json.load(fh)
    if report.get("report_type") != "PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION":
        raise ValueError("Report is not a recognized public lexical audit")
    if report.get("all_public_task_count") != len(tasks):
        raise ValueError("Report task count differs from current public inputs")
    if report.get("input_sha256") != hashes:
        raise ValueError("Exported audit source hashes differ from current inputs")
    queue = {}
    for row in report.get("cross_partition_review_queue", []):
        key = paired_key(row["task_a"], row["task_b"])
        if key in queue:
            raise ValueError("Duplicate pair in audit report")
        queue[key] = row

    records = []
    for decision in REVIEWS:
        left_id, right_id = decision["a"], decision["b"]
        key = paired_key(left_id, right_id)
        source = queue.get(key)
        if not source:
            raise ValueError(f"Pair absent from exported top-K cross-partition queue: {left_id}, {right_id}")
        left, right = task_index[left_id], task_index[right_id]
        if left.partition != decision["partition_a"] or right.partition != decision["partition_b"]:
            raise ValueError(f"Partition changed for pair: {left_id}, {right_id}")
        if left.partition == right.partition:
            raise ValueError("Expected cross-partition pair")
        for side, task_id in (("a", left_id), ("b", right_id)):
            row = public[task_id]
            if row.get("entry_point") != decision["entry_" + side]:
                raise ValueError("Entry point changed for: " + task_id)
            text = (row.get("prompt") or "") + "\n" + (row.get("starter_code") or "")
            for snippet in decision["text_" + side]:
                if snippet.casefold() not in text.casefold():
                    raise ValueError(f"Public prompt check failed for {task_id}: {snippet}")
        if decision["development_task"] not in (left_id, right_id):
            raise ValueError("Invalid development quarantine target")
        if task_index[decision["development_task"]].partition != "development":
            raise ValueError("Quarantine target no longer in development")
        records.append({
            "task_a": left_id,
            "task_b": right_id,
            "partition_a": left.partition,
            "partition_b": right.partition,
            "entry_point_a": decision["entry_a"],
            "entry_point_b": decision["entry_b"],
            "normalized_prompt_sha256_a": left.normalized_hash,
            "normalized_prompt_sha256_b": right.normalized_hash,
            "lexical_weighted_jaccard": source["lexical_weighted_jaccard"],
            "char_5gram_jaccard": source["char_5gram_jaccard"],
            "verdict": decision["verdict"],
            "evidence_from_public_prompts": decision["evidence"],
            "limitations": decision["uncertainty"],
            "review_status": "provisional_public_specification_review",
            "proposed_action": "quarantine_development_partner_pending_group_split_decision",
            "proposed_quarantine_task": decision["development_task"],
            "manifest_changed": False,
            "enforcement_installed": False,
        })

    counts = Counter(row["verdict"] for row in records)
    return {
        "schema_version": 1,
        "record_type": "PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_REVIEW_NOT_PARTITION_APPROVAL",
        "review_date": "2026-11-13",
        "review_origin": "manual comparison of six supplied public task specifications",
        "review_provenance": "User-provided public prompts and local global lexical audit; official tests not consulted",
        "manifest_status_at_review": manifest["status"],
        "input_sha256": hashes,
        "lexical_report_path": str(REPORT_REL),
        "lexical_report_sha256": sha256_file(report_path),
        "reviewed_pair_count": len(records),
        "verdict_counts": dict(sorted(counts.items())),
        "quarantine": {
            "status": "proposed_not_enforced",
            "scope": "iterative program generation, testing, repair and controller training",
            "development_task_ids": sorted({r["proposed_quarantine_task"] for r in records}),
            "reason": "Similar public tasks cross a development/validation or development/held-out boundary",
        },
        "pairs": records,
        "research_caveats": [
            "Prompt-level judgments are not official benchmark-equivalence or model-training contamination findings.",
            "No hidden tests or trusted reference programs were read for these decisions.",
            "Do not use the held-out partners for iterative model evaluation or tuning.",
            "Neither this record nor its quarantine proposal changes or enforces partition membership.",
            "Further review of 4635 cross-partition lexical leads and semantic-retrieval blind spots remains necessary.",
        ],
        "manifest_modified": False,
        "execution_authorized": False,
        "final_split_freeze_authorized": False,
    }


def write_new(path: Path, payload: dict):
    """Exclusive-create output file; never overwrite a previous review."""
    if path.exists():
        raise FileExistsError("Refusing to overwrite: " + str(path))
    # Require existing parent (the global audit export directory).
    if not path.parent.is_dir():
        raise FileNotFoundError("Review directory does not exist: " + str(path.parent))
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--write", action="store_true", help="Create manual_review.json, refusing to overwrite")
    parser.add_argument("--self-test", action="store_true", help="Run nonproject synthetic regression tests")
    args = parser.parse_args(argv)

    if args.self_test:
        from tests.test_phase2d_record_manual_overlap import run_self_tests
        run_self_tests()
        return 0

    try:
        payload = build_record(args.root.resolve())
        print("Audit source hashes verified; six public-specification pairs matched.")
        print("Manifest:", payload["manifest_status_at_review"])
        print("Provisional judgments:", payload["verdict_counts"])
        print("Proposed development quarantine:", ", ".join(payload["quarantine"]["development_task_ids"]))
        path = args.root.resolve() / OUTPUT_REL
        if args.write:
            write_new(path, payload)
            print("CREATED:", path)
            print("NO partition changes. NO quarantine enforcement. NO candidate execution.")
        else:
            print("DRY RUN. Would create:", path)
            print("To create the review record, re-run with --write.")
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print("REVIEW FAILED CLOSED:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
