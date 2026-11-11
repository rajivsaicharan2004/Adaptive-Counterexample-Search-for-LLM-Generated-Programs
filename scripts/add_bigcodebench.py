import json
from pathlib import Path

from datasets import load_dataset

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "data" / "public"
PRIVATE = ROOT / "data" / "private"

PUBLIC.mkdir(parents=True, exist_ok=True)
PRIVATE.mkdir(parents=True, exist_ok=True)

combined_path = PUBLIC / "problems.jsonl"

if not combined_path.exists():
    raise RuntimeError(
        "Run prepare_problems.py successfully first."
    )


def read_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [
            json.loads(line)
            for line in f
            if line.strip()
        ]


def write_jsonl(path, records):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    temp.replace(path)


print("Downloading BigCodeBench...")

dataset = load_dataset(
    "bigcode/bigcodebench",
    split="v0.1.4"
)

public_records = []
private_records = []

for item in dataset:
    task_id = item["task_id"]

    public_records.append({
        "task_id": task_id,
        "dataset": "bigcodebench",
        "split": "test",
        "prompt": item["instruct_prompt"],
        "entry_point": item["entry_point"],
        "starter_code": item["code_prompt"],
        "constraints": None,
        "public_examples": []
    })

    private_records.append({
        "task_id": task_id,
        "dataset": "bigcodebench",
        "entry_point": item["entry_point"],
        "code_prompt": item["code_prompt"],
        "canonical_solution": item["canonical_solution"],
        "test": item["test"]
    })

assert len(public_records) == 1140, (
    f"Unexpected dataset size: {len(public_records)}"
)

combined = read_jsonl(combined_path)

base_ids = {p["task_id"] for p in combined}
if not any(x.startswith("HumanEval/") for x in base_ids):
    raise RuntimeError("HumanEval not found in combined dataset")
if not any(x.startswith("MBPP/") for x in base_ids):
    raise RuntimeError("MBPP not found in combined dataset")

write_jsonl(
    PUBLIC / "bigcodebench.jsonl",
    public_records
)

write_jsonl(
    PRIVATE / "bigcodebench_evaluation.jsonl",
    private_records
)

existing = {p["task_id"] for p in combined}

new_records = [
    p for p in public_records
    if p["task_id"] not in existing
]

combined.extend(new_records)
write_jsonl(combined_path, combined)

print("\nBigCodeBench added successfully!")
print("BigCodeBench problems:", len(public_records))
print("New unique problems added:", len(new_records))
print("Combined total:", len(combined))
print("No Gemini API calls were made.")
