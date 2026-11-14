#!/usr/bin/env python3
"""Read-only verification of the proposed 81-pair Batch 4 public-prompt review.

This verifies the review matches the local sampled review CSV exactly on IDs,
partitions, score, stratum and full public prompt hashes. Never executes tasks,
never accesses hidden tests, and never writes the source/manifest.
"""
import argparse
import collections
import csv
import hashlib
import json
import sys
from pathlib import Path


def verify(source, record, strict_file_hash=False):
    with Path(source).open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    doc = json.loads(Path(record).read_text(encoding='utf-8'))
    if doc.get('record_type') != 'PROVISIONAL_STRATIFIED_PUBLIC_PROMPT_REVIEW_NOT_SPLIT_APPROVAL':
        raise ValueError('Unexpected or non-provisional record type')
    reviews = doc.get('reviews', [])
    if len(rows) != len(reviews) or len(rows) != 81:
        raise ValueError(f'Expected 81 rows with 81 reviews; got {len(rows)} and {len(reviews)}')
    if strict_file_hash and hashlib.sha256(Path(source).read_bytes()).hexdigest() != doc['source_file_sha256']:
        raise ValueError('Source file bytes do not match uploaded snapshot')
    if len({tuple(sorted((r['task_a'],r['task_b']))) for r in rows}) != len(rows):
        raise ValueError('Duplicate task pair detected')
    expected_fields = (
        'task_a', 'task_b', 'dataset_a', 'dataset_b',
        'partition_a', 'partition_b', 'lexical_weighted_jaccard',
        'char_5gram_jaccard', 'dataset_pair', 'partition_pair',
        'score_band', 'stratum_population_N', 'stratum_sample_n',
        'inclusion_probability', 'selection_mode'
    )
    verdicts = collections.Counter()
    for i, (row, review) in enumerate(zip(rows,reviews),1):
        if str(i) != review['review_index']:
            raise ValueError(f'Reordered review at row {i}')
        for k in expected_fields:
            if row[k] != review[k]:
                raise ValueError(f'Row {i} changed: {k}')
        for s, tag in (('prompt_a','source_prompt_a_sha256'), ('prompt_b','source_prompt_b_sha256')):
            digest = hashlib.sha256(row[s].encode('utf-8')).hexdigest()
            if digest != review[tag]:
                raise ValueError(f'Row {i} prompt changed: {s}')
        if not review.get('review_notes') or review.get('manual_verdict') not in doc['verdict_definitions']:
            raise ValueError(f'Row {i} missing a valid verdict/rationale')
        verdicts[review['manual_verdict']] += 1
    if dict(verdicts) != doc['verdict_counts']:
        raise ValueError('Review summary verdict counts do not agree with row verdicts')
    strata = collections.Counter((r['dataset_pair'],r['partition_pair'],r['score_band']) for r in rows)
    if len(strata) != doc['num_strata']:
        raise ValueError('Stratum count mismatch')
    for r in rows:
        k = (r['dataset_pair'],r['partition_pair'],r['score_band'])
        if strata[k] != int(r['stratum_sample_n']):
            raise ValueError(f'Stratum sample size mismatch: {k}')
    return {'pairs':len(rows),'strata':len(strata),'verdicts':dict(verdicts)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',default='results/phase2d/global_overlap_stratified_v1/random_stratified_review.csv')
    p.add_argument('--review',default='results/phase2d/global_overlap_stratified_v1/manual_review_batch4_provisional.json')
    p.add_argument('--strict-file-hash',action='store_true',help='Require byte-for-byte uploaded source snapshot; otherwise validates full prompt hashes and metadata')
    a=p.parse_args()
    try:
        result=verify(a.source,a.review,a.strict_file_hash)
    except (OSError,ValueError,KeyError,TypeError) as e:
        print(f'BATCH4 REVIEW VERIFICATION FAILED: {e}',file=sys.stderr)
        sys.exit(1)
    print('BATCH4 REVIEW VERIFICATION PASSED -- READ-ONLY')
    print('PAIRS:',result['pairs'])
    print('STRATA:',result['strata'])
    print('VERDICTS:',result['verdicts'])
    print('REVIEW STATUS: PROVISIONAL. No approval, quarantine, or manifest changes.')

if __name__ == '__main__':
    main()
