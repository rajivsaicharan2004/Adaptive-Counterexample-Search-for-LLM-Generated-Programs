import json
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "data" / "public"
PRIVATE = ROOT / "data" / "private"

PUBLIC.mkdir(parents=True, exist_ok=True)
PRIVATE.mkdir(parents=True, exist_ok=True)

REPO = "livecodebench/code_generation_lite"
RELEASE = "release_v6"
EXPECTED = 1055

RELEASE_FILES = [
    "test.jsonl",
    "test2.jsonl",
    "test3.jsonl",
    "test4.jsonl",
    "test5.jsonl",
    "test6.jsonl",
]


def decode_json(value):
    if not value:
        return None

    if not isinstance(value, str):
        return value

    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def read_jsonl(path):
    if not path.exists():
        return []

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
            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    default=str
                ) + "\n"
            )

    temp.replace(path)


def main():
    combined_path = PUBLIC / "problems.jsonl"

    if not combined_path.exists():
        raise RuntimeError(
            "Prepare HumanEval and MBPP first."
        )

    print("Connecting to official LiveCodeBench...")

    api = HfApi()

    revision = api.repo_info(
        repo_id=REPO,
        repo_type="dataset"
    ).sha

    files = api.list_repo_files(
        repo_id=REPO,
        repo_type="dataset",
        revision=revision
    )

    source_files = [
        filename for filename in RELEASE_FILES
        if filename in files
    ]

    if source_files != RELEASE_FILES:
        raise RuntimeError(
            f"Incomplete {RELEASE} release files: "
            f"found {source_files}"
        )

    print("Release:", RELEASE)
    print("JSONL files:", len(source_files))

    public_records = []
    evaluation_index = []

    for index, filename in enumerate(source_files, 1):
        print(
            f"Reading file {index}/{len(source_files)}..."
        )

        local_path = hf_hub_download(
            repo_id=REPO,
            filename=filename,
            repo_type="dataset",
            revision=revision,
        )

        # The source JSONL includes private tests; only public fields
        # are copied into generated output files.
        with open(local_path, encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                p = json.loads(line)
                platform = str(
                    p.get("platform") or "unknown"
                ).lower()

                question_id = str(p["question_id"])

                task_id = (
                    f"LiveCodeBench/"
                    f"{platform}/{question_id}"
                )

                metadata = decode_json(
                    p.get("metadata")
                )

                if not isinstance(metadata, dict):
                    metadata = {}

                entry_point = metadata.get(
                    "func_name"
                )

                title = p.get("question_title") or ""
                content = p.get("question_content") or ""
                starter = p.get("starter_code") or ""

                prompt = f"{title}\n\n{content}"

                if starter.strip():
                    prompt += (
                        "\n\nStarter code:\n"
                        + starter
                    )

                public_records.append({
                    "task_id": task_id,
                    "dataset": "livecodebench",
                    "split": RELEASE,
                    "prompt": prompt,
                    "entry_point": entry_point,
                    "starter_code": starter,
                    "difficulty": p.get("difficulty"),
                    "platform": platform,
                    "contest_id": p.get("contest_id"),
                    "contest_date": str(
                        p.get("contest_date") or ""
                    ),
                    "constraints": None,
                    "public_examples": decode_json(
                        p.get("public_test_cases")
                    ),
                    "metadata": metadata,
                    "source_revision": revision,
                })

                evaluation_index.append({
                    "task_id": task_id,
                    "dataset": "livecodebench",
                    "source_release": RELEASE,
                    "source_revision": revision,
                    "source_file": filename,
                    "private_tests_in_source": True,
                    "private_tests_exported": False,
                })

    if len(public_records) != EXPECTED:
        raise RuntimeError(
            f"Expected {EXPECTED} problems, "
            f"found {len(public_records)}"
        )

    ids = [r["task_id"] for r in public_records]

    if len(ids) != len(set(ids)):
        raise RuntimeError(
            "Duplicate LiveCodeBench task IDs"
        )

    existing = read_jsonl(combined_path)

    # Re-running the script replaces only the
    # LiveCodeBench records, not other datasets.
    existing = [
        p for p in existing
        if p.get("dataset") != "livecodebench"
    ]

    existing_ids = {
        p["task_id"] for p in existing
    }

    overlap = existing_ids.intersection(ids)

    if overlap:
        raise RuntimeError(
            f"Task ID collision: {next(iter(overlap))}"
        )

    write_jsonl(
        PUBLIC / "livecodebench.jsonl",
        public_records
    )

    write_jsonl(
        PRIVATE / "livecodebench_evaluation_index.jsonl",
        evaluation_index
    )

    write_jsonl(
        combined_path,
        existing + public_records
    )

    print("\n===== SUCCESS =====")
    print("LiveCodeBench:", len(public_records))
    print("Total problems:", len(existing) + len(public_records))
    print("Public:", "data/public/livecodebench.jsonl")
    print("Combined:", "data/public/problems.jsonl")
    print("Private tests: Present in source cache; not exported")
    print("Release:", RELEASE)
    print("Revision:", revision)
    print("Gemini API calls: 0")


if __name__ == "__main__":
    main()
