#!/usr/bin/env python3
"""Reproducible, conservative lexical screening of prepared PUBLIC programming tasks.

No generated code is run. No models, network, Docker, or private data are used.
Never writes source datasets or partition manifest. Optional --export-dir writes
standalone *review leads* only; scores are not semantic duplicate verdicts.

Usage:
    python phase2d_global_overlap_audit.py --self-test
    python phase2d_global_overlap_audit.py --top 60
    python phase2d_global_overlap_audit.py --top 100 --export-dir results/phase2d/global_overlap_review
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys

DATASETS = ("humaneval", "mbpp", "bigcodebench", "livecodebench")
EXPECTED_COUNT = 3333
TOKEN_PATTERN = re.compile(r"[a-z][a-z0-9_]*|\d+", re.IGNORECASE)
WORD_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "each",
    "for", "from", "has", "have", "if", "in", "into", "is", "it", "its",
    "of", "on", "or", "should", "that", "the", "their", "them", "then",
    "there", "these", "this", "to", "using", "was", "were", "when", "where",
    "which", "while", "will", "with", "you", "your", "write", "self", "contained",
    "code", "starting", "function", "outputs", "output", "returns", "return",
})
GENERIC_STOP_PATTERNS = (
    re.compile(r"\byou should write self-contained code starting with\s*:", re.I),
    re.compile(r"\bstarter code\s*:", re.I),
)


def normalized_prompt(value: str) -> str:
    """Matches the hash convention in phase2d_bcb854_overlap_audit.py."""
    return re.sub(r"\s+", " ", value.lower()).strip()


def strip_template(text: str) -> str:
    """Remove appended source boilerplate/code; preserve semantic specification prose.

    A false positive here can suppress relevant text: every output remains a
    candidate for human review, and exact raw normalized hashes use full prompts.
    """
    result = text
    for pattern in GENERIC_STOP_PATTERNS:
        match = pattern.search(result)
        if match:
            result = result[:match.start()]
    return result


def words(text: str) -> list[str]:
    return [tok.lower() for tok in TOKEN_PATTERN.findall(text)
            if tok.lower() not in WORD_STOPWORDS and len(tok) >= 2]


def features(prompt: str) -> frozenset[str]:
    toks = words(strip_template(prompt))
    fs = {"w:" + t for t in toks}
    # Adjacent phrase features strengthen matching on specific problem semantics.
    fs.update("b:" + a + "_" + b for a, b in zip(toks, toks[1:]))
    return frozenset(fs)


def char_ngrams(prompt: str) -> frozenset[str]:
    text = normalized_prompt(strip_template(prompt))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    if len(text) < 5:
        return frozenset([text]) if text else frozenset()
    return frozenset(text[i:i + 5] for i in range(len(text) - 4))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Task:
    task_id: str
    dataset: str
    prompt: str
    normalized_hash: str
    partition: str
    feature_set: frozenset[str]


def load_and_verify(root: Path, *, expected_count: int | None = EXPECTED_COUNT):
    """Fail closed on duplicate IDs, hash mismatches, missing partitions, bad schema."""
    public_paths = [root / "data" / "public" / f"{dataset}.jsonl"
                    for dataset in DATASETS]
    manifest_path = root / "results" / "phase2d" / "splits.json"
    if not manifest_path.is_file():
        raise ValueError(f"Missing partition manifest: {manifest_path}")
    with manifest_path.open(encoding="utf-8") as source:
        manifest = json.load(source)
    entries = manifest.get("tasks")
    if not isinstance(entries, dict):
        raise ValueError("Manifest must contain a tasks mapping")
    if not isinstance(manifest.get("status"), str):
        raise ValueError("Manifest is missing a string status")

    tasks: list[Task] = []
    seen: set[str] = set()
    for dataset, path in zip(DATASETS, public_paths):
        if not path.is_file():
            raise ValueError(f"Missing dataset file: {path}")
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as err:
                    raise ValueError(f"Invalid JSON at {path}:{line_number}") from err
                task_id = row.get("task_id")
                prompt = row.get("prompt")
                if not isinstance(task_id, str) or not task_id:
                    raise ValueError(f"Invalid task ID at {path}:{line_number}")
                if task_id in seen:
                    raise ValueError(f"Duplicate public task ID: {task_id}")
                seen.add(task_id)
                if row.get("dataset") != dataset or not isinstance(prompt, str):
                    raise ValueError(f"Malformed public record {task_id}")
                entry = entries.get(task_id)
                if not isinstance(entry, dict):
                    raise ValueError(f"Missing or malformed manifest entry: {task_id}")
                partition = entry.get("partition")
                if not isinstance(partition, str) or not partition:
                    raise ValueError(f"Missing partition: {task_id}")
                norm_hash = sha256_text(normalized_prompt(prompt))
                if entry.get("public_prompt_sha256") != norm_hash:
                    raise ValueError(f"Prompt SHA256 mismatch: {task_id}")
                if entry.get("dataset") != dataset:
                    raise ValueError(f"Manifest dataset mismatch: {task_id}")
                tasks.append(Task(task_id, dataset, prompt, norm_hash,
                                  partition, features(prompt)))
    if set(entries) != seen:
        raise ValueError(f"Manifest/public IDs differ: {len(seen - set(entries))} missing, "
                         f"{len(set(entries) - seen)} extra")
    if expected_count is not None and len(tasks) != expected_count:
        raise ValueError(f"Expected {expected_count} tasks, got {len(tasks)}")
    paths = [manifest_path] + public_paths
    provenance = {str(p.relative_to(root)): sha256_file(p) for p in paths}
    return tasks, manifest, provenance


def get_exact_groups(tasks: list[Task]) -> list[dict]:
    buckets: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        buckets[task.normalized_hash].append(task)
    groups = []
    for digest, members in buckets.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda t: t.task_id)
        groups.append({
            "normalized_prompt_sha256": digest,
            "task_ids": [t.task_id for t in members],
            "partitions": sorted({t.partition for t in members}),
            "datasets": sorted({t.dataset for t in members}),
            "cross_partition": len({t.partition for t in members}) > 1,
        })
    return sorted(groups, key=lambda g: (-len(g["task_ids"]), g["task_ids"]))


def weighted_jaccard(a: frozenset[str], b: frozenset[str], idf: dict) -> float:
    union = a | b
    if not union:
        return 0.0
    numerator = sum(idf[t] for t in a & b)
    denominator = sum(idf[t] for t in union)
    return numerator / denominator if denominator else 0.0


def lexical_pairs(tasks: list[Task], *, max_df: int = 150,
                  min_score: float = 0.12):
    """Sparse inverted-index candidate search; no candidate program execution.

    This is intentionally NOT exhaustive semantic retrieval: pairs sharing no
    rare lexical features can be missed. Exact full-prompt duplicates are
    recovered separately, even when their vocabulary is entirely boilerplate.
    """
    n = len(tasks)
    doc_freq = Counter(token for task in tasks for token in task.feature_set)
    idf = {t: math.log((n + 1) / (df + 1)) + 1 for t, df in doc_freq.items()}
    eligible_df = min(max_df, max(5, math.ceil(n * 0.10)))
    postings: dict[str, list[int]] = defaultdict(list)
    for i, task in enumerate(tasks):
        for token in task.feature_set:
            if doc_freq[token] <= eligible_df:
                postings[token].append(i)

    # Candidate generation is a union of rare-feature inverted lists.
    # Same-partition pairs are retained as review leads, but cross-partition
    # leads are highlighted and ranked separately.
    candidates: set[tuple[int, int]] = set()
    for posting in postings.values():
        if len(posting) < 2:
            continue
        posting.sort()
        for ai, a in enumerate(posting[:-1]):
            for b in posting[ai + 1:]:
                candidates.add((a, b))

    pairs = []
    for i, j in sorted(candidates):
        left, right = tasks[i], tasks[j]
        score = weighted_jaccard(left.feature_set, right.feature_set, idf)
        if score < min_score:
            continue
        pairs.append((score, i, j))
    pairs.sort(key=lambda x: (-x[0], tasks[x[1]].task_id, tasks[x[2]].task_id))
    return pairs, {"eligible_max_document_frequency": eligible_df,
                   "features_indexed": len(postings),
                   "candidate_pair_count": len(candidates),
                   "pairs_above_min_score": len(pairs),
                   "min_score": min_score}, idf


def pair_info(score: float, left: Task, right: Task, idf: dict,
              *, include_excerpt: bool = True) -> dict:
    # Character overlap serves as a second descriptive signal; it does not
    # turn lexical ranking into a semantic equivalence classifier.
    char_left, char_right = char_ngrams(left.prompt), char_ngrams(right.prompt)
    char_union = char_left | char_right
    char_score = (len(char_left & char_right) / len(char_union)) if char_union else 0.0
    entry = {
        "task_a": left.task_id,
        "task_b": right.task_id,
        "dataset_a": left.dataset,
        "dataset_b": right.dataset,
        "partition_a": left.partition,
        "partition_b": right.partition,
        "cross_partition": left.partition != right.partition,
        "same_dataset": left.dataset == right.dataset,
        "lexical_weighted_jaccard": round(score, 6),
        "char_5gram_jaccard": round(char_score, 6),
        "exact_normalized_prompt": left.normalized_hash == right.normalized_hash,
        "review_status": "unreviewed_lexical_lead",
        "verdict": None,
    }
    if include_excerpt:
        entry["prompt_a_excerpt"] = re.sub(r"\s+", " ", strip_template(left.prompt)).strip()[:220]
        entry["prompt_b_excerpt"] = re.sub(r"\s+", " ", strip_template(right.prompt)).strip()[:220]
    return entry


def chosen_review_queue(tasks: list[Task], ranked: list,
                        idf: dict, *, top: int, same_top: int) -> tuple[list, list]:
    cross, same = [], []
    for score, i, j in ranked:
        a, b = tasks[i], tasks[j]
        if a.partition != b.partition and len(cross) < top:
            cross.append(pair_info(score, a, b, idf))
        elif a.partition == b.partition and len(same) < same_top:
            same.append(pair_info(score, a, b, idf))
        if len(cross) >= top and len(same) >= same_top:
            break
    return cross, same


def stratified_cross_dataset_queue(tasks: list[Task], ranked: list, idf: dict,
                                  *, per_dataset_pair: int) -> list[dict]:
    """Ensure cross-dataset similarities are visible beyond the global top-K."""
    groups: dict[tuple[str, str], list] = defaultdict(list)
    for score, i, j in ranked:
        a, b = tasks[i], tasks[j]
        if a.dataset == b.dataset or a.partition == b.partition:
            continue
        key = tuple(sorted((a.dataset, b.dataset)))
        if len(groups[key]) < per_dataset_pair:
            groups[key].append(pair_info(score, a, b, idf))
    result = []
    for key in sorted(groups):
        for row in groups[key]:
            row["dataset_pair"] = " / ".join(key)
            result.append(row)
    return result


def build_report(tasks: list[Task], manifest: dict, provenance: dict,
                 *, top: int, same_top: int, per_dataset_pair: int,
                 max_df: int, min_score: float) -> dict:
    exact = get_exact_groups(tasks)
    ranked, stats, idf = lexical_pairs(tasks, max_df=max_df, min_score=min_score)
    cross, same = chosen_review_queue(tasks, ranked, idf, top=top, same_top=same_top)
    cross_dataset = stratified_cross_dataset_queue(tasks, ranked, idf,
                                                   per_dataset_pair=per_dataset_pair)
    partitions = Counter(t.partition for t in tasks)
    by_dataset = Counter(t.dataset for t in tasks)
    cross_all = sum(tasks[i].partition != tasks[j].partition for _, i, j in ranked)
    # Explicit algorithm and input hashes make this an auditable screening run.
    return {
        "schema_version": 1,
        "report_type": "PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION",
        "source_manifest_status": manifest["status"],
        "all_public_task_count": len(tasks),
        "by_dataset": dict(sorted(by_dataset.items())),
        "by_partition": dict(sorted(partitions.items())),
        "input_sha256": provenance,
        "settings": {"top_cross_partition": top, "top_same_partition": same_top,
                     "cross_dataset_per_pair": per_dataset_pair,
                     "max_document_frequency": max_df, "min_lexical_score": min_score,
                     "tokenizer": "lowercase word and bigram features after common starter-code boilerplate removal",
                     "similarity": "IDF-weighted Jaccard; char 5-grams descriptive only"},
        "screening": {**stats, "cross_partition_pairs_above_threshold": cross_all,
                      "same_partition_pairs_above_threshold": len(ranked) - cross_all},
        "exact_normalized_prompt_groups": exact,
        "cross_partition_review_queue": cross,
        "same_partition_review_queue": same,
        "cross_dataset_stratified_review_queue": cross_dataset,
        "limitations": [
            "Lexical retrieval can miss semantic duplicates with dissimilar wording.",
            "Ranking scores are review leads, not duplicate determinations or probability estimates.",
            "High-ranking pairs may share common task vocabulary without being equivalent.",
            "No split assignments are approved, changed, or frozen by this audit.",
            "Full source revision record equivalence and official evaluation are outside this audit.",
        ],
    }


def display(report: dict, *, max_print: int = 30) -> None:
    print("\nPUBLIC GLOBAL NEAR-DUPLICATE SCREEN — LEXICAL REVIEW LEADS ONLY")
    print("MANIFEST:", report["source_manifest_status"])
    print("TASKS:", report["all_public_task_count"])
    print("DATASETS:", report["by_dataset"])
    print("PARTITIONS:", report["by_partition"])
    print("EXACT NORMALIZED-PROMPT GROUPS:", len(report["exact_normalized_prompt_groups"]))
    print("CROSS-PARTITION EXACT GROUPS:", sum(x["cross_partition"] for x in report["exact_normalized_prompt_groups"]))
    for group in report["exact_normalized_prompt_groups"][:15]:
        print("  EXACT GROUP:", ", ".join(group["task_ids"]),
              "partitions=", ",".join(group["partitions"]))
    print("LEXICAL CANDIDATE PAIRS:", report["screening"]["candidate_pair_count"])
    print("CROSS-PARTITION PAIRS ABOVE THRESHOLD:", report["screening"]["cross_partition_pairs_above_threshold"])
    print("\nCROSS-PARTITION QUEUE (NOT DUPLICATE VERDICTS):")
    for rank, item in enumerate(report["cross_partition_review_queue"][:max_print], 1):
        print(f"{rank:3d}. {item['task_a']} ({item['partition_a']})  <->  "
              f"{item['task_b']} ({item['partition_b']})  "
              f"score={item['lexical_weighted_jaccard']:.3f} "
              f"char5={item['char_5gram_jaccard']:.3f}")
    print("\nSTRATIFIED CROSS-DATASET LEADS:")
    for rank, item in enumerate(report["cross_dataset_stratified_review_queue"][:max_print], 1):
        print(f"{rank:3d}. {item['task_a']} <-> {item['task_b']}  "
              f"score={item['lexical_weighted_jaccard']:.3f} "
              f"pair={item['dataset_pair']}")
    print("\nSAME-PARTITION QUEUE:")
    for rank, item in enumerate(report["same_partition_review_queue"][:min(10,max_print)], 1):
        print(f"{rank:3d}. {item['task_a']} <-> {item['task_b']} "
              f"score={item['lexical_weighted_jaccard']:.3f}")
    print("\nRead-only unless --export-dir specified. No candidate execution, models, Docker, network or private tests.")
    print("NOT a semantic-leakage clearance; manual review and source provenance still required.")


def export_reports(report: dict, out: Path) -> list[Path]:
    """New report files only. Fail closed if any destination already exists."""
    names = ["global_overlap_report.json", "global_overlap_cross_partition.csv",
             "global_overlap_same_partition.csv", "global_overlap_cross_dataset.csv"]
    if out.exists() and not out.is_dir():
        raise ValueError(f"Export destination is not a directory: {out}")
    paths = [out / name for name in names]
    for path in paths:
        if path.exists():
            raise ValueError(f"Refusing to overwrite existing file: {path}")
    out.mkdir(parents=True, exist_ok=True)
    with paths[0].open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    for path, key in zip(paths[1:],
                         ["cross_partition_review_queue", "same_partition_review_queue",
                          "cross_dataset_stratified_review_queue"]):
        with path.open("x", newline="", encoding="utf-8") as f:
            rows = report[key]
            fields = list(rows[0]) if rows else [
                "task_a", "task_b", "partition_a", "partition_b", "lexical_weighted_jaccard",
                "review_status", "verdict"]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return paths


def self_test() -> None:
    def synthetic(tid: str, partition: str, prompt: str) -> Task:
        return Task(tid, "humaneval", prompt,
                    sha256_text(normalized_prompt(prompt)), partition, features(prompt))
    x = synthetic("x", "development", "Generate all permutations of integers and sum factorials")
    y = synthetic("y", "held_out", "generate ALL  permutations of integers and sum factorials")
    z = synthetic("z", "held_out", "Read a CSV file and plot its data")
    tasks = [x, y, z]
    assert normalized_prompt(x.prompt) == normalized_prompt(y.prompt)
    assert len(get_exact_groups(tasks)) == 1
    assert get_exact_groups(tasks)[0]["cross_partition"]
    assert "import os" not in strip_template("compute a factorial. Starter code:\nimport os")
    ranked, _, idf = lexical_pairs(tasks, max_df=100, min_score=0)
    assert any({tasks[i].task_id, tasks[j].task_id} == {"x", "y"}
               for _, i, j in ranked)
    assert weighted_jaccard(x.feature_set, y.feature_set, idf) > weighted_jaccard(
        x.feature_set, z.feature_set, idf)
    assert char_ngrams(x.prompt) == char_ngrams(y.prompt)
    assert not x.feature_set & z.feature_set
    print("SELF-TEST PASS: normalized hashes, exact groups, cross-partition flags, "
          "boilerplate handling, lexical ranking, character n-grams")
    print("No project files read or written.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent,
                    help="Research project root; default: directory containing this script")
    ap.add_argument("--top", type=int, default=80,
                    help="maximum cross-partition review pairs to retain (default: 80)")
    ap.add_argument("--same-top", type=int, default=25,
                    help="maximum same-partition review pairs to retain")
    ap.add_argument("--per-dataset-pair", type=int, default=15,
                    help="review candidates per cross-dataset pair (default: 15)")
    ap.add_argument("--max-df", type=int, default=150,
                    help="ignore features occurring in more than this many public tasks")
    ap.add_argument("--min-score", type=float, default=0.12,
                    help="minimum IDF-weighted Jaccard score for report ranking")
    ap.add_argument("--export-dir", type=Path,
                    help="OPTIONAL: write new review-only JSON/CSV reports here; no overwrites")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.top <= 2000 or not 0 <= args.same_top <= 2000:
        ap.error("--top must be 1..2000 and --same-top 0..2000")
    if args.max_df < 2 or not 0 <= args.min_score <= 1 or not 0 <= args.per_dataset_pair <= 200:
        ap.error("--max-df must be >=2 and --min-score must be 0..1")
    try:
        root = args.root.resolve()
        tasks, manifest, provenance = load_and_verify(root)
        report = build_report(tasks, manifest, provenance, top=args.top,
                              same_top=args.same_top, per_dataset_pair=args.per_dataset_pair,
                              max_df=args.max_df,
                              min_score=args.min_score)
        display(report)
        if args.export_dir is not None:
            paths = export_reports(report, args.export_dir)
            print("\nCREATED REVIEW REPORTS:")
            for path in paths:
                print(" ", path)
    except (ValueError, OSError) as err:
        print(f"AUDIT FAILED CLOSED: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
