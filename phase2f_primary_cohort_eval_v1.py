#!/usr/bin/env python3
"""Fail-closed, manifest-selected Phase-2F DEVELOPMENT cohort evaluation.

    python phase2f_primary_cohort_eval_v1.py --preflight
    python phase2f_primary_cohort_eval_v1.py --run --task-id HumanEval/129

This is a NEW wrapper around the unchanged guarded evaluator. It does not
modify V3, V4, frozen inputs, candidates, or the original evaluator. The
only generated code it can run comes from the exact 24-member primary cohort.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import phase2f_guarded_candidate_eval_v1 as E

ROOT = Path(__file__).resolve().parent
MANIFEST_REL = 'results/phase2f/primary_acquisition_cohort_manifest_v1.json'
MANIFEST_SHA = '7ee24e3e21158355aa96d0ea9c9162a81fd6502af9cbe86451862ee5ed9e93cb'
BASELINE_SHA = '77f412560a21e53467840acc00dbd1b2b78691b56271139a9b9f5a55ea283dcc'
PROTOCOL_SHA = 'f4ee464a76bdb0311d411b2534c08c0ce9a32fbb09c78a0e1de0e6fac99f013a'
DEVIATION_SHA = '1dd58578a38800be32c4589ee14771fcb6761441f1005523e28516eab0a80d40'
DOCKER_IMAGE = ('python:3.11-slim@sha256:'
                '07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535')
REPORT_REL = Path('results/phase2f/primary_cohort_reports')
METHODS = ('sampling', 'diverse', 'boundary')


class CohortGateError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise CohortGateError(f'Missing, unsafe or symlinked file: {path}')
    return sha(path.read_bytes())


def safe_path(relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CohortGateError('Invalid relative file path')
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or p.parts[0] == '.':
        raise CohortGateError(f'Unsafe relative file path: {relative}')
    resolved = (ROOT / p).resolve()
    if not resolved.is_relative_to(ROOT.resolve()):
        raise CohortGateError(f'Path escapes project root: {relative}')
    return ROOT / p


def load_pinned_json(relative: str, expected: str) -> dict:
    path = safe_path(relative)
    if file_sha(path) != expected:
        raise CohortGateError(f'Immutable reference hash mismatch: {relative}')
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise CohortGateError(f'Expected object in {relative}')
    return document


def single_py_path(paths: dict) -> str:
    matches = [rel for rel in paths if rel.endswith('.py')]
    if len(matches) != 1:
        raise CohortGateError('Expected exactly one source file per record')
    return matches[0]


def load_and_check_cohort():
    """Read-only full audit; returns task -> primary candidates to select."""
    cohort = load_pinned_json(MANIFEST_REL, MANIFEST_SHA)
    if cohort.get('record_type') != 'PHASE2F_PRIMARY_ACQUISITION_COHORT_V1':
        raise CohortGateError('Unexpected cohort manifest type')
    if (cohort.get('baseline_manifest_sha256') != BASELINE_SHA
            or cohort.get('acquisition_protocol_sha256') != PROTOCOL_SHA
            or cohort.get('deviation_record_sha256') != DEVIATION_SHA):
        raise CohortGateError('Cohort has incorrect upstream evidence references')

    baseline = load_pinned_json('results/phase2f/baseline_evidence_manifest_v1.json', BASELINE_SHA)
    protocol = load_pinned_json('results/phase2f/candidate_acquisition_protocol_v1.json', PROTOCOL_SHA)
    deviation = load_pinned_json('results/phase2f/candidate_acquisition_deviation_112_diverse_v1.json', DEVIATION_SHA)

    tasks = protocol.get('tasks')
    if (not isinstance(tasks, list) or len(tasks) != 8 or len(set(tasks)) != 8
            or set(tasks) != set(E.O.ORDER)):
        raise CohortGateError('Task coverage mismatch')
    if (cohort.get('primary_candidate_count') != 24
            or cohort.get('extra_candidate_count') != 1
            or cohort.get('total_observed_acquisition_calls') != 25
            or cohort.get('exact_byte_duplicate_primary_count') != 2
            or protocol.get('planned_new_model_calls') != 24
            or deviation.get('protocol_sha256') != PROTOCOL_SHA):
        raise CohortGateError('Candidate counts or protocol references changed')
    if cohort.get('model') != protocol.get('model') or cohort.get('model') != 'gemini-3.8-flash':
        raise CohortGateError('Model mismatch')
    if set(protocol.get('generation_methods_and_temperatures', {})) != set(METHODS):
        raise CohortGateError('Method coverage mismatch')

    all_artifacts = cohort.get('artifacts_sha256')
    if not isinstance(all_artifacts, dict) or len(all_artifacts) != 147:
        raise CohortGateError('Unexpected referenced artifact count')
    for relative, expected in sorted(all_artifacts.items()):
        if file_sha(safe_path(relative)) != expected:
            raise CohortGateError(f'Artifact hash mismatch: {relative}')
    expected_script = all_artifacts.get('phase2f_guarded_candidate_eval_v1.py')
    if expected_script != file_sha(safe_path('phase2f_guarded_candidate_eval_v1.py')):
        raise CohortGateError('Original guarded evaluator changed')
    if E.validator.IMAGE != DOCKER_IMAGE:
        raise CohortGateError('Pinned Docker image changed')

    baseline_by_task = {r['task_id']: r for r in baseline['records']}
    if set(baseline_by_task) != set(tasks):
        raise CohortGateError('Baseline task coverage mismatch')
    primary = cohort.get('primary_cohort')
    extras = cohort.get('excluded_extra_attempts')
    if not isinstance(primary, list) or len(primary) != 24 or not isinstance(extras, list) or len(extras) != 1:
        raise CohortGateError('Cohort roster shape mismatch')
    if extras[0].get('candidate_id') != deviation['candidates'][1]['candidate_id']:
        raise CohortGateError('Unexpected extra candidate identity')
    if extras[0].get('source_sha256') != deviation['candidates'][1]['source_sha256']:
        raise CohortGateError('Unexpected extra candidate hash')

    by_task = {task: [] for task in tasks}
    extras_by_task = {task: [] for task in tasks}
    for row, bucket in [(r, by_task) for r in primary] + [(r, extras_by_task) for r in extras]:
        task = row.get('task_id')
        method = row.get('method')
        if task not in bucket or method not in METHODS:
            raise CohortGateError('Unrecognized candidate or method')
        folder = Path('generated/phase2f') / task.replace('/', '_')
        source_rel = single_py_path(row.get('artifacts_sha256', {}))
        source_path = Path(source_rel)
        if source_path.parent != folder or source_path.stem != row.get('candidate_id'):
            raise CohortGateError('Candidate source path/ID outside approved task folder')
        for relative, expected in row['artifacts_sha256'].items():
            if all_artifacts.get(relative) != expected:
                raise CohortGateError('Candidate artifact not included in frozen manifest')
        if row.get('source_sha256') != all_artifacts[source_rel]:
            raise CohortGateError('Source hash inconsistency')

        metadata_path = safe_path(source_rel).with_suffix('.json')
        prompt_path = safe_path(source_rel).with_suffix('.prompt.txt')
        meta = json.loads(metadata_path.read_text(encoding='utf-8'))
        summary_rel = str(folder / (meta.get('run_id', '') + '_run_summary.json'))
        if (str(metadata_path.relative_to(ROOT)) not in row['artifacts_sha256']
                or str(prompt_path.relative_to(ROOT)) not in row['artifacts_sha256']
                or summary_rel not in row['artifacts_sha256']):
            raise CohortGateError('Candidate missing prompt, metadata or run summary in manifest')
        summary = json.loads(safe_path(summary_rel).read_text(encoding='utf-8'))
        if (meta.get('task_id') != task or meta.get('method') != method
                or meta.get('model') != cohort['model'] or meta.get('attempt') != 1
                or meta.get('status') != 'generated'
                or meta.get('source_sha256') != row['source_sha256']
                or meta.get('submitted_prompt_sha256') != all_artifacts[str(prompt_path.relative_to(ROOT))]
                or meta.get('temperature') != protocol['generation_methods_and_temperatures'][method]
                or summary.get('run_id') != meta.get('run_id')
                or summary.get('task_id') != task
                or summary.get('method') != method
                or summary.get('attempted_calls') != 1
                or summary.get('model_code_executed') is not False
                or summary.get('development_only') is not True
                or len(summary.get('records', [])) != 1
                or summary['records'][0].get('source_sha256') != row['source_sha256']):
            raise CohortGateError(f'Candidate provenance mismatch: {source_rel}')
        bucket[task].append({**row, 'source_path': source_rel})

    if len(extras_by_task['HumanEval/112']) != 1 or extras_by_task['HumanEval/112'][0]['method'] != 'diverse':
        raise CohortGateError('Extra attempt is not the documented excluded /112 diverse candidate')
    if sum(len(v) for v in extras_by_task.values()) != 1:
        raise CohortGateError('Unexpected extra attempt count')

    duplicate_count = 0
    original_by_task = {}
    registered_by_task = {}
    for task in tasks:
        rows = by_task[task]
        if len(rows) != 3 or {r['method'] for r in rows} != set(METHODS):
            raise CohortGateError(f'Exactly one primary per method required: {task}')
        if [r['method'] for r in rows] != list(METHODS):
            raise CohortGateError(f'Unexpected method order: {task}')
        baseline_record = baseline_by_task[task]
        if baseline_record.get('passed') != 128 or baseline_record.get('failed') != 0:
            raise CohortGateError('Original baseline outcome changed')
        base_source = single_py_path(baseline_record['artifacts_sha256'])
        if Path(base_source).parent != Path('generated/phase2f') / task.replace('/', '_'):
            raise CohortGateError('Baseline path outside expected task directory')
        initial_hash = all_artifacts.get(base_source)
        if initial_hash != baseline_record['artifacts_sha256'][base_source]:
            raise CohortGateError('Original baseline source hash missing')
        seen = {initial_hash: base_source}
        for row in rows:
            duplicated = row['source_sha256'] in seen
            if row.get('byte_duplicate_on_task') is not duplicated:
                raise CohortGateError('Frozen duplicate classification changed')
            row['duplicate_of'] = seen.get(row['source_sha256'])
            if not duplicated:
                seen[row['source_sha256']] = row['source_path']
            duplicate_count += int(duplicated)
        original_by_task[task] = {'source_path': base_source, 'sha256': initial_hash}

        # The original evaluator is allowed to READ all registered paths, but
        # this gate selects only the explicit three primary candidates.
        registered = E.candidates_for_task(task)  # Static analysis only, no imports of generated code.
        actual_paths = {str(c['path'].relative_to(ROOT)) for c in registered}
        expected_paths = ({base_source} | {r['source_path'] for r in rows}
                          | {r['source_path'] for r in extras_by_task[task]})
        if len(registered) != len(expected_paths) or actual_paths != expected_paths:
            raise CohortGateError(f'Unexpected candidate files present for {task}')
        registered_by_task[task] = {str(c['path'].relative_to(ROOT)): c for c in registered}
        for row in rows + extras_by_task[task]:
            registered_candidate = registered_by_task[task][row['source_path']]
            if registered_candidate['hash'] != row['source_sha256']:
                raise CohortGateError('Existing evaluator source verification mismatch')

    if duplicate_count != 2:
        raise CohortGateError('Unexpected primary duplicate count')
    return tasks, by_task, extras_by_task, original_by_task, registered_by_task


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_task(task, selected, originals, registered, inputs, labels, input_sha, label_sha):
    output_folder = safe_path(str(REPORT_REL))
    output_folder.mkdir(parents=True, exist_ok=True)
    intent = output_folder / f'{task.replace("/", "_")}_cohort_v1_run_intent.json'
    if intent.exists() or intent.is_symlink() or list(output_folder.glob(f'{task.replace("/", "_")}_cohort_v1_*.json')):
        raise CohortGateError(f'Task may already have a cohort run or incomplete intent: {task}. Stop and audit; do not rerun.')

    # Persist an exclusive intent BEFORE any generated code executes. Interrupted
    # evaluations must be reconciled rather than silently repeated.
    intent_payload = E.P.stable_bytes({
        'record_type': 'PHASE2F_PRIMARY_COHORT_RUN_INTENT_V1',
        'created_utc': utc_now(), 'task_id': task,
        'primary_manifest_sha256': MANIFEST_SHA,
        'pinned_docker_image': DOCKER_IMAGE,
        'primary_candidate_ids': [row['candidate_id'] for row in selected],
        'candidate_source_sha256': [row['source_sha256'] for row in selected],
    })
    with intent.open('xb') as handle:
        handle.write(intent_payload)
    print('RUN INTENT CREATED:', intent.relative_to(ROOT), 'SHA256:', sha(intent_payload), flush=True)

    results = []
    for row in selected:
        candidate = registered[row['source_path']]
        if row['duplicate_of']:
            result = {
                'source_sha256': row['source_sha256'], 'source_path': row['source_path'],
                'generation_provenance': candidate['metadata'],
                'status': 'duplicate_source_not_executed',
                'duplicate_of': row['duplicate_of'],
                'baseline_reused_not_retested': row['duplicate_of'] == originals['source_path'],
                'candidate_calls': 0,
                'note': 'Source duplicate: no new Docker execution; do not count as a fresh test pass.',
            }
        elif candidate['static_problem']:
            result = {
                'source_sha256': row['source_sha256'], 'source_path': row['source_path'],
                'generation_provenance': candidate['metadata'],
                'status': 'static_generation_failure',
                'reason': candidate['static_problem'], 'candidate_calls': 0,
            }
        else:
            print('EVALUATING:', task, row['method'], row['candidate_id'], flush=True)
            E.check_permission(task)
            result = E.run_one(task, candidate,
                               inputs['tasks'][task]['cases'], labels['tasks'][task])
        result['candidate_id'] = row['candidate_id']
        result['method'] = row['method']
        result['primary_cohort'] = True
        results.append(result)
        print('RESULT:', task, row['method'], result['status'],
              'failures:', result.get('failed', 'n/a'), flush=True)

    report = {
        'record_type': 'PHASE2F_PRIMARY_COHORT_FROZEN_DEV_EVAL_V1',
        'created_utc': utc_now(), 'task_id': task, 'partition': 'development',
        'primary_cohort_manifest_sha256': MANIFEST_SHA,
        'runner_sha256': file_sha(Path(__file__)),
        'run_intent_sha256': sha(intent_payload),
        'input_suite_sha256': input_sha, 'oracle_labels_sha256': label_sha,
        'docker_image': DOCKER_IMAGE,
        'primary_candidate_count': 3, 'excluded_extra_candidate_count': (1 if task == 'HumanEval/112' else 0),
        'reports': results, 'heldout_or_validation_data_used': False,
        'note': ('Development only. Duplicates were not retested. Passing test inputs '
                 'does not establish program correctness or held-out generalization.'),
    }
    output = output_folder / (f'{task.replace("/", "_")}_cohort_v1_'
                              f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}_'
                              f'{uuid4().hex[:8]}.json')
    raw = E.P.stable_bytes(report)
    with output.open('xb') as handle:
        handle.write(raw)
    print('REPORT CREATED:', output.relative_to(ROOT))
    print('REPORT SHA256:', sha(raw))
    print('Original V3, original evaluator, baseline, and candidate sources unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preflight', action='store_true', help='Read-only cohort, evidence, sandbox and scope checks')
    group.add_argument('--run', action='store_true', help='Evaluate one task, three PRIMARY candidates only')
    parser.add_argument('--task-id', choices=E.O.ORDER)
    args = parser.parse_args()
    if args.run and not args.task_id:
        parser.error('--run requires --task-id')
    if args.preflight and args.task_id:
        parser.error('--task-id is only valid with --run')

    # Read-only full integrity checks before accessing Docker or candidate execution.
    tasks, selected, excluded, originals, registered = load_and_check_cohort()
    inputs, labels, input_hash, label_hash = E.load_verified_evidence()
    E.smoke.check_sandbox_contract()
    for task in tasks:
        E.check_permission(task)
    print('FROZEN COHORT HASH:', MANIFEST_SHA)
    print('FROZEN INPUT HASH:', input_hash)
    print('FROZEN ORACLE LABEL HASH:', label_hash)
    print('PINNED DOCKER:', DOCKER_IMAGE)
    print('SCOPE: researcher self-attested development ONLY; original V3 unchanged.')
    print('PRIMARY CANDIDATES: 24; EXCLUDED EXTRA ATTEMPTS: 1; SOURCE DUPLICATES: 2')
    if args.preflight:
        for task in tasks:
            print('READY:', task, 'primary=', len(selected[task]), 'excluded=', len(excluded[task]))
        print('PREFLIGHT PASS: no Docker or generated code executed; no files written.')
        return

    task = args.task_id
    output_folder = ROOT / REPORT_REL
    intent = output_folder / f'{task.replace("/", "_")}_cohort_v1_run_intent.json'
    if intent.exists() or intent.is_symlink() or list(output_folder.glob(f'{task.replace("/", "_")}_cohort_v1_*.json')):
        raise CohortGateError('This task already has a run intent/report. Stop; do not rerun.')
    # Explicit authorization and Docker availability BEFORE writing an intent.
    E.check_permission(task)
    E.validator.ensure_docker()
    run_task(task, selected[task], originals[task], registered[task],
             inputs, labels, input_hash, label_hash)


if __name__ == '__main__':
    main()
