#!/usr/bin/env python3
"""Build an immutable 8-task DEVELOPMENT input suite and dual-oracle labels.

--preview: trusted handwritten oracle self-checks and source checks, NO writes.
--build: create exclusively new, deterministic DEVELOPMENT inputs and labels.
--verify: re-derive and byte-verify both frozen artifacts.

Deliberately does NOT call V3 require_task_permission(): that permission
concerns candidate generation/evaluation, neither of which occurs here.
All model/candidate operations remain blocked by V3 pending policy approval.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import phase2f_oracles_v1 as O

ROOT = Path(__file__).resolve().parent
DATASET_REL = Path('data/public/humaneval.jsonl')
DATASET_SHA256 = '322d76a16580331fcfd54bf187c56c324f0ea5c4ab13f185363c42c6b750108a'
MANIFEST_REL = Path('results/phase2d/splits.json')
MANIFEST_SHA256 = 'c65578034f032b46ef7ad0865154d46e80156319f8d3f15c295d9b4c2d4eb747'
INPUTS_REL = Path('results/phase2f/dev_inputs_frozen_v1.json')
LABELS_REL = Path('results/phase2f/dev_dual_oracle_labels_v1.json')
SEED = 270219
COUNT = 128


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stable_bytes(obj):
    return (json.dumps(obj, ensure_ascii=True, indent=2, sort_keys=True,
                       allow_nan=False) + '\n').encode('utf-8')


def source_provenance(root=ROOT):
    import phase2d_quarantine_guard as guard
    manifest, quarantined = guard.load_verified_policy(root)
    if manifest.get('status') != 'draft_requires_review_and_freeze':
        raise RuntimeError('Unexpected manifest status for this fixed V1 protocol')
    for rel, sha in ((DATASET_REL, DATASET_SHA256), (MANIFEST_REL, MANIFEST_SHA256)):
        path = root / rel
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != sha:
            raise RuntimeError(f'Pinned source hash mismatch: {rel}')
    found = {}
    with (root / DATASET_REL).open('r', encoding='utf-8') as inp:
        for line in inp:
            if not line.strip():
                continue
            record = json.loads(line)
            task = record.get('task_id')
            if task not in O.TASKS:
                continue
            if task in found:
                raise RuntimeError(f'Duplicate task: {task}')
            found[task] = record
    if set(found) != set(O.TASKS):
        raise RuntimeError(f'Missing selected tasks: {sorted(set(O.TASKS) - set(found))}')
    for task, (_, _, manifest_sha, raw_sha) in O.TASKS.items():
        if task in quarantined:
            raise RuntimeError(f'Selected task has become quarantined: {task}')
        info = manifest['tasks'].get(task)
        if not isinstance(info, dict) or info.get('partition') != 'development':
            raise RuntimeError(f'Selected task is not development: {task}')
        if info.get('public_prompt_sha256') != manifest_sha:
            raise RuntimeError(f'Manifest prompt hash changed: {task}')
        if digest(found[task]['prompt'].encode('utf-8')) != raw_sha:
            raise RuntimeError(f'Raw public prompt changed: {task}')
    return {'manifest': str(MANIFEST_REL), 'manifest_sha256': MANIFEST_SHA256,
            'public_humaneval_sha256': DATASET_SHA256,
            'policy_status': 'draft_requires_review_and_freeze',
            'verified_review_batches': 3,
            'selected_original_prompt_hashes': {
                task: {'manifest': meta[2], 'raw': meta[3]}
                for task, meta in O.TASKS.items()
            }}


def make_documents(provenance, root=ROOT):
    oracle_path = root / 'phase2f_oracles_v1.py'
    prep_path = root / 'phase2f_prepare_dev_suite_v1.py'
    for path in (oracle_path, prep_path):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f'Missing source script: {path}')
    code_sha = digest(oracle_path.read_bytes())
    prep_sha = digest(prep_path.read_bytes())
    inputs = {
        'record_type': 'PHASE2F_FROZEN_PUBLIC_DEVELOPMENT_INPUTS_V1_NO_APPROVAL',
        'protocol_version': 1,
        'policy_and_execution_authorized': False,
        'official_validation_heldout_or_temporal_data_used': False,
        'status': 'development_only_candidate_blind_frozen_inputs',
        'input_generation_seed': SEED,
        'count_per_task': COUNT,
        'expected_values_included': False,
        'source_provenance': provenance,
        'generator_sha256': code_sha,
        'preparer_sha256': prep_sha,
        'tasks': {}
    }
    labels_by_task = {}
    for task in O.ORDER:
        cases = O.make_cases(task, COUNT, SEED)
        inputs['tasks'][task] = {
            'entry_point': O.TASKS[task][0],
            'cases': [{'name': case['name'], 'args': case['args']} for case in cases]
        }
        labels_by_task[task] = []
        for case in cases:
            exact = O.oracle_pair(task, case['args'])
            # JSON serialization maps Python tuples to arrays, but preserves the
            # pre-serialization runtime type in expected_python_type.
            encoded = json.loads(json.dumps(exact, allow_nan=False))
            labels_by_task[task].append({
                'name': case['name'],
                'expected_python_type': type(exact).__name__,
                'expected_json_value': encoded,
            })
    input_bytes = stable_bytes(inputs)
    labels = {
        'record_type': 'PHASE2F_DEVELOPMENT_DUAL_ORACLE_LABELS_V1_NO_APPROVAL',
        'protocol_version': 1,
        'candidate_execution_authorized': False,
        'official_validation_heldout_or_temporal_data_used': False,
        'test_inputs_sha256': digest(input_bytes),
        'oracle_implementation_sha256': code_sha,
        'oracle_agreement_required': True,
        'oracle_cross_checks_per_task': COUNT,
        'limitations': [
            'Development-only bounded input domains, not the official full task domains.',
            'Two implementations written by one assistant are not independent human verification.',
            'A passing program is not proven correct.',
            'Candidate generation/evaluation still requires separately authorized policy scope.',
        ],
        'tasks': labels_by_task,
    }
    return inputs, labels, input_bytes, stable_bytes(labels)


def check_documents(inputs, labels):
    if set(inputs['tasks']) != set(O.TASKS) or set(labels['tasks']) != set(O.TASKS):
        raise AssertionError('Task coverage changed')
    total = 0
    for task in O.ORDER:
        cases = inputs['tasks'][task]['cases']
        evidence = labels['tasks'][task]
        if len(cases) != COUNT or len(evidence) != COUNT:
            raise AssertionError(f'Wrong challenge count: {task}')
        seen = set()
        for case, row in zip(cases, evidence):
            if case['name'] != row['name']:
                raise AssertionError('Evidence ordering mismatch')
            key = json.dumps(case['args'], sort_keys=True, separators=(',', ':'))
            if key in seen:
                raise AssertionError(f'Duplicate input: {task}')
            seen.add(key)
            output = O.oracle_pair(task, case['args'])
            if type(output).__name__ != row['expected_python_type']:
                raise AssertionError('Oracle type drift')
            if json.loads(json.dumps(output)) != row['expected_json_value']:
                raise AssertionError('Oracle value drift')
            total += 1
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preview', action='store_true')
    group.add_argument('--build', action='store_true')
    group.add_argument('--verify', action='store_true')
    args = parser.parse_args()

    selfcheck = O.exhaustively_selfcheck()
    print('DUAL-ORACLE SELF-CHECKS:', json.dumps(selfcheck, sort_keys=True))
    print('SELF-CHECK TOTAL:', sum(selfcheck.values()))
    provenance = source_provenance(ROOT)
    inputs, labels, input_bytes, label_bytes = make_documents(provenance)
    total = check_documents(inputs, labels)
    print('Verified original public task prompts and V3 read-only policy:', len(O.TASKS))
    print('Development challenge inputs with two matching handwritten oracles:', total)
    print('INPUT SHA256:', digest(input_bytes))
    print('LABEL SHA256:', digest(label_bytes))

    if args.preview:
        print('PREVIEW ONLY; no files created.')
    elif args.verify:
        for rel, expected in ((INPUTS_REL, input_bytes), (LABELS_REL, label_bytes)):
            path = ROOT / rel
            if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
                raise RuntimeError(f'Frozen artifact changed or missing: {rel}')
        print('FROZEN DEVELOPMENT INPUTS AND ORACLE LABELS VERIFIED BYTE-FOR-BYTE')
    elif args.build:
        output_paths = (ROOT / INPUTS_REL, ROOT / LABELS_REL)
        if any(path.exists() or path.is_symlink() for path in output_paths):
            raise RuntimeError('Refusing to overwrite a frozen evidence artifact')
        output_paths[0].parent.mkdir(parents=True, exist_ok=True)
        with output_paths[0].open('xb') as handle:
            handle.write(input_bytes)
        try:
            with output_paths[1].open('xb') as handle:
                handle.write(label_bytes)
        except BaseException:
            # Leave the already frozen challenge visible, not silently replaced.
            print('PARTIAL BUILD: frozen input exists; inspect before retrying')
            raise
        print('CREATED:', INPUTS_REL)
        print('CREATED:', LABELS_REL)
    print('No LLM/model calls; no model-generated code or canonical benchmark reference solutions executed.')
    print('No policy change, execution authorization, or held-out evaluation.')


if __name__ == '__main__':
    main()
