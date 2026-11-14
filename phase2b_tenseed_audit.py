#!/usr/bin/env python3
"""Fail-closed read-only verifier and optional ZIP packager of the fixed 2026..2035
Phase 2B Fairness V1 synthetic benchmark. No code, Docker, or oracle execution.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path('results/phase2b')
SUITE = 'synthetic_fault_detection_development_fairness_v1'
BUDGET = 40
METHODS = ('property', 'mutation', 'differential', 'metamorphic')
TASK_MUTANTS = {
    'HumanEval/0': {'boundary_le', 'first_two_only', 'no_duplicates', 'ignore_negatives', 'adjacent_only'},
    'HumanEval/1': {'retain_spaces', 'merge_groups', 'reverse_groups', 'flatten_nesting', 'omit_last'},
}
SOURCE_HASHES = {
    'fairness_script_sha256': 'e3af520339a6c1fbd0fd9ac8e845e5d68b7bc7a416c5b6a039188a34a544368c',
    'phase2d_strategies_sha256': '454d3462d52d9f833ec8caa36a6891036dd3e44b0de2b318a5a87758de48bcb0',
    'historical_phase2b5_sha256': '951bf1b9b898a81bf5f1ca18918a0a60155fcdacf0bb46b66075c441532a5aca',
}
# Explicit filenames from the reviewed console logs; no globbing or ambiguous run selection.
EXPECTED_REPORTS = (
    (2026, ('HumanEval/0',), 'fault_benchmark_20261114T023651Z_b8f468_report.json'),
    (2026, ('HumanEval/1',), 'fault_benchmark_20261114T024254Z_279f71_report.json'),
    (2027, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T025121Z_d9f850_report.json'),
    (2028, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T025723Z_7257b6_report.json'),
    (2029, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T030211Z_1a529d_report.json'),
    (2030, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T030650Z_55468c_report.json'),
    (2031, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T031159Z_1dcf50_report.json'),
    (2032, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T031644Z_58d73f_report.json'),
    (2033, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T032124Z_cb3849_report.json'),
    (2034, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T032604Z_b2e9c9_report.json'),
    (2035, ('HumanEval/0', 'HumanEval/1'), 'fault_benchmark_20261114T033042Z_e8b39b_report.json'),
)


def check(ok, reason):
    if not ok:
        raise ValueError('INTEGRITY CHECK FAILED: ' + reason)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_path(root, rel):
    check(isinstance(rel, str) and rel.startswith('results/phase2b/'), f'invalid path: {rel!r}')
    p = root / rel
    check(p.resolve().is_relative_to((root / DATA_DIR).resolve()), f'path escape: {rel}')
    check(p.is_file() and not p.is_symlink(), f'missing or symlink: {rel}')
    return p


def as_json(p):
    return json.loads(p.read_text(encoding='utf-8'), parse_constant=lambda s: (_ for _ in ()).throw(ValueError('Non-finite JSON constant ' + s)))


def audit(root):
    check(len(EXPECTED_REPORTS) == 11, 'expected 11 pinned report files')
    hits = defaultdict(Counter)
    per_seed = defaultdict(lambda: Counter())
    task_seed_coverage = set()
    files = {}
    entries = []
    for seed, tasks, basename in EXPECTED_REPORTS:
        report_rel = str(DATA_DIR / basename)
        report_file = checked_path(root, report_rel)
        report = as_json(report_file)
        check(report.get('suite') == SUITE, basename + ': wrong suite')
        check(report.get('protocol_version') == 'phase2b_fairness_v1', basename + ': wrong protocol')
        check(report.get('official_or_held_out') is False, basename + ': held-out flag not false')
        check(report.get('seed') == seed, basename + ': wrong seed')
        check(report.get('candidate_executions_per_mutant_per_method') == BUDGET, basename + ': wrong budget')
        check(report.get('hypothesis_version') == '6.170.15', basename + ': changed Hypothesis version')
        for key, val in SOURCE_HASHES.items():
            check(report.get(key) == val, basename + ': source hash changed for ' + key)
        check(set(report.get('tasks', {})) == set(tasks), basename + ': wrong task coverage')
        check(report.get('budget_definition', '').startswith('B total target+probe'), basename + ': budget definition changed')
        input_rel = report.get('input_corpus_file')
        corpus_file = checked_path(root, input_rel)
        corpus_bytes = corpus_file.read_bytes()
        check(sha(corpus_bytes) == report.get('input_corpus_sha256'), basename + ': corpus file hash mismatch')
        corpus = as_json(corpus_file)
        check(corpus.get('suite') == SUITE and corpus.get('seed') == seed, basename + ': corpus suite/seed mismatch')
        check(corpus.get('candidate_execution_budget') == BUDGET, basename + ': corpus budget mismatch')
        check(set(corpus.get('tasks', {})) == set(tasks), basename + ': corpus task coverage mismatch')
        rows = report.get('mutants', [])
        check(len(rows) == len(tasks) * 5, basename + ': wrong mutant count')
        report_totals = Counter()
        report_executions = Counter()
        for task in tasks:
            check((seed, task) not in task_seed_coverage, f'duplicate seed/task {seed}/{task}')
            task_seed_coverage.add((seed, task))
            tr = report['tasks'][task]
            task_corpus = corpus['tasks'][task]
            check(tr['probe_candidate'] == task_corpus['probe_candidate'], basename + ': probe mismatch')
            gen = tr['generation']['property_generator']
            check(gen['hypothesis_seed'] == seed and gen['hypothesis_derandomize'] is False, basename + ': unseeded generation')
            check(gen['selected_valid_unique_cases'] == BUDGET, basename + ': wrong property input count')
            check(tr['witness_reference_calls'] == 5, basename + ': reference witness count mismatch')
            check(tr['shared_reference_calls_per_method'] == {'property':40,'mutation':40,'differential':20,'metamorphic':40}, basename + ': reference call count mismatch')
            expected_lens = {'property':40,'mutation':40,'differential':20,'metamorphic':40}
            for method, count in expected_lens.items():
                values = task_corpus['methods'][method]
                check(len(values) == count, f'{basename}: {task}/{method} wrong corpus size')
                check(sha(canonical(values).encode('utf-8')) == tr['corpus_sha256'][method], f'{basename}: {task}/{method} input hash mismatch')
            check(len(task_corpus['metamorphic_pairs']) == 20, basename + ': metamorphic pair count mismatch')
            task_rows = [r for r in rows if r.get('task_id') == task]
            check({r.get('mutant_id') for r in task_rows} == TASK_MUTANTS[task] and len(task_rows) == 5,
                  basename + ': mutant IDs changed or repeated')
            for row in task_rows:
                mutant = row['mutant_id']
                check(row['synthetic_diagnostic'] is True, basename + ': non-synthetic mutant')
                check(set(row.get('methods', {})) == set(METHODS), basename + ': methods missing')
                for method in METHODS:
                    m = row['methods'][method]
                    expected_target = 20 if method == 'differential' else 40
                    expected_probe = 20 if method == 'differential' else 0
                    expected_reference = 20 if method == 'differential' else 40
                    check(m['candidate_executions'] == 40 and
                          m['target_candidate_executions'] == expected_target and
                          m['differential_probe_executions'] == expected_probe and
                          m['reference_oracle_executions'] == expected_reference and
                          m['budget_ledger_matches'] is True, f'{basename}: {task}/{mutant}/{method} budget mismatch')
                    check(m['first_failure_cost_is_posthoc_index'] is True, basename + ': first-hit metadata mismatch')
                    check(type(m['detected']) is bool, basename + ': detected is not boolean')
                    n = int(m['detected'])
                    hits[(task, mutant)][method] += n
                    per_seed[seed][method] += n
                    report_totals[method] += n
                    report_executions[method] += m['candidate_executions']
        for method in METHODS:
            check(report['totals'][method]['synthetic_mutants_detected'] == report_totals[method], basename + ': reported hit count mismatch')
            check(report['totals'][method]['candidate_executions'] == report_executions[method], basename + ': execution total mismatch')
            check(report['totals'][method]['total_mutants'] == len(tasks) * 5, basename + ': mutant total mismatch')
        files[report_rel] = report_file.read_bytes()
        files[input_rel] = corpus_bytes
        entries.append({'seed': seed, 'tasks': list(tasks),
                        'report': report_rel, 'report_sha256': sha(files[report_rel]),
                        'input_corpus': input_rel, 'input_corpus_sha256': sha(corpus_bytes)})
    check(task_seed_coverage == {(seed, task) for seed in range(2026,2036) for task in TASK_MUTANTS},
          'incomplete ten-seed task coverage')
    check(len(files) == 22, 'expected 11 reports and 11 distinct corpora')
    summary = {
        'purpose': 'DEVELOPMENT synthetic mutants only, NOT real LLM or held-out accuracy',
        'protocol_version': 'phase2b_fairness_v1', 'budget': BUDGET,
        'seeds': list(range(2026,2036)), 'distinct_mutants': 10,
        'repeat_observations_per_method': 100,
        'method_hits_by_seed': {str(seed): dict(per_seed[seed]) for seed in range(2026,2036)},
        'method_total_hits': {m: sum(per_seed[seed][m] for seed in range(2026,2036)) for m in METHODS},
        'per_task_mutant_detection_counts': {
            task: {mutant: dict(hits[(task,mutant)]) for mutant in sorted(mutants)}
            for task,mutants in TASK_MUTANTS.items()
        },
        'nominal_target_plus_probe_executions_per_method': 4000,
        'nominal_total_target_plus_probe_executions': 16000,
        'limitations': ['The same 10 mutants are repeated across seeds; not 100 independent programs.',
                        'Oracle executions, probe/target proportions, and generation costs differ by method.',
                        'First-hit costs are posthoc and not actual early-stopping savings.',
                        'HumanEval/1 pilot overlaps semantically with held-out HumanEval/6; do not claim independence.'],
    }
    manifest = {'schema_version': 'phase2b_ten_seed_bundle_v1', 'records': entries, 'summary': summary,
                'file_sha256': {name: sha(data) for name,data in sorted(files.items())}}
    return summary, manifest, files


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--verify-only', action='store_true', help='Read-only integrity check; no file written')
    g.add_argument('--bundle', action='store_true', help='Create a new ZIP; do not modify source files')
    args = ap.parse_args()
    try:
        summary, manifest, files = audit(ROOT)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        ap.exit(1, f'FAIL CLOSED: {exc}\n')
    print('TEN-SEED AUDIT PASSED: 2026..2035, 2 tasks, 10 synthetic mutants, 11 reports, 11 corpora')
    for m in METHODS:
        print(f'  {m:<13} {summary["method_total_hits"][m]}/100 mutant-seed detections; 4000 target+probe executions')
    if args.bundle:
        out = ROOT / DATA_DIR / 'phase2b_fairness_v1_ten_seed_evidence_bundle.zip'
        if out.exists():
            ap.exit(1, f'FAIL CLOSED: output already exists: {out}\n')
        # Write only a new evidence archive; every input file is included verbatim.
        with zipfile.ZipFile(out, 'x', compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in sorted(files.items()):
                z.writestr(name, data)
            z.writestr('evidence_manifest.json', json.dumps(manifest, indent=2, sort_keys=True).encode())
        print('EVIDENCE ZIP:', out)
        print('EVIDENCE ZIP SHA256:', sha(out.read_bytes()))
    else:
        print('READ-ONLY VERIFICATION COMPLETE: no files modified or written')


if __name__ == '__main__':
    main()
