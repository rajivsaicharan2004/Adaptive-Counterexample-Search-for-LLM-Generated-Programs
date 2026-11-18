#!/usr/bin/env python3
"""8-task Phase 2F DEVELOPMENT candidate evaluator, fail-closed by V4 owner scope.

Usage:
  python phase2f_guarded_candidate_eval_v1.py --preflight
  python phase2f_guarded_candidate_eval_v1.py --run --task-id HumanEval/69

--run requires an explicitly completed V4 researcher self-attestation. The V4
scope verifier rechecks the original V3 evidence and never edits V3 itself.
Candidate code is only executed by the existing pinned hardened Docker executor.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import phase2a_validator as validator
import phase2f_scope_gate_v1 as scope
import phase2e_smoke_v1 as smoke
import phase2f_oracles_v1 as O
import phase2f_prepare_dev_suite_v1 as P

ROOT = Path(__file__).resolve().parent
BATCH = 16
REPORT_REL = Path('results/phase2f/candidate_reports')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_verified_evidence():
    # Trusted handwritten-oracle checks; no generated code executed.
    evidence = P.source_provenance(ROOT)
    inputs, labels, expected_inputs, expected_labels = P.make_documents(evidence)
    if P.check_documents(inputs, labels) != 8 * 128:
        raise RuntimeError('Unexpected development challenge count')
    for rel, expected in ((P.INPUTS_REL, expected_inputs), (P.LABELS_REL, expected_labels)):
        path = ROOT / rel
        if not path.is_file() or path.is_symlink() or path.read_bytes() != expected:
            raise RuntimeError(f'Frozen challenge/labels missing, stale, or modified: {rel}')
    if labels['test_inputs_sha256'] != sha(expected_inputs):
        raise RuntimeError('Input/label binding hash mismatch')
    return inputs, labels, sha(expected_inputs), sha(expected_labels)


def candidates_for_task(task):
    folder = ROOT / 'generated' / 'phase2f' / task.replace('/', '_')
    base = (ROOT / 'generated' / 'phase2f').resolve()
    if not folder.is_dir() or folder.is_symlink() or not folder.resolve().is_relative_to(base):
        raise RuntimeError(f'Missing or unsafe generated/phase2f candidate folder: {folder}')
    found = []
    for path in sorted(folder.glob('*.py')):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
            raise RuntimeError('Candidate path is not a safe regular file')
        metadata = path.with_suffix('.json')
        if not metadata.is_file() or metadata.is_symlink():
            raise RuntimeError(f'Missing model-generation provenance file: {metadata}')
        code_bytes = path.read_bytes()
        if len(code_bytes) > validator.MAX_CODE_BYTES:
            raise RuntimeError('Candidate exceeds hardened sandbox input size')
        meta = json.loads(metadata.read_text(encoding='utf-8'))
        if (meta.get('task_id') != task or meta.get('source_sha256') != sha(code_bytes)
                or not isinstance(meta.get('model'), str) or not meta['model']
                or not isinstance(meta.get('method'), str) or not meta['method']):
            raise RuntimeError(f'Candidate provenance mismatch: {path}')
        # Static source analysis only. Never Python-import the candidate here.
        static_problem = None
        try:
            tree = ast.parse(code_bytes.decode('utf-8'), filename=path.name)
            top_names = {node.name for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if O.TASKS[task][0] not in top_names:
                static_problem = 'missing_required_entry_point'
        except (SyntaxError, UnicodeDecodeError) as exc:
            static_problem = f'syntax_or_encoding_error: {str(exc)[:150]}'
        found.append({'path': path, 'metadata': meta, 'hash': sha(code_bytes),
                      'static_problem': static_problem})
    if not found:
        raise RuntimeError(f'No registered candidates in {folder}')
    return found


def typed_match(result, expected):
    actual_value = result.get('value')
    expected_value = expected['expected_json_value']
    return (result.get('status') == 'ok'
            and result.get('type') == expected['expected_python_type']
            and type(actual_value) is type(expected_value)
            and actual_value == expected_value)


def check_permission(task):
    # V4 is a separate, explicitly self-attested scope, NOT a V3 permission.
    # It revalidates all original V3 evidence and the approved exact task list.
    return scope.verify_attestation('evaluate', task, ROOT)


def run_one(task, candidate, cases, expected):
    code_bytes = candidate['path'].read_bytes()
    if sha(code_bytes) != candidate['hash']:
        raise RuntimeError('Candidate hash changed before execution')
    code = code_bytes.decode('utf-8')
    entry = O.TASKS[task][0]
    observed = []
    wall_seconds = 0
    for offset in range(0, len(cases), BATCH):
        check_permission(task)
        current = cases[offset:offset + BATCH]
        requests = [{'entry_point': entry, 'args': case['args']} for case in current]
        before = perf_counter()
        results = validator.docker_execute(code, requests)
        wall_seconds += perf_counter() - before
        for case, label, outcome in zip(current, expected[offset:offset + BATCH], results):
            if case['name'] != label['name']:
                raise RuntimeError('Challenge and label order mismatch')
            passed = typed_match(outcome, label)
            observed.append({'case_name': case['name'], 'args': case['args'] if not passed else None, 'passed': passed,
                             'candidate_result': outcome if not passed else None,
                             'oracle_type': label['expected_python_type'] if not passed else None,
                             'oracle_value': label['expected_json_value'] if not passed else None})
    failed = [row for row in observed if not row['passed']]
    reproduction = None
    if failed:
        target = next(case for case in cases if case['name'] == failed[0]['case_name'])
        first_expected = next(label for label in expected if label['name'] == target['name'])
        check_permission(task)
        repeated = validator.docker_execute(code, [{'entry_point': entry, 'args': target['args']}])[0]
        reproduction = {'case_name': target['name'], 'reproduced_failure': not typed_match(repeated, first_expected),
                        'repeated_result': repeated}
    return {'source_sha256': candidate['hash'], 'source_path': str(candidate['path'].relative_to(ROOT)),
            'generation_provenance': candidate['metadata'],
            'case_count': len(cases), 'passed': len(cases) - len(failed),
            'failed': len(failed), 'first_failing_case': failed[0] if failed else None,
            'first_five_failures': failed[:5], 'first_failure_reproduction': reproduction,
            'docker_wall_seconds': round(wall_seconds, 6),
            'candidate_calls': len(cases), 'status': 'observed_development_failures' if failed else 'no_failure_on_frozen_development_suite'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--task-id', choices=O.ORDER, default=None)
    args = parser.parse_args()

    inputs, labels, input_hash, label_hash = load_verified_evidence()
    smoke.check_sandbox_contract()
    print('Verified original V3 source integrity; frozen 8-task challenge and labels.')
    print('INPUT SHA256:', input_hash)
    print('LABEL SHA256:', label_hash)
    print('Pinned Docker image:', validator.IMAGE)
    if args.preflight:
        blocked = 0
        for task in O.ORDER:
            try:
                permission = check_permission(task)
            except (scope.ScopeError, RuntimeError) as exc:
                blocked += 1
                print(f'{task}: BLOCKED by V4 owner scope ({exc})')
            else:
                print(f'{task}: {permission}')
        print(f'V4 scope blocked {blocked}/8 selected tasks; no Docker or candidate code executed.')
        print('Do not edit V3. V4 must be explicitly self-attested first.')
        return

    if not args.task_id:
        parser.error('--run requires --task-id')
    # Authorization BEFORE checking candidate files, Docker, or running code.
    print(check_permission(args.task_id))
    candidates = candidates_for_task(args.task_id)
    validator.ensure_docker()
    results = []
    seen_hashes = set()
    for candidate in candidates:
        if candidate['hash'] in seen_hashes:
            results.append({'source_sha256': candidate['hash'],
                            'source_path': str(candidate['path'].relative_to(ROOT)),
                            'status': 'duplicate_code_not_re_evaluated'})
            continue
        seen_hashes.add(candidate['hash'])
        if candidate['static_problem']:
            results.append({'source_sha256': candidate['hash'],
                            'source_path': str(candidate['path'].relative_to(ROOT)),
                            'status': 'static_generation_failure',
                            'reason': candidate['static_problem']})
            continue
        print(check_permission(args.task_id))
        results.append(run_one(args.task_id, candidate,
                               inputs['tasks'][args.task_id]['cases'], labels['tasks'][args.task_id]))
        print(candidate['hash'][:12], results[-1]['status'], results[-1]['failed'])
    report = {
        'record_type': 'PHASE2F_FROZEN_DEVELOPMENT_CANDIDATE_EVALUATION_V1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'task_id': args.task_id, 'partition': 'development',
        'input_suite_sha256': input_hash, 'oracle_labels_sha256': label_hash,
        'docker_image': validator.IMAGE,
        'saved_candidate_count': len(results),
        'unique_candidate_source_count': len(seen_hashes), 'reports': results,
        'model_generated_source_executed_only_inside_hardened_docker': True,
        'heldout_or_validation_data_used': False,
        'limit': 'Development-only evidence. A passing candidate is not proven correct.',
    }
    output = ROOT / REPORT_REL / f'{args.task_id.replace("/", "_")}_{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}_{uuid4().hex[:8]}.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = P.stable_bytes(report)
    with output.open('xb') as handle:
        handle.write(payload)
    print('CREATED:', output.relative_to(ROOT))
    print('REPORT SHA256:', sha(payload))
    print('Not an independent held-out evaluation.')


if __name__ == '__main__':
    main()
