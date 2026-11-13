#!/usr/bin/env python3
"""Phase 2C: retrospective, matched-prefix execution-budget sensitivity.

Read Phase 2B-5 *development-only* synthetic fault benchmark JSON reports.
For every mutant/method, first_verified_failure_at_candidate_executions
is the earliest detection on that run's ordered 40-execution trial. Reuse
that first-hit cost to evaluate smaller budgets WITHOUT generating new test
cases or running Docker. The smaller-budget corpus is therefore a prefix
of the SAME run (not an independent fresh sample).

No model calls, reference calls, Docker, dependencies, or held-out data.
Only the original Phase 2B-5 definition of 'detected' is reproduced;
method semantics and oracle costs are not interchangeable.
"""

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics

METHODS = ("property", "mutation", "differential", "metamorphic")
TASKS = ("HumanEval/0", "HumanEval/1")


def validated_report(path, max_budget):
    """Return (seed, doc), or None for other studies / budgets / task subsets."""
    with path.open("r", encoding="utf-8") as handle:
        doc = json.load(handle)
    if doc.get("suite") != "synthetic_fault_detection_development":
        return None
    if doc.get("candidate_executions_per_mutant_per_method") != max_budget:
        return None
    if doc.get("official_or_held_out") is not False:
        raise ValueError(f"Refusing official/held-out or unlabeled report: {path}")
    mutants = doc.get("mutants")
    if not isinstance(mutants, list) or len(mutants) != 10:
        return None  # Skip single-task pilot runs (five mutants).
    seen = set()
    for row in mutants:
        key = (row.get("task_id"), row.get("mutant_id"))
        if key in seen or key[0] not in TASKS or not key[1]:
            raise ValueError(f"Invalid or duplicate mutant identifier: {path}: {key}")
        seen.add(key)
        if row.get("synthetic_diagnostic") is not True:
            raise ValueError(f"Non-synthetic candidate in report: {path}")
        if set(row.get("methods", {})) != set(METHODS):
            raise ValueError(f"Missing method entry for mutant {key} in {path}")
        for method, result in row["methods"].items():
            cost = result.get("first_verified_failure_at_candidate_executions")
            detected = result.get("detected")
            spent = result.get("candidate_executions")
            if type(detected) is not bool or spent != max_budget:
                raise ValueError(f"Invalid detection or execution count in {path}: {key}/{method}")
            if detected != (cost is not None):
                raise ValueError(f"Hit-cost and detection flag disagree: {path}: {key}/{method}")
            if cost is not None and (type(cost) is not int or
                                     not 1 <= cost <= max_budget or
                                     (method in ("differential", "metamorphic") and cost % 2)):
                raise ValueError(f"Invalid first-hit cost: {path}: {key}/{method}={cost}")
    if len({t for t, _ in seen}) != 2:
        raise ValueError(f"Expected two tasks in {path}")
    seed = doc.get("seed")
    if type(seed) is not int:
        raise ValueError(f"Missing integer seed: {path}")
    return seed, doc


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    p = argparse.ArgumentParser(description="Budget sensitivity from completed Phase 2B-5 reports (no Docker)")
    p.add_argument("--reports-dir", default="results/phase2b")
    p.add_argument("--out-dir", default="results/phase2c")
    p.add_argument("--seeds", nargs="+", type=int, default=list(range(2026, 2032)))
    p.add_argument("--budgets", nargs="+", type=int, default=[4, 10, 20, 30, 40])
    p.add_argument("--max-budget", type=int, default=40,
                   help="Budget of the already-completed source reports")
    p.add_argument("--allow-missing", action="store_true",
                   help="Process available selected seeds when others are missing")
    args = p.parse_args()
    budgets = sorted(set(args.budgets))
    seeds = sorted(set(args.seeds))
    if not seeds or not budgets or any(b < 2 or b % 2 or b > args.max_budget for b in budgets):
        p.error("Budgets must be positive, even, and at most --max-budget")
    source_dir = Path(args.reports_dir).expanduser().resolve()
    if not source_dir.is_dir():
        p.error(f"Reports directory not found: {source_dir}")

    by_seed = {}
    for path in sorted(source_dir.glob("fault_benchmark_*_report.json")):
        result = validated_report(path, args.max_budget)
        if result is None:
            continue
        seed, doc = result
        if seed not in seeds:
            continue
        # Use latest completed report if repeated runs exist for the same seed.
        if seed not in by_seed or path.stat().st_mtime_ns > by_seed[seed][0].stat().st_mtime_ns:
            by_seed[seed] = (path, doc)
    missing = [seed for seed in seeds if seed not in by_seed]
    if missing and not args.allow_missing:
        p.error(f"Missing full-budget, two-task development reports for seeds {missing}. "
                "Use --allow-missing to analyze an incomplete set.")
    if not by_seed:
        p.error("No eligible full-budget reports found")

    output = Path(args.out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    seed_rows, mutant_rows, first_rows, corpus_rows = [], [], [], []
    detections = defaultdict(dict)  # (budget, method, seed) -> detected count
    per_mutant = defaultdict(list)
    corpora = defaultdict(set)  # (task, method) -> hashes across selected seeds

    for seed, (source, doc) in sorted(by_seed.items()):
        for task in TASKS:
            hashes = doc.get("tasks", {}).get(task, {}).get("corpus_sha256", {})
            for method in METHODS:
                digest = hashes.get(method)
                if digest:
                    corpora[(task, method)].add(digest)
        rows = doc["mutants"]
        for mutant in rows:
            task, name = mutant["task_id"], mutant["mutant_id"]
            for method in METHODS:
                result = mutant["methods"][method]
                first = result["first_verified_failure_at_candidate_executions"]
                first_rows.append({"seed": seed, "task_id": task, "mutant_id": name,
                                   "method": method, "full_budget": args.max_budget,
                                   "first_failure_cost": "" if first is None else first,
                                   "detected_at_full_budget": int(first is not None),
                                   "source_report": str(source)})
                for budget in budgets:
                    hit = int(first is not None and first <= budget)
                    key = (budget, method, seed)
                    detections[key][(task, name)] = hit
                    per_mutant[(budget, method, task, name)].append(hit)
        for budget in budgets:
            for method in METHODS:
                hits = detections[(budget, method, seed)]
                if len(hits) != 10:
                    raise RuntimeError(f"Expected 10 mutants, got {len(hits)}: {seed}/{method}")
                count = sum(hits.values())
                seed_rows.append({"seed": seed, "budget": budget, "method": method,
                                  "detected_mutants": count, "total_mutants": 10,
                                  "detection_percent": 10 * count,
                                  "total_candidate_executions": 10 * budget,
                                  "source_report": str(source)})

    summary_rows = []
    for budget in budgets:
        for method in METHODS:
            counts = [sum(detections[(budget, method, seed)].values()) for seed in sorted(by_seed)]
            summary_rows.append({
                "budget_per_mutant": budget, "method": method, "n_seeds": len(counts),
                "mean_detected_out_of_10": round(statistics.mean(counts), 4),
                "sample_sd": round(statistics.stdev(counts), 4) if len(counts) > 1 else "",
                "min_detected": min(counts), "max_detected": max(counts),
                "mean_detection_percent": round(10 * statistics.mean(counts), 2),
            })
    for (budget, method, task, name), values in sorted(per_mutant.items()):
        mutant_rows.append({"budget": budget, "method": method, "task_id": task,
                            "mutant_id": name, "seeds_detected": sum(values),
                            "n_seeds": len(values), "detection_fraction": round(statistics.mean(values), 4)})
    for task in TASKS:
        for method in METHODS:
            unique = len(corpora[(task, method)])
            corpus_rows.append({"task_id": task, "method": method, "distinct_corpus_hashes": unique,
                                "n_seeds": len(by_seed),
                                "identical_corpus_across_seeds": unique == 1 and len(by_seed) > 1})

    write_csv(output / "budget_per_seed.csv",
              ["seed", "budget", "method", "detected_mutants", "total_mutants",
               "detection_percent", "total_candidate_executions", "source_report"], seed_rows)
    write_csv(output / "budget_summary.csv",
              ["budget_per_mutant", "method", "n_seeds", "mean_detected_out_of_10",
               "sample_sd", "min_detected", "max_detected", "mean_detection_percent"], summary_rows)
    write_csv(output / "budget_per_mutant.csv",
              ["budget", "method", "task_id", "mutant_id", "seeds_detected",
               "n_seeds", "detection_fraction"], mutant_rows)
    write_csv(output / "first_failure_costs.csv",
              ["seed", "task_id", "mutant_id", "method", "full_budget",
               "first_failure_cost", "detected_at_full_budget", "source_report"], first_rows)
    write_csv(output / "corpus_diversity.csv",
              ["task_id", "method", "distinct_corpus_hashes", "n_seeds",
               "identical_corpus_across_seeds"], corpus_rows)

    lines = ["# Phase 2C — Matched-prefix budget-sensitivity study", "",
             "Development-only evidence on ten synthetic mutants (five per HumanEval task).",
             "No additional test execution was performed; smaller budgets are prefixes of saved runs.", "",
             "| Budget per mutant | Property | Mutation | Differential | Metamorphic |",
             "|---:|---:|---:|---:|---:|"]
    for budget in budgets:
        values = []
        for method in METHODS:
            entry = next(row for row in summary_rows if row["budget_per_mutant"] == budget
                         and row["method"] == method)
            values.append(f"{entry['mean_detected_out_of_10']:.2f}/10")
        lines.append(f"| {budget} | " + " | ".join(values) + " |")
    lines += ["", "## Corpus-diversity diagnostic", "",
              "| Task | Method | Distinct input corpora across selected seeds |",
              "|---|---|---:|"]
    for row in corpus_rows:
        lines.append(f"| {row['task_id']} | {row['method']} | {row['distinct_corpus_hashes']} |")
    lines += ["", "## Interpretation cautions", "",
              "- The same ten synthetic mutants appear in every run. Seeds are not independent mutants or tasks.",
              "- If a method has only one distinct corpus hash across seeds, seed repetitions for that method are not independent input samples.",
              "- Differential detection requires both disagreement and reference-confirmed target failure; metamorphic detection follows the original benchmark's verified-signal definition.",
              "- Candidate/probe executions are budget-matched, but reference-oracle calls, generator overhead, and wall-clock costs are not.",
              "- Prefix curves are exact for the saved ordered trials; they do not predict the outcomes of separately regenerated shorter runs.",
              "- These results are not held-out benchmark scores or accuracy estimates for real Gemini-generated programs.", ""]
    (output / "budget_study.md").write_text("\n".join(lines), encoding="utf-8")

    print("Phase 2C — matched-prefix budget sensitivity (DEVELOPMENT only)")
    print(f"Loaded {len(by_seed)} full-budget reports, seeds: {', '.join(map(str, sorted(by_seed)))}")
    print("\nAverage distinct synthetic mutants detected (out of 10):")
    print(f"{'B':>5} {'property':>11} {'mutation':>11} {'differential':>13} {'metamorphic':>13}")
    for budget in budgets:
        scores = [next(row["mean_detected_out_of_10"] for row in summary_rows
                       if row["budget_per_mutant"] == budget and row["method"] == method)
                  for method in METHODS]
        print(f"{budget:>5} {scores[0]:>11.2f} {scores[1]:>11.2f} {scores[2]:>13.2f} {scores[3]:>13.2f}")
    for task in TASKS:
        for method in METHODS:
            if len(corpora[(task, method)]) == 1 and len(by_seed) > 1:
                print(f"CAUTION: {task}/{method} has identical corpus hashes across all seeds.")
    print(f"\nSaved five CSV files and budget_study.md under: {output}")
    print("Development evidence only. No Docker, oracle, or model calls were made.")


if __name__ == "__main__":
    main()
