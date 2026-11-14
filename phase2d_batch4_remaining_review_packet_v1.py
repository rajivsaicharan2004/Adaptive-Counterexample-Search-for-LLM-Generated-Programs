#!/usr/bin/env python3
"""Build a *provisional*, source-verified Batch 4 remaining-specification review packet.

Includes 8 secondary development pairs and 14 validation/held-out pairs.
Does NOT adjudicate, modify policy, permit execution, or imply blinded human review.

Usage:
    .venv/bin/python phase2d_batch4_remaining_review_packet_v1.py --preview
    .venv/bin/python phase2d_batch4_remaining_review_packet_v1.py
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from phase2d_quarantine_guard import load_verified_policy

SOURCES = {
    "triage": (
        "results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1/"
        "batch4_policy_triage_summary.json",
        "10fb936babf23a99614781d56dad1719fc88085f8a630503ef7de81f927b472a",
    ),
    "development": (
        "results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1/"
        "development_second_review_queue.csv",
        "62bc7a431991a7f401193730814d94d5bab52407a6cc27391eddac17c0924ea2",
    ),
    "evaluation": (
        "results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1/"
        "validation_heldout_watchlist.csv",
        "753c418bfc61b90c66d1644fa6bfa22229c4be4e85a5a8bbf1e81115b15d975b",
    ),
    "review": (
        "results/phase2d/global_overlap_stratified_v1/manual_review_batch4_provisional.json",
        "84b0e2e541a075c151e6f742bd21267b34410f6000eb8032f9019693e570d84f",
    ),
    "priority_addendum": (
        "results/phase2d/phase2d_batch4_priority_adjudication_addendum_v1.json",
        "d5151eb052e225f9d9406d19845ada52362368e548a7abe367001cb80c50731d",
    ),
}

DATASETS = {
    "MBPP": ("data/public/mbpp.jsonl", ("text", "prompt")),
    "HumanEval": ("data/public/humaneval.jsonl", ("prompt",)),
    "BigCodeBench": (
        "data/public/bigcodebench.jsonl",
        ("instruct_prompt", "complete_prompt", "prompt", "text"),
    ),
}
OUTPUT_REL = "results/phase2d/batch4_remaining_spec_review_packet_v1.json"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_json(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def checked_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def task_pair(row):
    a, b = row.get("task_a"), row.get("task_b")
    require(isinstance(a, str) and bool(a) and isinstance(b, str) and bool(b),
            "Missing pair task identifiers")
    require(a != b, f"Self-pair: {a}")
    return a, b


def provisional_components(pairs):
    """Connected *candidate-transfer* groups, NOT equivalence classes."""
    graph = defaultdict(set)
    for a, b, _ in pairs:
        graph[a].add(b)
        graph[b].add(a)
    visited = set()
    comps = []
    for start in sorted(graph):
        if start in visited:
            continue
        stack = [start]
        group = []
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            group.append(node)
            stack.extend(sorted(graph[node] - visited))
        comps.append(sorted(group))
    return sorted(comps, key=lambda group: (-len(group), group))


def build(root):
    manifest, quarantined = load_verified_policy(root)
    require(manifest.get("status") == "draft_requires_review_and_freeze",
            "Split status changed; refusing to continue")
    tasks = manifest.get("tasks")
    require(isinstance(tasks, dict) and bool(tasks), "Manifest tasks missing")

    for label, (relative_path, expected_digest) in SOURCES.items():
        path = root / relative_path
        require(path.is_file(), f"Missing {label}: {relative_path}")
        require(file_digest(path) == expected_digest,
                f"Source hash verification failed: {relative_path}")

    triage = checked_json(root / SOURCES["triage"][0])
    review = checked_json(root / SOURCES["review"][0])
    prior = checked_json(root / SOURCES["priority_addendum"][0])
    development = checked_csv(root / SOURCES["development"][0])
    evaluation = checked_csv(root / SOURCES["evaluation"][0])

    require(triage.get("execution_authorized") is False and
            triage.get("final_split_freeze_authorized") is False,
            "Triage authorization state changed")
    require(triage.get("state") == "provisional_second_review_not_completed",
            "Unexpected Batch 4 review state")
    require(triage.get("secondary_independent_review") == 8 and
            triage.get("priority_independent_review") == 13,
            "Unexpected Batch 4 priority/secondary counts")
    require(review.get("needs_contract_review_pairs") == [["MBPP/707", "MBPP/903"]],
            "Unresolved contract evidence changed")
    require(prior.get("reviewed_pair_count") == 14 and
            prior.get("independent_second_review_completed") is False and
            prior.get("execution_authorized") is False,
            "Priority addendum format/authorization changed")

    require(len(development) == 21 and len(evaluation) == 14,
            "Batch 4 CSV row counts changed")
    secondary = [r for r in development
                 if r.get("review_priority") == "secondary_independent_review"]
    priority = [r for r in development
                if r.get("review_priority") == "priority_independent_review"]
    require(len(secondary) == 8 and len(priority) == 13,
            "Batch 4 development priority counts changed")
    require({r["review_priority"] for r in development} == {
        "priority_independent_review", "secondary_independent_review"
    }, "Unexpected development review priority category")

    # DO NOT copy earlier first-pass labels, rationale, proposed actions, or
    # the already-reviewed priority cases into the assessor's specification packet.
    all_pairs = []
    admin = []
    for row in secondary:
        a, b = task_pair(row)
        dev = row.get("development_task")
        require(dev in (a, b), f"Development member missing from pair {a}, {b}")
        require(tasks.get(dev, {}).get("partition") == "development",
                f"Incorrect development partition: {dev}")
        require(dev not in quarantined,
                f"Development task is now quarantined: {dev}; re-review policy")
        all_pairs.append((a, b, "secondary_development_review"))
        admin.append((a, b, dev))

    for row in evaluation:
        a, b = task_pair(row)
        pa = tasks.get(a, {}).get("partition")
        pb = tasks.get(b, {}).get("partition")
        require({pa, pb} == {"validation", "held_out"},
                f"Evaluation partitions changed for {a}, {b}: {pa}, {pb}")
        all_pairs.append((a, b, "validation_heldout_review"))

    pair_keys = [frozenset((a, b)) for a, b, _ in all_pairs]
    require(len(pair_keys) == len(set(pair_keys)) == 22,
            "Expected 22 unique secondary/evaluation pairs")
    priority_keys = {frozenset(task_pair(row)) for row in priority}
    require(not set(pair_keys).intersection(priority_keys),
            "Already-reviewed priority case unexpectedly reused")

    wanted = {task for a, b, _ in all_pairs for task in (a, b)}
    prompts = {}
    for dataset, (relative_path, fields) in DATASETS.items():
        source = root / relative_path
        require(source.is_file(), f"Missing public dataset: {relative_path}")
        with source.open("r", encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                raw = rec.get("task_id")
                if raw is None:
                    raw = rec.get("id")
                if raw is None:
                    continue
                task_id = str(raw)
                if "/" not in task_id:
                    task_id = f"{dataset}/{task_id}"
                if task_id not in wanted:
                    continue
                require(task_id not in prompts, f"Duplicate task: {task_id}")
                require(task_id.startswith(dataset + "/"),
                        f"Dataset/task ID conflict: {task_id}")
                selected = next(
                    ((key, rec[key]) for key in fields
                     if isinstance(rec.get(key), str) and rec[key].strip()), None
                )
                require(selected is not None,
                        f"Missing public prompt for {task_id}")
                field, prompt = selected
                metadata = tasks.get(task_id)
                require(isinstance(metadata, dict),
                        f"Task missing from manifest: {task_id}")
                normalized_digest = metadata.get("public_prompt_sha256")
                require(isinstance(normalized_digest, str) and
                        len(normalized_digest) == 64 and
                        all(c in "0123456789abcdef" for c in normalized_digest),
                        f"Invalid manifest prompt hash: {task_id}")
                prompts[task_id] = {
                    "task_id": task_id,
                    "public_specification": prompt,
                    "raw_public_text_sha256": hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    "manifest_public_prompt_sha256": normalized_digest,
                    "source_file": relative_path,
                    "source_line": line_no,
                    "source_field": field,
                }

    require(set(prompts) == wanted,
            f"Missing public specifications: {sorted(wanted - set(prompts))}")
    comps = provisional_components(all_pairs)
    overlap_groups = [group for group in comps if len(group) > 2]

    packet = {
        "schema_version": 1,
        "record_type": "PHASE2D_BATCH4_REMAINING_UNADJUDICATED_PUBLIC_SPECIFICATION_PACKET_V1",
        "manifest_status": manifest["status"],
        "pair_count": len(all_pairs),
        "secondary_development_pair_count": len(secondary),
        "validation_heldout_pair_count": len(evaluation),
        "unique_public_task_count": len(wanted),
        "source_evidence_sha256": {key: value[1] for key, value in SOURCES.items()},
        "original_verdicts_withheld": True,
        "independent_human_review_completed": False,
        "execution_authorized": False,
        "split_freeze_authorized": False,
        "quarantine_change_authorized": False,
        "review_guidance": (
            "Have an independent human assessor review public prompts and record "
            "an explanation and a provisional verdict for each pair BEFORE consulting "
            "the original Batch 4 first-pass judgments. An LLM-assisted assessment "
            "is not independent human-reviewer agreement."
        ),
        "caveats": [
            "Public prompts only; hidden tests and reference solutions excluded.",
            "Prompt hashes may differ from manifest normalized hashes.",
            "Potential transfer connections do not prove behavioral equivalence.",
            "No prior pair adjudication is changed by this packet.",
            "The existing V3 guard and draft pilot restriction remain unchanged.",
        ],
        "provisional_risk_connected_groups": overlap_groups,
        "pairs": [
            {
                "review_index": i,
                "review_track": track,
                "task_a": prompts[a],
                "task_b": prompts[b],
                "independent_human_reviewer_verdict": None,
                "independent_human_reviewer_reasoning": None,
            }
            for i, (a, b, track) in enumerate(all_pairs, 1)
        ],
    }
    return packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true",
                        help="Verify and show summary without writing files")
    args = parser.parse_args()
    root = Path.cwd().resolve()

    try:
        packet = build(root)
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FAIL CLOSED: {exc}") from exc

    print("PHASE 2D — BATCH 4 REMAINING PUBLIC SPECIFICATION REVIEW PACKET V1")
    print("All five source artifact SHA-256 hashes verified.")
    print("Secondary development pairs:", packet["secondary_development_pair_count"])
    print("Validation/held-out pairs:", packet["validation_heldout_pair_count"])
    print("Total pairs:", packet["pair_count"])
    print("Unique public specifications:", packet["unique_public_task_count"])
    print("Provisional multi-pair connected groups:")
    for group in packet["provisional_risk_connected_groups"]:
        print(" ", " / ".join(group))
    print("Original verdicts withheld; independent human review NOT completed.")
    print("No split freeze, execution permission, or quarantine changes.")
    if args.preview:
        print("PREVIEW ONLY. No output written.")
        return

    output = root / OUTPUT_REL
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(packet, sort_keys=True, indent=2, ensure_ascii=False)
               + "\n").encode("utf-8")
    try:
        with output.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as exc:
        raise SystemExit(f"FAIL CLOSED: Output exists; will not overwrite: {OUTPUT_REL}") from exc
    print("CREATED:", OUTPUT_REL)
    print("SHA256:", hashlib.sha256(payload).hexdigest())
    print("No source, manifest, guard, review, Docker, candidate, or model changes.")


if __name__ == "__main__":
    main()
