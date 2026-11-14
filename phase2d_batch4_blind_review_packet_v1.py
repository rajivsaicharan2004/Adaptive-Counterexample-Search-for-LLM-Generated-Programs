from pathlib import Path
import csv
import hashlib
import json
from phase2d_quarantine_guard import load_verified_policy

root = Path.cwd()
manifest, quarantined = load_verified_policy(root)
if manifest.get("status") != "draft_requires_review_and_freeze":
    raise SystemExit("Unexpected split status; refusing to proceed")

base = Path("results/phase2d/global_overlap_stratified_v1")
sources = {
    "triage": (base / "batch4_policy_triage_v1/batch4_policy_triage_summary.json", "10fb936babf23a99614781d56dad1719fc88085f8a630503ef7de81f927b472a"),
    "development": (base / "batch4_policy_triage_v1/development_second_review_queue.csv", "62bc7a431991a7f401193730814d94d5bab52407a6cc27391eddac17c0924ea2"),
    "evaluation": (base / "batch4_policy_triage_v1/validation_heldout_watchlist.csv", "753c418bfc61b90c66d1644fa6bfa22229c4be4e85a5a8bbf1e81115b15d975b"),
    "review": (base / "manual_review_batch4_provisional.json", "84b0e2e541a075c151e6f742bd21267b34410f6000eb8032f9019693e570d84f"),
}
for name, (rel, expected) in sources.items():
    if hashlib.sha256((root / rel).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"Source hash mismatch: {name}")

triage = json.loads((root / sources["triage"][0]).read_text(encoding="utf-8"))
review = json.loads((root / sources["review"][0]).read_text(encoding="utf-8"))
with (root / sources["development"][0]).open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

priority = [r for r in rows if r["review_priority"] == "priority_independent_review"]
secondary = [r for r in rows if r["review_priority"] == "secondary_independent_review"]
if (len(rows), len(priority), len(secondary)) != (21, 13, 8):
    raise SystemExit("Priority review counts changed")
if triage.get("priority_independent_review") != 13 or triage.get("secondary_independent_review") != 8:
    raise SystemExit("Triage count mismatch")
if triage.get("execution_authorized") is not False or triage.get("final_split_freeze_authorized") is not False:
    raise SystemExit("Unexpected policy authorization")
contract_pairs = review.get("needs_contract_review_pairs")
if contract_pairs != [["MBPP/707", "MBPP/903"]]:
    raise SystemExit(f"Unexpected unresolved contract pairs: {contract_pairs!r}")

pairs = [(r["task_a"], r["task_b"], "priority_independent_second_review") for r in priority]
pairs += [("MBPP/707", "MBPP/903", "unresolved_contract_review")]
if len({frozenset((a,b)) for a,b,_ in pairs}) != 14:
    raise SystemExit("Duplicate review pair")
wanted = {x for a,b,_ in pairs for x in (a,b)}

data_files = {
    "MBPP": ("data/public/mbpp.jsonl", ("text", "prompt")),
    "HumanEval": ("data/public/humaneval.jsonl", ("prompt",)),
    "BigCodeBench": ("data/public/bigcodebench.jsonl", ("instruct_prompt", "complete_prompt", "prompt", "text")),
}
public = {}
for dataset, (relative_path, fields) in data_files.items():
    path = root / relative_path
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            raw_id = rec.get("task_id", rec.get("id"))
            if raw_id is None:
                continue
            task_id = str(raw_id)
            if "/" not in task_id:
                task_id = f"{dataset}/{task_id}"
            if task_id not in wanted:
                continue
            if task_id in public:
                raise SystemExit(f"Duplicate public task: {task_id}")
            selected = next(((key, rec[key]) for key in fields if isinstance(rec.get(key), str) and rec[key].strip()), None)
            if selected is None:
                raise SystemExit(f"No public prompt: {task_id}")
            field, prompt = selected
            metadata = manifest["tasks"].get(task_id)
            if not isinstance(metadata, dict):
                raise SystemExit(f"Task missing from manifest: {task_id}")
            public[task_id] = {
                "task_id": task_id,
                "public_specification": prompt,
                "manifest_public_prompt_sha256": metadata["public_prompt_sha256"],
                "raw_public_text_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "source_file": relative_path,
                "source_line": line_no,
                "source_field": field,
            }
missing = wanted - set(public)
if missing:
    raise SystemExit(f"Missing public specifications: {sorted(missing)}")

for row in priority:
    dev = row["development_task"]
    if dev not in (row["task_a"], row["task_b"]):
        raise SystemExit("Inconsistent development task in queue")
    if manifest["tasks"][dev]["partition"] != "development":
        raise SystemExit("Development task partition changed")

packet = {
    "schema_version": 1,
    "record_type": "PHASE2D_BATCH4_UNADJUDICATED_PUBLIC_SPECIFICATION_REVIEW_PACKET_V1",
    "manifest_status": manifest["status"],
    "source_evidence_sha256": {name: digest for name, (_, digest) in sources.items()},
    "pair_count": 14,
    "priority_second_review_count": 13,
    "unresolved_contract_review_count": 1,
    "independent_second_review_completed": False,
    "initial_verdicts_withheld_from_packet": True,
    "execution_authorized": False,
    "split_freeze_authorized": False,
    "instruction": "A separate independent reviewer should assess these public specifications without consulting earlier verdicts, record their own reasoning and reviewer identity, then compare with the original review. An LLM explanation here is not independent human reviewer agreement.",
    "caveats": ["Public prompts only; no reference solutions or hidden tests.", "Prompt text hashes may differ from manifest normalized hashes.", "Existing V3 quarantine and pilot restrictions remain unchanged.", "The first-pass reviewer verdicts are available in the original evidence, but deliberately omitted here."],
    "pairs": [{"review_index": i, "review_track": track, "task_a": public[a], "task_b": public[b], "independent_reviewer_verdict": None, "independent_reviewer_reasoning": None} for i, (a, b, track) in enumerate(pairs, 1)],
}
out = root / "results/phase2d/batch4_priority_spec_review_packet_v1.json"
out.parent.mkdir(parents=True, exist_ok=True)
payload = (json.dumps(packet, indent=2, sort_keys=True) + "\n").encode("utf-8")
with out.open("xb") as f:
    f.write(payload)
print("PHASE 2D — BATCH 4 PRIORITY PUBLIC SPECIFICATION REVIEW PACKET")
print("Priority pairs:", len(priority))
print("Separate unresolved contract pairs:", 1)
print("Unique public task specifications:", len(public))
print("Saved:", out.relative_to(root))
print("SHA256:", hashlib.sha256(payload).hexdigest())
print("Status: UNADJUDICATED. No independent review claimed.")
print("No original artifact, manifest, or guard modified; no candidate code or models executed.")
