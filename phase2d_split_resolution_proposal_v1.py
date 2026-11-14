#!/usr/bin/env python3
"""Build a review-only Phase 2D split-resolution proposal, never a policy change.

Requires the locally verified Phase 2D guard, 28-pair queue, the public-spec
packet, and the two provisional adjudication addenda. Checks exact source file
hashes, joins pair decisions by unordered task IDs, and fails closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

import phase2d_quarantine_guard as guard

ROOT = Path(__file__).resolve().parent
BASE = Path('results/phase2d')
PINS = {
    'queue': (BASE / 'expansion_review_queue_v1_1.json', 'fdb973c4ffbc3d69a288d1293b22d1fbe78619c037a0b7697ef0c3a8a9b10a60'),
    'packet': (BASE / 'public_spec_review_packet_v1.json', 'a1cc6ef313aed4437931dde692e87caec45c54bb6ea68088511e65f24e46f565'),
    'contract': (BASE / 'contract_adjudication_addendum_v1.json', 'de57ce7a9843b1891074bda1b618aeb296d7f650fe4d244a417a2b485075c319'),
    'public': (BASE / 'phase2d_public_spec_adjudication_addendum_v1.json', '4f88cadd57b13816f62725036e8f12b686ee58da8112822942a28ec7bb1b418f'),
}
OUTPUT = BASE / 'split_resolution_proposal_v1.json'


def ensure(condition, message):
    if not condition:
        raise RuntimeError(message)


def key_of(p):
    a, b = p['task_a'], p['task_b']
    ensure(isinstance(a, str) and isinstance(b, str) and a != b,
           f'Invalid task pair: {a!r} / {b!r}')
    return tuple(sorted((a, b)))


def read_pinned(label, relative, expected_hash):
    path = ROOT / relative
    if label == 'public' and not path.is_file():
        alternate = ROOT / relative.name
        if alternate.is_file():
            path = alternate
    ensure(path.is_file(), f'Missing {label}: {path}')
    raw = path.read_bytes()
    actual = sha256(raw).hexdigest()
    ensure(actual == expected_hash,
           f'Hash mismatch for {label}: expected {expected_hash}, found {actual}')
    data = json.loads(raw)
    ensure(isinstance(data, dict), f'{label} must be a JSON object')
    return data, {'path': str(path.relative_to(ROOT)), 'sha256': actual}


def build():
    manifest, quarantine = guard.load_verified_policy(ROOT)
    tasks = manifest.get('tasks')
    ensure(manifest.get('status') == 'draft_requires_review_and_freeze',
           'This proposal only supports the verified draft manifest')
    ensure(isinstance(tasks, dict) and len(tasks) == 3333,
           'Task census changed; manual protocol review required')
    ensure(len(quarantine) == 21,
           'Quarantine census changed; manual protocol review required')

    docs, provenance = {}, {}
    for label, (relative, expected) in PINS.items():
        docs[label], provenance[label] = read_pinned(label, relative, expected)

    queue = docs['queue']
    ensure(queue.get('status') == 'provisional_review_queue_not_partition_approval'
           and queue.get('execution_authorized') is False
           and queue.get('final_split_freeze_authorized') is False,
           'Unexpected queue approval or status')
    pairs = queue.get('reviewed_pairs_priority_order')
    ensure(isinstance(pairs, list) and len(pairs) == 28,
           'Expected exactly 28 original reviewed pairs')

    source_pairs = {}
    for p in pairs:
        k = key_of(p)
        ensure(k not in source_pairs, f'Duplicate reviewed pair {k}')
        ensure(p.get('cross_partition') is True, f'Not cross-partition: {k}')
        for letter in ('a', 'b'):
            task = p['task_' + letter]
            ensure(task in tasks and
                   tasks[task]['partition'] == p['partition_' + letter],
                   f'Partition mismatch for {task}')
        source_pairs[k] = p

    ensure(docs['packet'].get('pair_count') == 8 and
           docs['packet'].get('execution_authorized') is False and
           docs['packet'].get('split_freeze_authorized') is False,
           'Public-spec packet is not the verified eight-pair draft packet')
    ensure(docs['public'].get('source_packet_sha256') == provenance['packet']['sha256']
           and docs['public'].get('execution_authorized') is False
           and docs['public'].get('final_split_freeze_authorized') is False
           and docs['public'].get('recommendations_require_manual_policy_approval') is True,
           'Public adjudication provenance or permissions changed')
    ensure(docs['contract'].get('execution_authorized') is False
           and docs['contract'].get('final_split_freeze_authorized') is False,
           'Contract addendum claims unexpected permission')

    decisions = {}
    for label, expected_count in [('contract', 3), ('public', 8)]:
        items = docs[label].get('pairs')
        ensure(isinstance(items, list) and len(items) == expected_count,
               f'Unexpected pair count in {label}')
        for p in items:
            k = key_of(p)
            ensure(k not in decisions, f'Adjudication duplicated: {k}')
            for letter in ('a', 'b'):
                task = p['task_' + letter]
                recorded = p.get('prompt_sha_' + letter) if label == 'contract' \
                    else p.get('public_prompt_sha256_' + letter)
                ensure(task in tasks and
                       tasks[task]['public_prompt_sha256'] == recorded,
                       f'Public prompt SHA mismatch for {task} in {label}')
            ensure(p.get('verdict') in {'near_equivalent_solution_transfer',
                     'likely_equivalent_public_specification', 'related_but_distinct'},
                   f'Unexpected verdict in {label}: {k}')
            if label == 'contract':
                ensure(k in source_pairs and
                       source_pairs[k]['verdict'] == 'needs_contract_review',
                       f'Contract decision without matching unresolved review: {k}')
                ensure(p.get('exact_contract_equivalence_proven') is False,
                       'Contract addendum overclaims behavioral equivalence')
            elif k not in source_pairs:
                ensure(k == ('HumanEval/1', 'HumanEval/6'),
                       f'Unexpected extra public adjudication: {k}')
            decisions[k] = {'source': label, 'verdict': p['verdict'],
                            'recommendation': p.get('recommendation')}

    ensure(len(decisions) == 11, 'Expected 11 decisions across both addenda')
    ensure(len(set(source_pairs) | set(decisions)) == 29,
           'Expected 28 reviewed plus one HumanEval exception')

    rows = []
    for k in sorted(set(source_pairs) | set(decisions)):
        a, b = k
        pa, pb = tasks[a]['partition'], tasks[b]['partition']
        ensure(pa != pb, f'Cross-partition assumption failed for {k}')
        original = source_pairs.get(k)
        decision = decisions.get(k)
        if {'development'} & {pa, pb}:
            development_tasks = [x for x in (a, b)
                                 if tasks[x]['partition'] == 'development']
            held_dev = all(x in quarantine for x in development_tasks)
            if k == ('HumanEval/1', 'HumanEval/6'):
                action = 'SPECIAL_HOLD_HUMANEVAL_6_FOR_INDEPENDENT_EVALUATION_REVIEW'
            else:
                ensure(held_dev, f'Development overlap not quarantined: {k}')
                action = 'RETAIN_CURRENT_DEVELOPMENT_QUARANTINE'
        elif decision and decision['verdict'] == 'related_but_distinct':
            action = 'WATCHLIST_PENDING_FULL_CONTRACT_REVIEW'
        else:
            action = 'PROPOSE_GROUP_OR_EXCLUDE_FROM_CLEAN_VALIDATION_HELDOUT_COMPARISON'
        rows.append({
            'task_a': a, 'task_b': b, 'partition_a': pa, 'partition_b': pb,
            'original_verdict': original['verdict'] if original else None,
            'adjudicated_verdict': decision['verdict'] if decision else None,
            'adjudication_source': decision['source'] if decision else None,
            'proposed_action': action,
            'decision_state': 'REQUIRES_INDEPENDENT_REVIEW_AND_FORMAL_APPROVAL',
        })
    counts = Counter(p['proposed_action'] for p in rows)
    ensure(counts['RETAIN_CURRENT_DEVELOPMENT_QUARANTINE'] == 21,
           'Expected 21 existing development quarantine partner pairs')
    ensure(counts['PROPOSE_GROUP_OR_EXCLUDE_FROM_CLEAN_VALIDATION_HELDOUT_COMPARISON'] == 6,
           'Expected six validation/held-out high-overlap proposals')
    ensure(counts['WATCHLIST_PENDING_FULL_CONTRACT_REVIEW'] == 1,
           'Expected one related-but-distinct validation/held-out watchlist')
    ensure(counts['SPECIAL_HOLD_HUMANEVAL_6_FOR_INDEPENDENT_EVALUATION_REVIEW'] == 1,
           'Expected special HumanEval held-out review')

    temporal = sum(t.get('partition') == 'held_out_temporal_pending'
                   for t in tasks.values())
    ensure(temporal == 1055, 'Temporal split census changed')
    return {
        'schema_version': 1,
        'record_type': 'PHASE2D_SPLIT_RESOLUTION_PROPOSAL_V1',
        'status': 'PROPOSAL_ONLY_NO_PARTITION_FREEZE_OR_EXECUTION_AUTHORIZATION',
        'execution_authorized': False,
        'final_split_freeze_authorized': False,
        'manifest_modified': False,
        'quarantine_modified': False,
        'source_artifacts': provenance,
        'summary': {
            'original_reviewed_pairs': len(source_pairs),
            'adjudicated_pairs': len(decisions),
            'total_unique_covered_pairs': len(rows),
            'unadjudicated_original_pairs': len(set(source_pairs) - set(decisions)),
            'proposed_actions': dict(sorted(counts.items())),
            'existing_quarantined_development_tasks': len(quarantine),
            'temporal_tasks_pending_provenance': temporal,
        },
        'pairwise_provisional_actions': rows,
        'outstanding_gates': [
            'Independently adjudicate the other 18 originally reviewed development-side pairs; preserve existing quarantines meanwhile.',
            'Complete second-review and reconcile the separately recorded Batch 4 stratified sample of 81 overlap leads; this proposal does not incorporate it.',
            'Perform source-backed contract/transfer review of the validation-heldout pairs and explicitly decide whether to group or exclude.',
            'Explicitly resolve HumanEval/1 development versus HumanEval/6 held-out transfer before any clean held-out claim.',
            'Assess broader lexical/syntactic/semantic overlap screening coverage; the reviewed pairs are not a proof of full decontamination.',
            'Resolve 1055 LiveCodeBench temporal-pending provenance records before temporal evaluation.',
            'Obtain independent human review and separately approve/version a frozen grouping and split policy; keep existing guard unchanged until then.',
        ],
        'research_caveats': [
            'Decisions are prompt-level opinions, not tested behavioral equivalence.',
            'Existing quarantine covers the original 21 development-side reviewed pairs but does not authorize evaluation of other draft tasks.',
            'This is an evidence summary only; no dataset or policy changes are implied.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Do not write output')
    args = parser.parse_args()
    proposal = build()
    raw = (json.dumps(proposal, indent=2, sort_keys=True) + '\n').encode()
    print('PHASE 2D: SPLIT RESOLUTION PROPOSAL V1')
    for key, val in proposal['summary'].items():
        print(f'{key}: {val}')
    print('Status: proposal only, NOT a freeze or execution authorization')
    if args.preview:
        print('PREVIEW ONLY; no output written.')
        return
    path = ROOT / OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(raw)
    print('CREATED:', OUTPUT)
    print('SHA256:', sha256(raw).hexdigest())
    print('No existing artifacts, manifest, or guard modified.')


if __name__ == '__main__':
    main()
