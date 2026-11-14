#!/usr/bin/env python3
"""Build a read-only sourced Phase 2D split-resolution review queue.

This module loads the existing verified quarantine policy and provisional reviews,
creates a new queue artifact, and never modifies the manifest or execution guard.
It does not execute generated code or import any generated candidate.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import phase2d_quarantine_guard as guard

ROOT = Path(__file__).resolve().parent
OUT_REL = Path("results/phase2d/expansion_review_queue_v1_1.json")
SOURCES = (
    ("batch1", "REVIEW_REL", 6),
    ("batch2", "BATCH2_REL", 8),
    ("batch3", "BATCH3_REL", 14),
)
TRANSFER_VERDICTS = {
    "equivalent_public_specification",
    "likely_equivalent_public_specification",
    "near_equivalent_solution_transfer",
}
REVIEW_VERDICTS = TRANSFER_VERDICTS | {"needs_contract_review", "related_but_distinct"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preview", action="store_true",
        help="Print the queue but do not write any file.",
    )
    args = parser.parse_args()

    # The guard validates the historical review chain and fails closed.
    manifest, quarantined = guard.load_verified_policy(ROOT)
    tasks = manifest.get("tasks")
    check(isinstance(tasks, dict), "Verified manifest has no tasks mapping")
    check(manifest.get("status") == "draft_requires_review_and_freeze",
          "This script is for the unchanged draft manifest only")

    partition_counts = Counter(
        item.get("partition", "unknown")
        for item in tasks.values() if isinstance(item, dict)
    )
    check(len(tasks) == 3333, "Task census changed: re-review this versioned script")
    check(len(quarantined) == 21, "Quarantine census changed: re-review script")

    source_records = []
    pairs = []
    seen = set()
    common_input_hash = None
    for batch, constant, expected_count in SOURCES:
        rel = Path(getattr(guard, constant))
        check(not rel.is_absolute() and ".." not in rel.parts,
              f"Unsafe review path {rel}")
        path = ROOT / rel
        raw = path.read_bytes()
        record = json.loads(raw)
        check(isinstance(record, dict), f"Invalid record {rel}")
        reviewed_pairs = record.get("pairs")
        check(isinstance(reviewed_pairs, list)
              and len(reviewed_pairs) == expected_count,
              f"Review count mismatch in {rel}")
        check(record.get("execution_authorized") is False
              and record.get("final_split_freeze_authorized") is False
              and record.get("manifest_modified") is False,
              f"Unexpected authority claimed by {rel}")
        inp = record.get("input_sha256")
        # Original Phase 2D audit records use a mapping of source path to
        # SHA-256 digest, not one aggregate SHA-256 string. The verified
        # quarantine guard above has already checked these values against
        # the original dataset files and all three historical review records.
        check(isinstance(inp, dict) and bool(inp),
              f"Missing source-hash mapping in {rel}")
        check(all(isinstance(k, str) and bool(k) and
                  isinstance(v, str) and len(v) == 64 and
                  all(c in '0123456789abcdef' for c in v)
                  for k, v in inp.items()),
              f"Malformed source-hash mapping in {rel}")
        if common_input_hash is None:
            common_input_hash = inp
        check(inp == common_input_hash,
              "Review records use differing audit input-hash mappings")
        source_records.append({
            "batch": batch, "path": str(rel), "sha256": digest(raw),
            "reviewed_pairs": len(reviewed_pairs),
            "record_type": record.get("record_type"),
        })
        for p in reviewed_pairs:
            check(isinstance(p, dict), f"Invalid pair in {rel}")
            a, b = p.get("task_a"), p.get("task_b")
            check(isinstance(a, str) and isinstance(b, str)
                  and a in tasks and b in tasks and a != b,
                  f"Unknown pair in {rel}: {a} / {b}")
            pair_key = tuple(sorted((a, b)))
            check(pair_key not in seen, f"Repeated reviewed pair: {pair_key}")
            seen.add(pair_key)
            verdict = p.get("verdict")
            check(verdict in REVIEW_VERDICTS,
                  f"Unrecognized verdict {verdict!r} in {rel}")
            action = p.get("proposed_action")
            check(action in {
                "quarantine_development_partner_pending_group_split_decision",
                "watchlist_validation_heldout_pending_group_split_decision",
            }, f"Unexpected action for {a} / {b}")
            pa = tasks[a].get("partition")
            pb = tasks[b].get("partition")
            cross_partition = pa != pb
            if verdict == "needs_contract_review":
                priority = "P0_contract_review_required"
            elif verdict in TRANSFER_VERDICTS and cross_partition:
                priority = "P0_cross_partition_transfer_risk"
            elif cross_partition:
                priority = "P1_cross_partition_review"
            else:
                priority = "P2_same_partition_review"
            pairs.append({
                "task_a": a, "task_b": b,
                "partition_a": pa, "partition_b": pb,
                "cross_partition": cross_partition,
                "verdict": verdict,
                "proposed_action": action,
                "proposed_quarantine_task": p.get("proposed_quarantine_task"),
                "priority": priority,
                "source_batch": batch,
                "source_review_path": str(rel),
                "decision_status": "provisional_needs_final_adjudication",
            })

    check(len(pairs) == 28, "Expected 28 provisional pair reviews")
    check(sum(p["verdict"] == "needs_contract_review" for p in pairs) == 3,
          "Expected three unresolved contract reviews")
    check(sum(p["proposed_action"].startswith("quarantine_") for p in pairs) == 21,
          "Expected 21 provisional quarantine actions")

    # Connected components indicate *potential* solution-transfer groups only.
    # No component is treated as a proven duplicate cluster or applied to the split.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for p in pairs:
        if p["verdict"] in TRANSFER_VERDICTS:
            union(p["task_a"], p["task_b"])

    comps: dict[str, list[str]] = defaultdict(list)
    for x in sorted(parent):
        comps[find(x)].append(x)
    components = [
        {
            "tasks": members,
            "partitions": {x: tasks[x].get("partition") for x in members},
            "cross_partition": len({tasks[x].get("partition") for x in members}) > 1,
            "status": "provisional_transfer_risk_not_a_final_duplicate_verdict",
        }
        for members in comps.values() if len(members) >= 2
    ]
    components.sort(key=lambda c: (-int(c["cross_partition"]), c["tasks"]))

    priority_order = {
        "P0_contract_review_required": 0,
        "P0_cross_partition_transfer_risk": 1,
        "P1_cross_partition_review": 2,
        "P2_same_partition_review": 3,
    }
    pairs.sort(key=lambda p: (priority_order[p["priority"]],
                               p["task_a"], p["task_b"]))

    output = {
        "schema_version": 1,
        "protocol": "phase2d_expansion_review_queue_v1_1",
        "status": "provisional_review_queue_not_partition_approval",
        "execution_authorized": False,
        "final_split_freeze_authorized": False,
        "manifest_modified": False,
        "policy_input_sha256": common_input_hash,
        "sources": source_records,
        "summary": {
            "task_count": len(tasks),
            "partition_counts": dict(sorted(partition_counts.items())),
            "quarantined_count": len(quarantined),
            "development_not_quarantined": sum(
                isinstance(item, dict)
                and item.get("partition") == "development"
                and task_id not in quarantined
                for task_id, item in tasks.items()
            ),
            "pilot_task_ids": sorted(guard.PILOT_TASKS),
            "reviewed_pair_count": len(pairs),
            "review_priority_counts": dict(sorted(Counter(
                p["priority"] for p in pairs
            ).items())),
            "verdict_counts": dict(sorted(Counter(
                p["verdict"] for p in pairs
            ).items())),
            "provisional_transfer_risk_components": len(components),
            "cross_partition_transfer_risk_components": sum(
                c["cross_partition"] for c in components
            ),
        },
        "reviewed_pairs_priority_order": pairs,
        "provisional_transfer_risk_components": components,
        "blocking_next_checks": [
            "Resolve every needs_contract_review pair using complete public specifications and contract semantics.",
            "Adjudicate cross-partition solution-transfer risks and choose reproducible group-level split assignments.",
            "Review remaining lexical overlap candidate universe; these 28 reviews are not proof of global decontamination.",
            "Verify unreviewed HumanEval cross-task overlap suspicions, including HumanEval/1 vs HumanEval/6, using original audit evidence.",
            "Establish LiveCodeBench temporal provenance before moving pending tasks into any final temporal evaluation.",
            "Produce a separate versioned, approved policy after human review; never modify the draft guard implicitly.",
        ],
        "caveats": [
            "Provisional equivalence/transfer labels do not establish semantic identity.",
            "Quarantining development tasks alone does not resolve validation-versus-held-out overlap.",
            "The draft guard restricts generation/evaluation to authorized pilot tasks regardless of non-quarantine status.",
            "No hidden tests, private held-out solutions, or generated programs were read or executed.",
        ],
    }

    payload = json.dumps(output, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    print("PHASE 2D — EXPANSION REVIEW QUEUE V1.1")
    print("Manifest status:", manifest["status"])
    print("Tasks:", len(tasks), "| quarantined:", len(quarantined))
    print("Reviewed pairs:", len(pairs), "| contract reviews:",
          sum(p["verdict"] == "needs_contract_review" for p in pairs))
    print("Priority counts:")
    for priority, count in sorted(output["summary"]["review_priority_counts"].items()):
        print(f"  {priority}: {count}")
    print("Provisional transfer groups:", len(components),
          "| cross-partition:",
          output["summary"]["cross_partition_transfer_risk_components"])
    print("\nTOP CONTRACT REVIEWS:")
    for p in pairs:
        if p["priority"] == "P0_contract_review_required":
            print(f"  {p['task_a']} [{p['partition_a']}] <-> "
                  f"{p['task_b']} [{p['partition_b']}]")
    print("\nNOT APPROVED: No split freeze or broader execution authorization.")
    if args.preview:
        print("PREVIEW ONLY. No output written.")
        return

    path = ROOT / OUT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(payload)
    print("\nCreated:", OUT_REL)
    print("SHA256:", digest(payload))
    print("No existing manifest/guard/review record changed; no Docker/model/candidate calls.")


if __name__ == "__main__":
    main()
