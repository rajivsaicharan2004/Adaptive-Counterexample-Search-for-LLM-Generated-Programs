import ast
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from phase2d_quarantine_guard import require_task_permission

ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT / "generated" / "phase1"

TASKS = {
    "HumanEval/0": "has_close_elements",
    "HumanEval/1": "separate_paren_groups",
}

PROMPT_METHODS = {"direct", "sampling", "diverse", "plan"}
SEARCH_METHODS = {"beam", "mcts", "evolution", "adaptive"}

print("=" * 65)
print("PHASE 2E: CANDIDATE REGISTRY V1")
print("=" * 65)

# Validate the original, versioned quarantine policy.
for task_id in TASKS:
    print(require_task_permission(ROOT, task_id, "evaluate"))

groups = defaultdict(lambda: defaultdict(list))
excluded = []
errors = []

if not SOURCE_ROOT.is_dir():
    raise SystemExit("ERROR: generated/phase1 directory missing")

for path in sorted(SOURCE_ROOT.rglob("*.py")):
    relative_path = str(path.relative_to(ROOT))

    if "validator_diagnostic" in relative_path.lower():
        excluded.append({
            "path": relative_path,
            "reason": "validator_diagnostic",
        })
        continue

    match = re.search(
        r"(HumanEval|MBPP|BigCodeBench|LiveCodeBench)_(\d+)",
        relative_path,
    )

    task_id = (
        f"{match.group(1)}/{match.group(2)}"
        if match else None
    )

    if task_id not in TASKS:
        excluded.append({
            "path": relative_path,
            "reason": "outside_development_pilot",
        })
        continue

    metadata_path = path.with_suffix(".json")

    if not metadata_path.is_file():
        errors.append(f"Missing metadata: {relative_path}")
        continue

    try:
        source_bytes = path.read_bytes()
        source = source_bytes.decode("utf-8")
        metadata_bytes = metadata_path.read_bytes()
        metadata = json.loads(metadata_bytes)
        tree = ast.parse(source, filename=relative_path)
    except (SyntaxError, UnicodeError) as exc:
        excluded.append({
            "path": relative_path,
            "reason": "syntax_invalid",
            "error": str(exc),
        })
        continue
    except (OSError, ValueError) as exc:
        errors.append(f"{relative_path}: {exc}")
        continue

    if not isinstance(metadata, dict):
        errors.append(f"Invalid metadata structure: {relative_path}")
        continue

    digest = hashlib.sha256(source_bytes).hexdigest()
    recorded_hash = metadata.get("code_sha256")

    # Phase 1 records the hash before the saved file's final LF.
    # Verify precisely one final LF; do not strip arbitrary whitespace.
    if not source_bytes.endswith(b"\n"):
        errors.append(f"Missing expected final LF: {relative_path}")
        continue

    phase1_digest = hashlib.sha256(source_bytes[:-1]).hexdigest()

    if recorded_hash != phase1_digest:
        errors.append(
            f"Source hash mismatch after one-LF normalization: {relative_path}"
        )
        continue

    if metadata.get("task_id") != task_id:
        errors.append(f"Task metadata mismatch: {relative_path}")
        continue

    if metadata.get("status") != "generated":
        errors.append(f"Unexpected generation status: {relative_path}")
        continue

    if metadata.get("syntax_ok") is not True:
        errors.append(f"Syntax metadata mismatch: {relative_path}")
        continue

    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    if TASKS[task_id] not in functions:
        errors.append(f"Missing expected entry point: {relative_path}")
        continue

    if metadata.get("entry_point_present") is False:
        errors.append(f"Entry-point metadata mismatch: {relative_path}")
        continue

    method = metadata.get("method")
    model = metadata.get("model")

    if method not in PROMPT_METHODS | SEARCH_METHODS:
        errors.append(f"Unknown generation method: {relative_path}")
        continue

    if not isinstance(model, str) or not model:
        errors.append(f"Missing model provenance: {relative_path}")
        continue

    if method in SEARCH_METHODS:
        provenance_class = "search_derived"
    else:
        provenance_class = "prompt_generated"

    groups[task_id][digest].append({
        "path": relative_path,
        "metadata_path": str(metadata_path.relative_to(ROOT)),
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "phase1_recorded_code_sha256": recorded_hash,
        "saved_file_sha256": digest,
        "code_hash_normalization": "remove_exactly_one_final_LF",
        "model": model,
        "method": method,
        "provenance_class": provenance_class,
        "run_id": metadata.get("run_id"),
        "candidate_index": metadata.get("candidate_index"),
        "parent": metadata.get("parent"),
        "other_parent": metadata.get("other_parent"),
        "action": metadata.get("action"),
        "fitness_is_correctness": metadata.get("fitness_is_correctness"),
    })

if errors:
    print("\nREGISTRY BUILD BLOCKED:")
    for error in errors:
        print(" -", error)
    raise SystemExit(
        "Fix or adjudicate provenance errors before creating a registry."
    )

registry = {
    "schema_version": 1,
    "protocol": "phase2e_candidate_registry_v1_1",
    "status": "development_pilot_not_correctness_evaluated",
    "tasks": {},
    "excluded_files": excluded,
    "notes": [
        "Source hashes deduplicated within each task.",
        "Search-derived outputs may share candidate ancestry.",
        "Prompt-generated does not guarantee statistical independence.",
        "Diagnostic and syntax-invalid files excluded.",
        "No correctness labels established.",
        "HumanEval/1 has known cross-partition overlap concerns.",
        "No held-out performance claims authorized.",
    ],
}

for task_id in sorted(TASKS):
    candidates = []

    for digest, occurrences in sorted(groups[task_id].items()):
        occurrences.sort(key=lambda x: x["path"])

        categories = sorted({
            item["provenance_class"] for item in occurrences
        })

        candidates.append({
            "candidate_id": f"{task_id}:{digest[:16]}",
            "task_id": task_id,
            "source_sha256": digest,
            "representative_path": occurrences[0]["path"],
            "occurrence_count": len(occurrences),
            "provenance_classes": categories,
            "occurrences": occurrences,
            "correctness_status": "not_evaluated",
        })

    registry["tasks"][task_id] = {
        "entry_point": TASKS[task_id],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }

    count = sum(c["occurrence_count"] for c in candidates)
    print(f"\n{task_id}")
    print("Syntax-valid eligible files:", count)
    print("Unique implementations:", len(candidates))
    print("Duplicate copies:", count - len(candidates))

print("\nExcluded files:", len(excluded))
for item in excluded:
    print(" ", item["reason"], "|", item["path"])

output_dir = ROOT / "results" / "phase2e"
output_dir.mkdir(parents=True, exist_ok=True)

output = output_dir / "candidate_registry_v1_1.json"
payload = json.dumps(registry, indent=2, sort_keys=True).encode("utf-8") + b"\n"

# Never silently replace an existing research registry.
with output.open("xb") as handle:
    handle.write(payload)

print("\nREGISTRY CREATED")
print("Path:", output.relative_to(ROOT))
print("SHA256:", hashlib.sha256(payload).hexdigest())
print("No candidate programs executed.")
print("No Docker or Gemini calls.")
print("Original generation files unchanged.")
