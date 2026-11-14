#!/usr/bin/env python3
"""Reproducible, read-only-by-default STRATIFIED LEXICAL OVERLAP REVIEW.

This samples from *all* cross-partition pairs returned by the same sparse
retrieval as phase2d_global_overlap_audit.py (not its truncated top-200 CSV).
No models, Docker, private tests, candidate execution, network or split edits.

Usage:
  python phase2d_stratified_overlap_sampling.py --self-test
  python phase2d_stratified_overlap_sampling.py --seed 2026 --per-stratum 3
  python phase2d_stratified_overlap_sampling.py --seed 2026 --per-stratum 3 \\
    --export-dir results/phase2d/global_overlap_stratified_v1
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import random
import sys

from phase2d_global_overlap_audit import (
    get_exact_groups, load_and_verify, lexical_pairs, pair_info,
    sha256_file,
)

REPORT_REL = Path('results/phase2d/global_overlap_audit_v1/global_overlap_report.json')
REVIEW_RELS = (
    Path('results/phase2d/global_overlap_audit_v1/manual_review.json'),
    Path('results/phase2d/global_overlap_audit_v1/manual_review_batch2.json'),
)
EXPECTED_MANIFEST_STATUS = 'draft_requires_review_and_freeze'
SCORE_BOUNDS = (0.12, 0.20, 0.35, 0.50, 0.65)
OUTPUT_NAMES = (
    'stratified_overlap_summary.json',
    'priority_manual_review.csv',
    'random_stratified_review.csv',
    'stratum_inventory.csv',
)


def pair_key(a: str, b: str) -> tuple[str, str]:
    if not isinstance(a, str) or not isinstance(b, str) or a == b:
        raise ValueError('Invalid reviewed task pair')
    return tuple(sorted((a, b)))


def score_band(score: float, priority_threshold: float = 0.65) -> str:
    if score >= priority_threshold:
        return f'priority_ge_{priority_threshold:g}'
    bounds = (0.12, 0.20, 0.35, 0.50, priority_threshold)
    for lower, upper in zip(bounds, bounds[1:]):
        if lower <= score < upper:
            return f'[{lower:.2f},{upper:.2f})'
    raise ValueError(f'Score outside supported audit range: {score}')


def stratum_key(row: dict, priority_threshold: float = 0.65) -> tuple[str, str, str]:
    dp = ' / '.join(sorted((row['dataset_a'], row['dataset_b'])))
    pp = ' / '.join(sorted((row['partition_a'], row['partition_b'])))
    band = score_band(float(row['lexical_weighted_jaccard']), priority_threshold)
    return dp, pp, band


def load_json_object(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f'Missing input file: {path}')
    with path.open(encoding='utf-8') as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError(f'Invalid JSON object: {path}')
    return value


def verify_evidence(root: Path, hashes: dict, manifest: dict, tasks: list) -> tuple[dict, set, dict]:
    if manifest.get('status') != EXPECTED_MANIFEST_STATUS:
        raise ValueError('Manifest changed from draft; refusing the sample')
    report_path = root / REPORT_REL
    report = load_json_object(report_path)
    if (report.get('report_type') != 'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION'
            or report.get('input_sha256') != hashes
            or report.get('all_public_task_count') != len(tasks)):
        raise ValueError('Global audit stale, mismatched or unexpected')
    if get_exact_groups(tasks) != report.get('exact_normalized_prompt_groups'):
        raise ValueError('Exact-group evidence differs from global audit')
    report_sha = sha256_file(report_path)
    reviewed = set()
    review_shas = {}
    lookup = {t.task_id: t for t in tasks}
    for rel, required_count in zip(REVIEW_RELS, (6, 8)):
        path = root / rel
        doc = load_json_object(path)
        if (doc.get('manifest_status_at_review') != EXPECTED_MANIFEST_STATUS
                or doc.get('input_sha256') != hashes
                or doc.get('lexical_report_sha256') != report_sha
                or doc.get('execution_authorized') is not False
                or doc.get('final_split_freeze_authorized') is not False
                or doc.get('reviewed_pair_count') != required_count
                or not isinstance(doc.get('pairs'), list)
                or len(doc['pairs']) != required_count):
            raise ValueError(f'Stale or unexpected manual review: {rel}')
        for item in doc['pairs']:
            key = pair_key(item['task_a'], item['task_b'])
            if key in reviewed:
                raise ValueError(f'Duplicate manual review: {key}')
            left, right = (lookup.get(key[0]), lookup.get(key[1]))
            if left is None or right is None or left.partition == right.partition:
                raise ValueError(f'Invalid cross-partition review task pair: {key}')
            for suffix in ('a', 'b'):
                tid = item[f'task_{suffix}']
                if lookup[tid].partition != item[f'partition_{suffix}']:
                    raise ValueError(f'Manual review partition mismatch: {tid}')
                documented_hash = item.get(f'normalized_prompt_sha256_{suffix}')
                if documented_hash is not None and lookup[tid].normalized_hash != documented_hash:
                    raise ValueError(f'Manual review prompt hash mismatch: {tid}')
            reviewed.add(key)
        review_shas[str(rel)] = sha256_file(path)
    return report, reviewed, review_shas


def split_priority_and_sample(rows: list[dict], reviewed: set[tuple[str, str]], *,
                              seed: int = 2026, per_stratum: int = 3,
                              priority_threshold: float = 0.65):
    """Priority census plus independent fixed-seed samples from remaining strata.

    Sampling fractions describe ONLY the lexically retrieved, above-threshold
    cross-partition candidate population, excluding previously reviewed and
    priority-census pairs; they are NOT whole-corpus leakage probabilities.
    """
    if per_stratum < 1 or not 0.60 <= priority_threshold <= 0.65:
        raise ValueError('Require --per-stratum >= 1 and priority threshold 0.60..0.65')
    priorities = []
    strata = defaultdict(list)
    keys_seen = set()
    for row in rows:
        key = pair_key(row['task_a'], row['task_b'])
        if key in keys_seen:
            raise ValueError(f'Repeated lexical pair: {key}')
        keys_seen.add(key)
        if key in reviewed:
            continue
        if row['partition_a'] == row['partition_b']:
            raise ValueError('Expected cross-partition only')
        if float(row['lexical_weighted_jaccard']) >= priority_threshold:
            priorities.append(row)
        else:
            strata[stratum_key(row, priority_threshold)].append(row)

    priorities.sort(key=lambda r: (-float(r['lexical_weighted_jaccard']),
                                   pair_key(r['task_a'], r['task_b'])))
    sampled = []
    inventory = []
    for key in sorted(strata):
        pool = sorted(strata[key], key=lambda r: pair_key(r['task_a'], r['task_b']))
        n = min(per_stratum, len(pool))
        stratum_label = ' | '.join(key)
        seed_bytes = hashlib.sha256(f'{seed}|{stratum_label}'.encode('utf-8')).digest()
        local_seed = int.from_bytes(seed_bytes, 'big')
        chosen = sorted(random.Random(local_seed).sample(range(len(pool)), n))
        inventory.append({'dataset_pair': key[0], 'partition_pair': key[1],
                          'score_band': key[2], 'population_N': len(pool),
                          'sample_n': n, 'sampling_fraction': round(n / len(pool), 9),
                          'seed': seed})
        for index in chosen:
            new_row = dict(pool[index])
            new_row.update({'dataset_pair': key[0], 'partition_pair': key[1],
                            'score_band': key[2], 'stratum_population_N': len(pool),
                            'stratum_sample_n': n,
                            'inclusion_probability': round(n / len(pool), 9),
                            'selection_mode': 'fixed_seed_random_stratum'})
            sampled.append(new_row)
    return priorities, sampled, inventory


def build(root: Path, *, seed: int, per_stratum: int,
          priority_threshold: float):
    root = root.resolve()
    tasks, manifest, hashes = load_and_verify(root)
    report, reviewed, review_shas = verify_evidence(root, hashes, manifest, tasks)
    settings = report.get('settings') or {}
    if settings.get('min_lexical_score') != 0.12:
        raise ValueError('This sampler requires the pre-reviewed 0.12 lexical threshold')
    ranked, stats, idf = lexical_pairs(
        tasks,
        max_df=int(settings['max_document_frequency']),
        min_score=float(settings['min_lexical_score']),
    )
    if stats['candidate_pair_count'] != report['screening']['candidate_pair_count']:
        raise ValueError('Recomputed candidate count differs from original audit')
    rows = [pair_info(score, tasks[i], tasks[j], idf)
            for score, i, j in ranked
            if tasks[i].partition != tasks[j].partition]
    if len(rows) != report['screening']['cross_partition_pairs_above_threshold']:
        raise ValueError('Recomputed cross-partition count differs from original audit')
    row_keys = {pair_key(r['task_a'], r['task_b']) for r in rows}
    if not reviewed.issubset(row_keys):
        raise ValueError('Reviewed pair missing from lexical candidate population')
    priorities, samples, inventory = split_priority_and_sample(
        rows, reviewed, seed=seed, per_stratum=per_stratum,
        priority_threshold=priority_threshold,
    )
    task_map = {t.task_id: t for t in tasks}

    def expand(r: dict, *, selection_mode: str) -> dict:
        out = dict(r)
        out['selection_mode'] = selection_mode
        out['prompt_a'] = task_map[r['task_a']].prompt
        out['prompt_b'] = task_map[r['task_b']].prompt
        out['manual_verdict'] = ''
        out['review_notes'] = ''
        return out

    priority_expanded = [expand(r, selection_mode='priority_full_census') for r in priorities]
    sample_expanded = [expand(r, selection_mode='fixed_seed_random_stratum') for r in samples]
    audit_path = root / 'phase2d_global_overlap_audit.py'
    summary = {
        'schema_version': 1,
        'report_type': 'PUBLIC_STRATIFIED_LEXICAL_REVIEW_QUEUE_NOT_DUPLICATE_VERDICTS',
        'manifest_status': manifest['status'],
        'input_sha256': hashes,
        'original_report_sha256': sha256_file(root / REPORT_REL),
        'manual_review_sha256': review_shas,
        'audit_script_sha256': sha256_file(audit_path) if audit_path.exists() else None,
        'seed': seed,
        'per_stratum': per_stratum,
        'priority_threshold': priority_threshold,
        'cross_partition_lexical_leads_above_threshold': len(rows),
        'already_manually_reviewed': len(reviewed),
        'remaining_above_threshold': len(rows) - len(reviewed),
        'priority_census_count': len(priority_expanded),
        'stratified_sampling_pool_count': sum(x['population_N'] for x in inventory),
        'stratified_sample_count': len(sample_expanded),
        'nonempty_sampling_strata': len(inventory),
        'dataset_pairs_in_sample': dict(sorted(Counter(
            r['dataset_pair'] for r in samples).items())),
        'limitations': [
            'No semantic duplicate verdicts are generated; all rows require manual review.',
            'The retrieved candidate population excludes low-score pairs and pairs with no shared eligible lexical features.',
            'Sample inclusion fractions apply only within each listed nonpriority candidate stratum.',
            'A full census of score >= threshold leads is listed separately; it may be large.',
            'No task partitions are changed; held_out_temporal_pending remains unapproved.',
            'Do not infer whole-corpus or model-training contamination rates from these queues.',
        ],
    }
    return summary, priority_expanded, sample_expanded, inventory


def export_files(directory: Path, summary: dict, priority: list, samples: list, inventory: list):
    if directory.exists() and not directory.is_dir():
        raise ValueError('Output location is not a directory')
    out_paths = [directory / n for n in OUTPUT_NAMES]
    if any(p.exists() for p in out_paths):
        raise ValueError('Refusing to overwrite existing stratified audit files')
    directory.mkdir(parents=True, exist_ok=True)
    with out_paths[0].open('x', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write('\n')
    for path, rows in [(out_paths[1], priority), (out_paths[2], samples),
                       (out_paths[3], inventory)]:
        with path.open('x', newline='', encoding='utf-8') as f:
            fieldnames = list(rows[0].keys()) if rows else (
                ['task_a', 'task_b', 'manual_verdict', 'review_notes']
                if path != out_paths[3] else
                ['dataset_pair', 'partition_pair', 'score_band',
                 'population_N', 'sample_n', 'sampling_fraction', 'seed']
            )
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                # Prevent cells starting with =, +, -, @ from being interpreted
                # as formulas if researchers open the public-prompt CSV in Excel.
                safe = {k: ("'" + v if isinstance(v, str) and
                             v.lstrip().startswith(('=', '+', '-', '@')) else v)
                        for k, v in row.items()}
                writer.writerow(safe)
    return out_paths


def self_test():
    assert pair_key('z', 'a') == ('a', 'z')
    assert score_band(0.65) == 'priority_ge_0.65'
    assert score_band(0.12) == '[0.12,0.20)'
    assert score_band(0.3499) == '[0.20,0.35)'
    rows = [
        {'task_a': 'a', 'task_b': 'b', 'dataset_a': 'mbpp',
         'dataset_b': 'mbpp', 'partition_a': 'development',
         'partition_b': 'held_out', 'lexical_weighted_jaccard': 0.9},
        {'task_a': 'a', 'task_b': 'c', 'dataset_a': 'mbpp',
         'dataset_b': 'mbpp', 'partition_a': 'development',
         'partition_b': 'held_out', 'lexical_weighted_jaccard': 0.21},
        {'task_a': 'a', 'task_b': 'd', 'dataset_a': 'mbpp',
         'dataset_b': 'mbpp', 'partition_a': 'development',
         'partition_b': 'held_out', 'lexical_weighted_jaccard': 0.22},
        {'task_a': 'a', 'task_b': 'e', 'dataset_a': 'mbpp',
         'dataset_b': 'mbpp', 'partition_a': 'development',
         'partition_b': 'held_out', 'lexical_weighted_jaccard': 0.23},
    ]
    result = split_priority_and_sample(rows, {pair_key('a','c')}, seed=7,
                                       per_stratum=1)
    assert len(result[0]) == 1 and len(result[1]) == 1
    assert result[2][0]['population_N'] == 2
    assert result == split_priority_and_sample(rows, {pair_key('a','c')}, seed=7,
                                               per_stratum=1)
    print('SELF-TEST PASS: canonical pairs, score bands, fixed-seed stratified sampling, reviewed exclusions')
    print('No project data read or written.')


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--seed', type=int, default=2026)
    ap.add_argument('--per-stratum', type=int, default=3)
    ap.add_argument('--priority-threshold', type=float, default=0.65)
    ap.add_argument('--export-dir', type=Path,
                    help='OPTIONAL: creates new files only; default is strictly read-only')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    try:
        summary, priorities, samples, inventory = build(
            args.root, seed=args.seed, per_stratum=args.per_stratum,
            priority_threshold=args.priority_threshold)
        print('STRATIFIED PUBLIC LEXICAL REVIEW — NO DUPLICATE VERDICTS')
        for k in ('manifest_status', 'cross_partition_lexical_leads_above_threshold',
                  'already_manually_reviewed', 'remaining_above_threshold',
                  'priority_census_count', 'stratified_sampling_pool_count',
                  'stratified_sample_count', 'nonempty_sampling_strata'):
            print(k.upper() + ':', summary[k])
        print('STRATIFIED DATASET PAIRS:', summary['dataset_pairs_in_sample'])
        print('\nTOP PRIORITY UNREVIEWED LEADS:')
        for row in priorities[:12]:
            print(row['task_a'], '<->', row['task_b'],
                  'score=', row['lexical_weighted_jaccard'])
        print('\nFIRST 12 FIXED-SEED SAMPLE LEADS:')
        for row in samples[:12]:
            print(row['task_a'], '<->', row['task_b'],
                  'stratum=', row['dataset_pair'], '|', row['partition_pair'], '|', row['score_band'])
        print('\nNo candidate execution, model calls, private tests, Docker, network or split changes.')
        if args.export_dir:
            for path in export_files(args.export_dir, summary, priorities, samples, inventory):
                print('CREATED:', path)
        else:
            print('READ-ONLY: no files created (use --export-dir to save review queues).')
    except (OSError, ValueError, KeyError) as err:
        print(f'SAMPLER FAILED CLOSED: {err}', file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    main()
