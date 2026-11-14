#!/usr/bin/env python3
"""Read-only-by-default independent review of BigCodeBench/854 pilot suite.

Never imports or runs generated candidate code, accesses private data, or makes
network/model/Docker calls. An explicit --approve action writes reviewed files,
leaving the split manifest and proposal unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

TASK = 'BigCodeBench/854'
EXPECTED_NAMES = {
    'empty', 'singleton_zero', 'singleton_four', 'two_distinct',
    'two_repeated', 'three_distinct', 'three_with_repeats',
    'four_distinct', 'four_with_repeats', 'non_list_string',
    'non_list_integer', 'noninteger_string', 'noninteger_float',
    'noninteger_none', 'negative_single', 'negative_mixed',
}
REPEATED = {'two_repeated', 'three_with_repeats', 'four_with_repeats'}
POLICIES = {
    'domain': 'JSON-transportable inputs; lists of 0..4 nonnegative exact Python ints, with bounded small test values',
    'empty': 'two empty lists, even though the mathematical empty permutation would otherwise exist',
    'duplicates': 'position-based permutations; repeated values retain multiplicity as itertools.permutations would',
    'permutation_order': 'ignored; matching uses multiset of (factorial sum, permutation) pairs',
    'semantic_representation': 'list or tuple permutation rows accepted after trusted JSON serialization',
    'strict_representation': 'tuple root and tuple permutation rows recorded separately; exploratory, not official scoring',
    'exceptions': 'TypeError for non-list/non-int input, ValueError for negative ints',
    'boolean_inputs': 'excluded: whether bool counts as int is unresolved',
    'tuple_inputs': 'excluded: JSON transport does not preserve tuple input types',
    'mixed_invalid_inputs': 'excluded: TypeError vs ValueError precedence ambiguous',
    'scope': 'independently reviewed *development* suite; not official BigCodeBench grading',
}


def factorial_by_loop(n: int) -> int:
    result = 1
    for k in range(2, n + 1):
        result *= k
    return result


def independently_expected(value):
    """Use unique-value Cartesian enumeration + positional multiplicity.

    Deliberately differs from the adapter's direct itertools.permutations
    implementation, while using only tiny bounded public development inputs.
    """
    if type(value) is not list or any(type(x) is not int for x in value):
        return {'status': 'exception', 'error_type': 'TypeError'}
    if any(x < 0 for x in value):
        return {'status': 'exception', 'error_type': 'ValueError'}
    n = len(value)
    if n > 4:
        raise ValueError('review supports only n <= 4')
    if n == 0:
        return {'status': 'ok', 'pairs': Counter(), 'n': 0}
    freqs = Counter(value)
    multiplier = 1
    for count in freqs.values():
        multiplier *= factorial_by_loop(count)
    total = sum(factorial_by_loop(x) for x in value)
    pairs = Counter()
    # Cartesian enumeration of unique values (not itertools.permutations)
    for tup in product(sorted(freqs), repeat=n):
        if Counter(tup) == freqs:
            pairs[(total, tup)] = multiplier
    return {'status': 'ok', 'pairs': pairs, 'n': factorial_by_loop(n)}


def audit(proposal_path: Path) -> dict:
    raw_bytes = proposal_path.read_bytes()
    p = json.loads(raw_bytes)
    if p.get('task_id') != TASK:
        raise ValueError('Wrong task_id')
    if p.get('provenance') != 'proposed_unreviewed_development' or p.get('approval') != 'NOT_APPROVED':
        raise ValueError('Expected original unapproved development proposal')
    cases = p.get('cases')
    if not isinstance(cases, list) or len(cases) != 16:
        raise ValueError('Expected exactly 16 proposed cases')
    names = [c.get('name') for c in cases if isinstance(c, dict)]
    if len(names) != len(cases) or len(set(names)) != 16 or set(names) != EXPECTED_NAMES:
        raise ValueError('Missing, extra, or duplicate case names')
    outcomes = []
    for row in cases:
        name = row['name']
        if not isinstance(row.get('args'), list) or len(row['args']) != 1:
            raise ValueError(f'{name}: expected exactly one argument')
        input_value = row['args'][0]
        expected = independently_expected(input_value)
        observed = row['expected']
        if expected['status'] != observed.get('status'):
            raise ValueError(f'{name}: wrong outcome status')
        if expected['status'] == 'exception':
            if observed != {'status': 'exception', 'error_type': expected['error_type']}:
                raise ValueError(f'{name}: wrong exception type')
        else:
            if set(observed) != {'status', 'value'}:
                raise ValueError(f'{name}: wrong expected outcome fields')
            value = observed['value']
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError(f'{name}: malformed return value')
            sums, perms = value
            if not isinstance(sums, list) or not isinstance(perms, list):
                raise ValueError(f'{name}: malformed output lists')
            if not all(type(s) is int for s in sums):
                raise ValueError(f'{name}: sums must be integer')
            if not all(isinstance(r, list) and all(type(x) is int for x in r) for r in perms):
                raise ValueError(f'{name}: permutation rows must be integer lists in JSON')
            if len(sums) != len(perms) or len(sums) != expected['n']:
                raise ValueError(f'{name}: wrong number of permutations')
            actual_pairs = Counter((s, tuple(r)) for s, r in zip(sums, perms))
            if actual_pairs != expected['pairs']:
                raise ValueError(f'{name}: incorrect factorial/permutation multiset')
        outcomes.append({'name': name, 'result': 'independently_verified', 'kind': expected['status']})
    counts = Counter(o['kind'] for o in outcomes)
    return {
        'schema_version': 'bcb854-review.1',
        'task_id': TASK,
        'proposal_sha256': sha256(raw_bytes).hexdigest(),
        'review_method': 'independent combinatorial multiplicity oracle; fixed exception-policy checks',
        'case_count': len(outcomes),
        'valid_cases': counts.get('ok', 0),
        'invalid_cases': counts.get('exception', 0),
        'cases': outcomes,
        'policies': POLICIES,
        'status': 'independent_checks_passed_pending_local_approval',
        'manifest_status': 'not_modified',
        'candidate_execution': False,
        'private_tests_accessed': False,
        'official_evaluation': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposal', type=Path, default=Path('proposals/bcb854_review.json'))
    parser.add_argument('--reviewed', type=Path,
                        default=Path('data/development/bigcodebench/BigCodeBench_854.json'))
    parser.add_argument('--record', type=Path,
                        default=Path('results/phase2d/reviews/BigCodeBench_854_review.json'))
    parser.add_argument('--approve', action='store_true',
                        help='Explicitly accept disclosed policies and create reviewed suite; DOES NOT enable evaluation')
    args = parser.parse_args()
    outcome = audit(args.proposal)
    print('Task:', TASK)
    print('Proposal SHA256:', outcome['proposal_sha256'])
    print('Cases verified:', outcome['case_count'])
    print('Valid / invalid:', outcome['valid_cases'], '/', outcome['invalid_cases'])
    print('Repeated-value policy cases:', ', '.join(sorted(REPEATED)))
    print('Unresolved interpretation policies: tuple/list strictness, bool inputs, and mixed-error precedence')
    print('No candidate execution; no network; no private tests; manifest unchanged.')
    if not args.approve:
        print('READ ONLY. To approve this bounded suite locally, run with --approve after reviewing the policies.')
        return
    if args.reviewed.exists() or args.record.exists():
        raise SystemExit('Refusing to overwrite existing reviewed suite or record.')
    original = json.loads(args.proposal.read_text(encoding='utf-8'))
    original['provenance'] = 'independently_reviewed_development'
    original['approval'] = 'APPROVED_FOR_BOUNDED_DEVELOPMENT_ONLY'
    original['review_policy'] = POLICIES
    original['source_proposal_sha256'] = outcome['proposal_sha256']
    original['reviewed_utc'] = datetime.now(timezone.utc).isoformat()
    original['official_evaluation'] = False
    outcome['status'] = 'approved_for_bounded_development_by_local_operator'
    outcome['reviewed_utc'] = original['reviewed_utc']
    args.reviewed.parent.mkdir(parents=True, exist_ok=True)
    args.record.parent.mkdir(parents=True, exist_ok=True)
    with args.reviewed.open('x', encoding='utf-8') as f:
        json.dump(original, f, indent=2, ensure_ascii=False)
        f.write('\n')
    with args.record.open('x', encoding='utf-8') as f:
        json.dump(outcome, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print('Reviewed development suite:', args.reviewed)
    print('Independent review record:', args.record)
    print('SPLIT MANIFEST UNCHANGED. Execution remains blocked while manifest is draft.')


if __name__ == '__main__':
    main()
