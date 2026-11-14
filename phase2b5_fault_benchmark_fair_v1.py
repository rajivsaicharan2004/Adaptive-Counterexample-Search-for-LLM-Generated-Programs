#!/usr/bin/env python3
"""Phase 2B-5 FAIRNESS V1: controlled DEVELOPMENT fault-detection benchmark.

Compare four *different kinds of checks* on ten explicitly synthetic faulty
programs, five each for HumanEval/0 and HumanEval/1. Reuse the existing Phase
2A Docker executor and the Phase 2B input generators. No LLM calls. No
untrusted candidate code executes on the host. No held-out benchmark tests.

This is a distinct protocol from historical Phase 2B-5; legacy results are not directly comparable.
A budget is the number of target+probe executions per mutant per method:
  property:     B independent candidate executions; reference oracle checks
  mutation:     B independent candidate executions; reference oracle checks
  differential: B/2 inputs x (target + genuine probe) = B executions
  metamorphic:  B/2 pairs x (base + follow-up) = B executions
Reference-oracle executions are separately recorded and reused across mutants.
The property generator is Phase 2D seeded Hypothesis (different prior from legacy).
Different input distributions and shared setup still limit causal comparisons.
A first-discovery execution index is post-hoc, not measured early stopping.
"""

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import random
import statistics
import time
from uuid import uuid4

import phase2a_validator as base
import phase2b2_mutation as mutator
import phase2b4_metamorphic as metamorphic
import hypothesis
from phase2d.strategies import property_inputs as seeded_property_inputs

ROOT = Path(__file__).resolve().parent
TASKS = ("HumanEval/0", "HumanEval/1")

# PURPOSELY DEFECTIVE diagnostic code. Never classify these as Gemini outputs.
# Each mutant has a distinct, documented logic error and a manually constructed
# non-equivalence witness, which is verified separately, NOT injected into trials.
MUTANTS = {
    "HumanEval/0": [
        ("boundary_le", "Uses <= where specification requires <", [[1.0, 2.0], 1.0],
         "def has_close_elements(numbers, threshold):\n"
         "    return any(abs(a-b) <= threshold for i,a in enumerate(numbers) "
         "for b in numbers[i+1:])\n"),
        ("first_two_only", "Examines only the first two elements", [[1.0, 10.0, 10.1], 0.2],
         "def has_close_elements(numbers, threshold):\n"
         "    return len(numbers) >= 2 and abs(numbers[0]-numbers[1]) < threshold\n"),
        ("no_duplicates", "Incorrectly ignores equal-valued elements", [[2.0, 2.0], 0.1],
         "def has_close_elements(numbers, threshold):\n"
         "    return any(a != b and abs(a-b) < threshold for i,a in enumerate(numbers) "
         "for b in numbers[i+1:])\n"),
        ("ignore_negatives", "Incorrectly excludes negative values", [[-2.0, -1.0], 1.1],
         "def has_close_elements(numbers, threshold):\n"
         "    return any(a >= 0 and b >= 0 and abs(a-b) < threshold "
         "for i,a in enumerate(numbers) for b in numbers[i+1:])\n"),
        ("adjacent_only", "Checks only adjacent input positions", [[1.0, 20.0, 1.1], 0.2],
         "def has_close_elements(numbers, threshold):\n"
         "    return any(abs(a-b) < threshold for a,b in zip(numbers, numbers[1:]))\n"),
    ],
    "HumanEval/1": [
        ("retain_spaces", "Does not strip spaces inside groups", ["( )"],
         "def separate_paren_groups(paren_string):\n"
         "    groups=[]\n    depth=0\n    start=0\n"
         "    for i,ch in enumerate(paren_string):\n"
         "        if ch=='(': \n            if depth==0: start=i\n            depth+=1\n"
         "        elif ch==')':\n            depth-=1\n            if depth==0: groups.append(paren_string[start:i+1])\n"
         "    return groups\n"),
        ("merge_groups", "Incorrectly merges all groups into one", ["()()"],
         "def separate_paren_groups(paren_string):\n"
         "    return [paren_string.replace(' ','')]\n"),
        ("reverse_groups", "Incorrectly reverses group order", ["()(())"],
         "def separate_paren_groups(paren_string):\n"
         "    text=paren_string.replace(' ','')\n    depth=0\n    start=0\n    groups=[]\n"
         "    for i,ch in enumerate(text):\n"
         "        depth+=1 if ch=='(' else -1\n"
         "        if depth==0: groups.append(text[start:i+1]); start=i+1\n"
         "    return list(reversed(groups))\n"),
        ("flatten_nesting", "Loses nested parentheses content", ["(())"],
         "def separate_paren_groups(paren_string):\n"
         "    text=paren_string.replace(' ','')\n    depth=0\n    groups=[]\n"
         "    for ch in text:\n"
         "        depth+=1 if ch=='(' else -1\n"
         "        if depth==0: groups.append('()')\n"
         "    return groups\n"),
        ("omit_last", "Incorrectly omits the last group", ["()"],
         "def separate_paren_groups(paren_string):\n"
         "    text=paren_string.replace(' ','')\n    depth=0\n    start=0\n    groups=[]\n"
         "    for i,ch in enumerate(text):\n"
         "        depth+=1 if ch=='(' else -1\n"
         "        if depth==0: groups.append(text[start:i+1]); start=i+1\n"
         "    return groups[:-1]\n"),
    ],
}


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def chunks(items, batch_size):
    for start in range(0, len(items), batch_size):
        yield items[start:start + batch_size]


def execute(code, entry, args_list, batch_size):
    results = []
    for part in chunks(args_list, batch_size):
        results.extend(base.docker_execute(code, [{"entry_point": entry, "args": x} for x in part]))
    if len(results) != len(args_list):
        raise RuntimeError("Sandbox produced an incorrect result count")
    return results


def property_module():
    for module_name in ("phase2b1_validator", "phase2b_property"):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            # Do not silently hide a missing dependency inside a found module.
            if exc.name != module_name:
                raise RuntimeError(f"{module_name} dependency unavailable: {exc}") from exc
    raise RuntimeError("Missing phase2b1_validator.py (Phase 2B-1 Hypothesis generator)")


def property_cases(task, count, seed_value):
    """Explicitly seeded, deterministic Hypothesis corpus from Phase 2D.

    This changes the input prior relative to historical Phase 2B; label every
    new run as FAIRNESS V1, and never pool estimates across protocol versions.
    """
    requested = min(500, max(60, count * 3))
    rows = seeded_property_inputs(task, requested, seed_value)
    selected, seen = [], set()
    invalid = 0
    for args in rows:
        if not valid(task, args):
            invalid += 1
            continue
        key = canonical(args)
        if key in seen:
            continue
        seen.add(key)
        selected.append(args)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise RuntimeError(f"Seeded Hypothesis produced only {len(selected)}/{count}"
                           f" valid distinct {task} cases out of {requested} generated")
    return selected, {
        "generator": "phase2d.strategies.property_inputs",
        "hypothesis_version": hypothesis.__version__,
        "hypothesis_seed": seed_value,
        "hypothesis_derandomize": False,
        "hypothesis_database": None,
        "hypothesis_unique_cases_requested": requested,
        "selected_valid_unique_cases": len(selected),
        "invalid_cases_skipped_before_budget": invalid,
        "corpus_sha256": sha(selected),
        "note": "Hypothesis strategy execution/draw cost is not instrumented; do not claim matching generation cost.",
    }


def valid(task, args):
    if task == "HumanEval/0":
        return mutator.valid_numbers(args)
    return mutator.valid_parens(args)


def probe_code(task, explicit):
    if explicit:
        run_dirs = [(ROOT / explicit).resolve()]
    else:
        run_dirs = sorted((ROOT / "generated/phase1").glob("*_HumanEval_" + task.split("/")[1]))
    for run in run_dirs:
        if not run.is_dir() or "diagnostic" in run.name.lower():
            continue
        try:
            files = base.candidate_files([str(run)], task)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for file in sorted(files, key=lambda p: (not p.name.startswith("direct_"), p.name)):
            meta = json.loads(file.with_suffix(".json").read_text(encoding="utf-8"))
            if meta.get("diagnostic_only") or meta.get("source") == "synthetic_fault_injection":
                continue
            code = file.read_text(encoding="utf-8")
            if len(code.encode("utf-8")) > base.MAX_CODE_BYTES:
                continue
            return code, str(file.relative_to(ROOT))
    raise ValueError(f"No genuine Phase 1 probe candidate found for {task}. "
                     "Provide --probe-run-0 / --probe-run-1 if needed.")


def prepare_corpora(task, budget, seed):
    generation_started = time.perf_counter()
    prop, settings = property_cases(task, budget, seed)
    property_generation_seconds = time.perf_counter() - generation_started
    reviewed = base.load_development_cases(task)
    mutation_started = time.perf_counter()
    mutated, attempts = mutator.build_corpus(task, reviewed, budget, seed)
    mutation_generation_seconds = time.perf_counter() - mutation_started
    mutation = [c["args"] for c in mutated]
    # Differential testing is a screening technique, NOT an independent input
    # generator. It reuses the first B/2 property-generated inputs.
    differential = prop[:budget // 2]
    # Metamorphic testing consumes two executions per relation pair; do not
    # deduplicate between pairs because the budget counts actual executions.
    source = [{"name": f"seed_{i:04d}", "args": args}
              for i, args in enumerate(prop, 1)]
    mr_started = time.perf_counter()
    pairs, attempts_mr = metamorphic.generate_pairs(task, source, budget // 2, seed)
    metamorphic_generation_seconds = time.perf_counter() - mr_started
    mr_flat = [args for pair in pairs for args in (pair["base_args"], pair["followup_args"])]
    for args in prop + mutation + differential + mr_flat:
        if not valid(task, args):
            raise RuntimeError(f"Input-contract violation for {task}: {args!r}")
    return {"property": prop, "mutation": mutation, "differential": differential,
            "metamorphic": mr_flat, "pairs": pairs}, {
        "property_generator": settings,
        "mutation_attempts": attempts,
        "metamorphic_attempts": attempts_mr,
        "generation_wall_seconds": {
            "property": round(property_generation_seconds, 6),
            "mutation": round(mutation_generation_seconds, 6),
            "differential": 0.0,  # Reuses the property corpus; shared cost is in property.
            "metamorphic": round(metamorphic_generation_seconds, 6),
        },
    }


def checked_outputs(task, ref_code, entry, corpora, batch_size):
    expected, oracle_counts = {}, {}
    for method in ("property", "mutation", "differential", "metamorphic"):
        inputs = corpora[method]
        outputs = execute(ref_code, entry, inputs, batch_size)
        for i, output in enumerate(outputs):
            if output.get("status") != "ok":
                raise RuntimeError(f"Reference oracle failed for {task}/{method} case {i}: {output}")
        expected[method] = outputs
        oracle_counts[method] = len(outputs)
    # Independently verify that our transformations are correct for the trusted
    # reference before evaluating any mutants.
    outcomes = expected["metamorphic"]
    for i, pair in enumerate(corpora["pairs"]):
        relation = metamorphic.relation_holds(outcomes[2 * i], outcomes[2 * i + 1],
                                              pair["relation"], pair["relation_info"])
        if relation is not True:
            raise RuntimeError(f"Metamorphic relation {pair['operation']} rejected by "
                               f"reference on pair #{i+1} for {task}")
    return expected, oracle_counts


def reference_matches(result, oracle):
    return base.matching_result(result, oracle["value"], oracle["type"])


def evaluate_method(method, mutant_code, probe, entry, corpora, expected, batch_size):
    started = time.perf_counter()
    inputs, oracle = corpora[method], expected[method]
    mutant_outputs = execute(mutant_code, entry, inputs, batch_size)
    target_executions = len(mutant_outputs)
    probe_executions = 0
    oracle_bad = [not reference_matches(a, b) for a, b in zip(mutant_outputs, oracle)]
    hits = []
    signal_hits = []
    relation_violations = 0
    relation_execution_failures = 0
    probe_wrong = 0
    if method in ("property", "mutation"):
        hits = [i for i, bad in enumerate(oracle_bad) if bad]
        signal_hits = hits[:]
        calls = len(inputs)
    elif method == "differential":
        probe_outputs = execute(probe, entry, inputs, batch_size)
        probe_executions = len(probe_outputs)
        for i, (target, baseline, bad) in enumerate(zip(mutant_outputs, probe_outputs, oracle_bad)):
            same = metamorphic.canonical(target) == metamorphic.canonical(baseline)
            # A differential discovery requires a disagreement AND a reference
            # confirmed failure of the tested mutant.
            if not same and bad:
                hits.append(i)
            if not reference_matches(baseline, oracle[i]):
                probe_wrong += 1
            if not same:
                signal_hits.append(i)
        calls = 2 * len(inputs)
    else:
        calls = len(inputs)
        for i, pair in enumerate(corpora["pairs"]):
            relation = metamorphic.relation_holds(
                mutant_outputs[2 * i], mutant_outputs[2 * i + 1],
                pair["relation"], pair["relation_info"])
            confirmed = oracle_bad[2 * i] or oracle_bad[2 * i + 1]
            if relation is False:
                relation_violations += 1
            elif relation is None:
                relation_execution_failures += 1
            if relation is not True:
                signal_hits.append(i)
                if confirmed:
                    hits.append(i)
    first_hit_cost = None
    if hits:
        first_hit_cost = (hits[0] + 1) if method in ("property", "mutation") else (2 * (hits[0] + 1))
    return {
        "method": method, "detected": bool(hits),
        "verified_signal_count": len(hits),
        "signal_count": len(signal_hits),
        "oracle_wrong_execution_count": sum(oracle_bad),
        "metamorphic_relation_violations": relation_violations,
        "metamorphic_execution_failure_pairs": relation_execution_failures,
        "probe_oracle_wrong_cases": probe_wrong,
        "candidate_executions": calls,  # Historical total target + probe.
        "target_candidate_executions": target_executions,
        "differential_probe_executions": probe_executions,
        "reference_oracle_executions": len(oracle),  # Shared once per task/method.
        "budget_ledger_matches": calls == target_executions + probe_executions,
        "first_verified_failure_at_candidate_executions": first_hit_cost,
        "first_failure_cost_is_posthoc_index": True,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "first_three_verified_signals": [
            {"index": i, "args": (inputs[i] if method != "metamorphic" else
                                      [inputs[2*i], inputs[2*i+1]])}
            for i in hits[:3]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Phase 2B-5: matched candidate-execution fault benchmark")
    parser.add_argument("--task-id", choices=("HumanEval/0", "HumanEval/1", "all"),
                        default="all", help="Pilot one task or run both (default: all)")
    parser.add_argument("--budget", type=int, default=40,
                        help="Candidate+probe executions per mutant per method; EVEN integer 4..200")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--probe-run-0", help="Optional genuine Phase 1 HumanEval/0 run directory")
    parser.add_argument("--probe-run-1", help="Optional genuine Phase 1 HumanEval/1 run directory")
    parser.add_argument("--dry-run", action="store_true", help="Plan trials without Docker or reference execution")
    parser.add_argument("--seed-audit", action="store_true", help="Read-only repeat/different-seed corpus test; no probe or Docker")
    parser.add_argument("--execute-synthetic-docker", action="store_true", help="Explicitly enable synthetic Docker trials (legacy default was execution)")
    args = parser.parse_args()
    if not 4 <= args.budget <= 200 or args.budget % 2:
        parser.error("--budget must be an even integer between 4 and 200")
    if not 1 <= args.batch_size <= min(20, base.MAX_CASES):
        parser.error("--batch-size must be in 1..20 and no greater than Phase 2A MAX_CASES")
    tasks = TASKS if args.task_id == "all" else (args.task_id,)
    total_mutants = sum(len(MUTANTS[t]) for t in tasks)
    print("Phase 2B-5 FAIRNESS V1: Controlled fault-detection benchmark (DEVELOPMENT only)")
    print(f"{total_mutants} synthetic mutants | {len(tasks)} tasks | "
          f"budget {args.budget} candidate executions/method/mutant")
    print("No Gemini calls. No official benchmark scores. Synthetic programs are never genuine candidates.")
    if args.seed_audit:
        if args.execute_synthetic_docker:
            parser.error("--seed-audit cannot be combined with --execute-synthetic-docker")
        for task in tasks:
            a, am = property_cases(task, args.budget, args.seed)
            b, bm = property_cases(task, args.budget, args.seed)
            c, cm = property_cases(task, args.budget, args.seed + 1)
            if a != b:
                raise RuntimeError(f"Seed reproducibility FAILED for {task}")
            if a == c:
                raise RuntimeError(f"Distinct-seed corpus diversity FAILED for {task}")
            print(f"SEED AUDIT PASS {task}: same seed reproducible, adjacent seed changed")
            print(f"  seed={args.seed} sha256={am['corpus_sha256']}")
            print(f"  seed={args.seed+1} sha256={cm['corpus_sha256']}")
        print("Read-only seed audit complete. No probes, candidates, Docker or private tests accessed.")
        return
    if not args.dry_run and not args.execute_synthetic_docker:
        parser.error("Synthetic Docker execution requires --execute-synthetic-docker; use --seed-audit or --dry-run otherwise")
    experiments = {}
    for task in tasks:
        project_probe = args.probe_run_0 if task == "HumanEval/0" else args.probe_run_1
        probe, path = probe_code(task, project_probe)
        corpus, generation = prepare_corpora(task, args.budget, args.seed)
        for method in ("property", "mutation", "differential", "metamorphic"):
            print(f"  {task} / {method}: {len(corpus[method])} inputs")
        print(f"  Differential probe: {path}")
        experiments[task] = {"probe": probe, "probe_path": path,
                             "corpora": corpus, "generation": generation}
    if args.dry_run:
        print("DRY RUN completed: no Docker, reference, or candidate executions.")
        return

    base.ensure_docker()
    all_reports, summary = [], {}
    for task in tasks:
        experiment = experiments[task]
        corpus = experiment["corpora"]
        reference, entry = base.load_reference(task)
        expected, reference_counts = checked_outputs(task, reference, entry, corpus, args.batch_size)
        # Verify each synthetic mutant is genuinely non-equivalent using its own
        # manually constructed witness, distinct from the scoring corpus.
        witness_list = [row[2] for row in MUTANTS[task]]
        reference_witnesses = execute(reference, entry, witness_list, args.batch_size)
        for (name, description, witness, source), reference_out in zip(MUTANTS[task], reference_witnesses):
            if not valid(task, witness) or reference_out.get("status") != "ok":
                raise RuntimeError(f"Invalid reference witness for {task}/{name}")
            parsed = ast.parse(source)
            functions = {node.name for node in parsed.body if isinstance(node, ast.FunctionDef)}
            if entry not in functions:
                raise RuntimeError(f"Mutant {name} has no {entry}")
            mutant_witness = execute(source, entry, [witness], args.batch_size)[0]
            if reference_matches(mutant_witness, reference_out):
                raise RuntimeError(f"Mutant {name} is not distinguished by its declared witness")
        print(f"{task}: reference & 5 mutant witnesses verified")
        for name, description, witness, source in MUTANTS[task]:
            method_reports = {}
            for method in ("property", "mutation", "differential", "metamorphic"):
                method_reports[method] = evaluate_method(
                    method, source, experiment["probe"], entry, corpus,
                    expected, args.batch_size)
                ledger = method_reports[method]
                if not ledger["budget_ledger_matches"] or ledger["candidate_executions"] != args.budget:
                    raise RuntimeError(f"Execution-budget accounting failed: {task}/{name}/{method}")
                if ledger["reference_oracle_executions"] != reference_counts[method]:
                    raise RuntimeError(f"Shared-oracle accounting failed: {task}/{name}/{method}")
            row = {"task_id": task, "mutant_id": name, "description": description,
                   "synthetic_diagnostic": True, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                   "witness_sha256": sha(witness), "methods": method_reports}
            all_reports.append(row)
            print(" ", task, name, "|", " ".join(f"{m}:{'DETECT' if r['detected'] else '-'}"
                                                    for m, r in method_reports.items()))
        summary[task] = {"probe_candidate": experiment["probe_path"],
                         "generation": experiment["generation"],
                         "shared_reference_calls_per_method": reference_counts,
                         "witness_reference_calls": len(witness_list),
                         "corpus_sha256": {m: sha(corpus[m]) for m in
                                           ("property", "mutation", "differential", "metamorphic")}}

    totals = {}
    for method in ("property", "mutation", "differential", "metamorphic"):
        selected = [r["methods"][method] for r in all_reports]
        totals[method] = {
            "synthetic_mutants_detected": sum(r["detected"] for r in selected),
            "total_mutants": len(selected),
            "verified_signals": sum(r["verified_signal_count"] for r in selected),
            "candidate_executions": sum(r["candidate_executions"] for r in selected),
            "candidate_wall_seconds": round(sum(r["wall_seconds"] for r in selected), 3),
            "median_first_failure_cost_excluding_undetected": (
                statistics.median([r["first_verified_failure_at_candidate_executions"]
                                   for r in selected
                                   if r["first_verified_failure_at_candidate_executions"] is not None])
                if any(r["detected"] for r in selected) else None),
        }
    output = ROOT / "results/phase2b"
    output.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    dest = output / f"fault_benchmark_{tag}_report.json"
    corpora_file = output / f"fault_benchmark_{tag}_inputs.json"
    saved_corpora = {
        task: {
            "probe_candidate": experiments[task]["probe_path"],
            "methods": {
                method: experiments[task]["corpora"][method]
                for method in ("property", "mutation", "differential", "metamorphic")
            },
            "metamorphic_pairs": experiments[task]["corpora"]["pairs"],
        } for task in tasks
    }
    corpora_file.write_text(json.dumps({
        "suite": "synthetic_fault_detection_development_fairness_v1", "seed": args.seed,
        "candidate_execution_budget": args.budget, "tasks": saved_corpora,
    }, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    dest.write_text(json.dumps({
        "suite": "synthetic_fault_detection_development_fairness_v1", "official_or_held_out": False,
        "protocol_version": "phase2b_fairness_v1",
        "hypothesis_version": hypothesis.__version__,
        "property_generator": "phase2d.strategies.property_inputs (explicit seed)",
        "fairness_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "phase2d_strategies_sha256": hashlib.sha256((ROOT / "phase2d" / "strategies.py").read_bytes()).hexdigest(),
        "historical_phase2b5_sha256": hashlib.sha256((ROOT / "phase2b5_fault_benchmark.py").read_bytes()).hexdigest(),
        "seed_independence_caveat": "Reproducible distinct seeds do not guarantee statistical independence of resulting observations.",
        "budget_definition": "B total target+probe sandbox calls per mutant per method; oracle/setup excluded",
        "cost_limits": "Target candidate counts differ across methods; oracle and generation costs are not matched; first-hit index is posthoc.",
        "seed": args.seed, "candidate_executions_per_mutant_per_method": args.budget,
        "reference_oracle_calls": "shared by method/task, separately recorded; not matched across strategies",
        "warning": "Different input-generation priors and method semantics prohibit causal method-ranking claims.",
        "docker_image": base.IMAGE, "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_corpus_file": str(corpora_file.relative_to(ROOT)),
        "input_corpus_sha256": hashlib.sha256(corpora_file.read_bytes()).hexdigest(),
        "tasks": summary, "totals": totals, "mutants": all_reports,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nDetection summary (distinct synthetic mutants, not distinct real-world bugs):")
    for name, data in totals.items():
        print(f"  {name:13s} {data['synthetic_mutants_detected']}/{data['total_mutants']} "
              f"| {data['candidate_executions']} candidate executions")
    print("Saved input corpus:", corpora_file.relative_to(ROOT))
    print("Saved report:", dest.relative_to(ROOT))
    print("Development evidence only. Never report this as real Gemini accuracy or held-out performance.")


if __name__ == "__main__":
    main()
