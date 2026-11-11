import ast
import gzip
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PUBLIC = ROOT / "data" / "public"
PRIVATE = ROOT / "data" / "private"

for folder in (RAW, PUBLIC, PRIVATE):
    folder.mkdir(parents=True, exist_ok=True)

DATASETS = {
    "humaneval": {
        "url": (
            "https://raw.githubusercontent.com/openai/"
            "human-eval/master/data/HumanEval.jsonl.gz"
        ),
        "path": RAW / "HumanEval.jsonl.gz",
        "sha256": (
            "b796127e635a67f93fb35c04f4cb03"
            "cf06f38c8072ee7cee8833d7bee06979ef"
        ),
        "count": 164,
    },
    "mbpp": {
        "url": (
            "https://raw.githubusercontent.com/"
            "google-research/google-research/master/"
            "mbpp/mbpp.jsonl"
        ),
        "path": RAW / "mbpp.jsonl",
        "sha256": (
            "ccf64ceae9c5403bf50a044cb6d505bf"
            "d2a2963ee58338ba268fd65beab92a9f"
        ),
        "count": 974,
    },
}


def download(name, config):
    path = config["path"]

    if not path.exists():
        print(f"Downloading {name}...")
        urllib.request.urlretrieve(config["url"], path)

    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    if digest != config["sha256"]:
        raise RuntimeError(
            f"{name}: checksum mismatch. "
            f"Delete {path} and retry."
        )

    print(f"Verified {name}: SHA256 OK")
    return path


def read_jsonl(path):
    opener = gzip.open if path.suffix == ".gz" else open

    with opener(path, "rt", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )


def mbpp_split(task_id):
    if 1 <= task_id <= 10:
        return "few_shot"
    if 11 <= task_id <= 510:
        return "test"
    if 511 <= task_id <= 600:
        return "validation"
    return "train"


def infer_entry_point(code, tests):
    # Identify the function tested by MBPP.
    try:
        tree = ast.parse(code)
        names = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
    except SyntaxError:
        names = set()

    for test in tests:
        try:
            test_tree = ast.parse(test)
        except SyntaxError:
            continue

        for node in ast.walk(test_tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in names:
                        return node.func.id

    if len(names) == 1:
        return next(iter(names))

    return None


def prepare_humaneval(records):
    public = []
    private = []

    for p in records:
        task_id = p["task_id"]

        public.append({
            "task_id": task_id,
            "dataset": "humaneval",
            "split": "test",
            "prompt": p["prompt"],
            "entry_point": p["entry_point"],
            "constraints": None,
            "public_examples": [],
        })

        private.append({
            "task_id": task_id,
            "dataset": "humaneval",
            "entry_point": p["entry_point"],
            "reference_solution": (
                p["prompt"] + p["canonical_solution"]
            ),
            "test": p["test"],
        })

    return public, private


def prepare_mbpp(records):
    public = []
    private = []

    for p in records:
        task_id = f"MBPP/{p['task_id']}"

        entry_point = infer_entry_point(
            p["code"],
            p["test_list"],
        )

        public.append({
            "task_id": task_id,
            "dataset": "mbpp",
            "split": mbpp_split(p["task_id"]),
            "prompt": p["text"],
            "entry_point": entry_point,
            "constraints": None,
            "public_examples": [],
        })

        private.append({
            "task_id": task_id,
            "dataset": "mbpp",
            "entry_point": entry_point,
            "reference_solution": p["code"],
            "test_setup_code": p.get(
                "test_setup_code", ""
            ),
            "test_list": p["test_list"],
            "challenge_test_list": p.get(
                "challenge_test_list", []
            ),
        })

    return public, private


def main():
    all_public = []
    all_private = []

    for name, config in DATASETS.items():
        path = download(name, config)
        records = read_jsonl(path)

        if len(records) != config["count"]:
            raise ValueError(
                f"{name}: expected {config['count']} "
                f"problems, received {len(records)}"
            )

        if name == "humaneval":
            pub, priv = prepare_humaneval(records)
        else:
            pub, priv = prepare_mbpp(records)

        write_jsonl(
            PUBLIC / f"{name}.jsonl", pub
        )
        write_jsonl(
            PRIVATE / f"{name}_evaluation.jsonl",
            priv,
        )

        all_public.extend(pub)
        all_private.extend(priv)

        print(f"{name}: {len(pub)} problems prepared")

    ids = [p["task_id"] for p in all_public]

    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate task IDs detected")

    write_jsonl(
        PUBLIC / "problems.jsonl",
        all_public,
    )

    write_jsonl(
        PRIVATE / "reference_tests.jsonl",
        all_private,
    )

    print("\n===== DATASET READY =====")
    print("HumanEval: 164 problems")
    print("MBPP: 974 problems")
    print("Combined base dataset: 1138 problems")
    print()
    print("Base public dataset:")
    print("data/public/problems.jsonl")
    print()
    print("Evaluation-only data:")
    print("data/private/reference_tests.jsonl")
    print()
    print("No Gemini API calls were made.")


if __name__ == "__main__":
    main()
