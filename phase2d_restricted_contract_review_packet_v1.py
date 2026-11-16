#!/usr/bin/env python3
"""Prepare 24-task PUBLIC development contract review packet (not approval).

Usage:
    .venv/bin/python phase2d_restricted_contract_review_packet_v1.py --preview
    .venv/bin/python phase2d_restricted_contract_review_packet_v1.py

Reads only already reviewed project evidence and PUBLIC task prompts. No test
cases, reference solutions, generated candidates, model calls, or Docker runs.
The pre-existing guard and dataset partitions are NEVER modified.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import phase2d_quarantine_guard as guard
import phase2d_restricted_development_eligibility_v1 as eligibility
from phase2d_global_overlap_audit import load_and_verify

ROOT = Path(__file__).resolve().parent
PROPOSAL_REL = Path('results/phase2d/restricted_development_eligibility_proposal_v1.json')
EXPECTED_PROPOSAL_SHA256 = '3be9c55c8d835e52cca1c96f4249211ebadabfd8ab17a0f94a23f9d5db1cc024'
OUTPUT_REL = Path('results/phase2d/restricted_development_contract_review_packet_v1.json')
EXPECTED_COUNTS = {'humaneval': 12, 'mbpp': 12}


def require(ok, msg):
    if not ok:
        raise RuntimeError(msg)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extract_signatures(public_prompt):
    """Static AST inspection ONLY; does not import or execute prompt code."""
    try:
        tree = ast.parse(public_prompt)
    except (SyntaxError, ValueError):
        return [], 'public_prompt_not_parseable_as_complete_python_module'
    signatures = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            source = ast.get_source_segment(public_prompt, node)
            first_line = source.splitlines()[0] if source else 'def ' + node.name + '(...)'
            signatures.append({'function_name': node.name, 'header_excerpt': first_line[:400]})
    return signatures, None


def static_review_flags(text, has_signature):
    """Triage leads, not safety or correctness judgments."""
    flags = []
    if not has_signature:
        flags.append('public_prompt_lacks_machine_readable_function_signature')
    patterns = [
        (r'\bprint\b|\bstdout\b', 'check_print_vs_return_contract'),
        (r'\b(?:in.place|mutat(?:e|ion)|modif(?:y|ies)\s+the\s+(?:input|list|array))\b',
         'check_input_mutation_and_side_effects'),
        (r'\b(?:recurs(?:e|ive|ion)|permutation|combination|subsequence)\b',
         'review_input_size_and_runtime_budget'),
        (r'\b(?:regular\s+expression|regex)\b', 'review_regex_matching_semantics'),
        (r'\b(?:float|rounding|precision)\b', 'review_numeric_tolerance'),
    ]
    for pattern, flag in patterns:
        if re.search(pattern, text, flags=re.I):
            flags.append(flag)
    return flags


def build_packet():
    proposal_path = ROOT / PROPOSAL_REL
    require(proposal_path.is_file(), f'Missing source proposal: {proposal_path}')
    proposal_bytes = proposal_path.read_bytes()
    require(sha(proposal_bytes) == EXPECTED_PROPOSAL_SHA256,
            'Proposal SHA-256 mismatch; do not proceed with unverified shortlist')
    proposal = json.loads(proposal_bytes)
    require(proposal.get('execution_authorized') is False and
            proposal.get('split_freeze_authorized') is False and
            proposal.get('guard_modification_authorized') is False,
            'Unexpected proposal authorization fields')
    require(proposal.get('record_type') ==
            'PHASE2D_RESTRICTED_DEVELOPMENT_ELIGIBILITY_PROPOSAL_V1_NOT_APPROVAL',
            'Unrecognized proposal type')

    # Deterministically rebuild the exact earlier shortlist using the existing
    # reviewed source hashes, quarantine guard, and precautionary exclusions.
    independently_recomputed = eligibility.build()
    require(proposal == independently_recomputed,
            'Recomputed shortlist differs from saved proposal; fail closed')

    manifest, quarantine = guard.load_verified_policy(ROOT)
    public_tasks, second_manifest, source_hashes = load_and_verify(ROOT)
    require(manifest == second_manifest, 'Manifest changed during verification')
    require(manifest.get('status') == 'draft_requires_review_and_freeze',
            'This packet requires the unchanged draft-policy state')
    require(len(public_tasks) == 3333, 'Unexpected public task count')
    require(len(quarantine) == 21, 'Existing quarantine count changed')

    selected = proposal.get('shortlist_for_manual_review')
    require(isinstance(selected, list) and len(selected) == 24, 'Expected exactly 24 tasks')
    names = [item['task_id'] for item in selected]
    require(len(set(names)) == 24, 'Duplicate proposed task ID')
    require(Counter(item['dataset'] for item in selected) == EXPECTED_COUNTS,
            'Dataset shortlist balance changed')

    indexed = {t.task_id: t for t in public_tasks}
    review_entries = []
    for rank, item in enumerate(selected, 1):
        name = item['task_id']
        require(name in indexed, f'Unknown public task: {name}')
        t = indexed[name]
        require(t.partition == 'development' and
                manifest['tasks'][name]['partition'] == 'development',
                f'Not a development task: {name}')
        require(name not in quarantine and name not in guard.PILOT_TASKS,
                f'Not a new, non-quarantined development task: {name}')
        require(t.dataset == item['dataset'] and
                t.normalized_hash == item['public_prompt_sha256'] ==
                manifest['tasks'][name]['public_prompt_sha256'],
                f'Prompt hash or source mismatch: {name}')
        require(item.get('execution_authorized') is False,
                f'Unexpected task execution authorization: {name}')

        signatures, ast_warning = extract_signatures(t.prompt)
        flags = static_review_flags(t.prompt, bool(signatures))
        if ast_warning:
            flags.append(ast_warning)
        if t.dataset == 'mbpp':
            flags.append('mbpp_one_line_spec_may_not_define_full_interface_or_edge_cases')

        review_entries.append({
            'review_rank': rank,
            'task_id': name,
            'dataset': t.dataset,
            'partition': 'development',
            'family_heuristic': item['family'],
            'prompt_complexity_proxy_not_measured_difficulty': item['prompt_complexity_proxy'],
            'manifest_public_prompt_sha256': t.normalized_hash,
            'raw_public_prompt_sha256': sha(t.prompt.encode('utf-8')),
            'public_prompt': t.prompt,
            'statically_extracted_functions': signatures,
            'automated_review_flags_not_conclusions': sorted(set(flags)),
            'execution_authorized': False,
            'human_review': {
                'status': 'PENDING',
                'reviewer_identity': None,
                'review_timestamp_utc': None,
                'input_domain_and_edge_cases': None,
                'return_type_and_side_effect_contract': None,
                'semantic_overlap_concerns': None,
                'deterministic_oracle_strategy': None,
                'safe_hardened_docker_execution_plan': None,
                'decision_one_of_approve_reject_defer': None,
                'rationale': None,
            },
        })

    return {
        'schema_version': 1,
        'record_type': 'PHASE2D_RESTRICTED_DEVELOPMENT_CONTRACT_REVIEW_PACKET_V1_NOT_APPROVAL',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'proposal_path': str(PROPOSAL_REL),
        'proposal_sha256': EXPECTED_PROPOSAL_SHA256,
        'source_dataset_and_manifest_sha256': source_hashes,
        'manifest_status': manifest['status'],
        'task_count': len(review_entries),
        'dataset_counts': dict(sorted(Counter(p['dataset'] for p in review_entries).items())),
        'independent_human_review_completed': False,
        'all_contract_reviews_pending': True,
        'execution_authorized': False,
        'guard_change_authorized': False,
        'split_freeze_authorized': False,
        'notes': [
            'Only public prompts for proposed DEVELOPMENT tasks are included; no reference solutions or tests.',
            'Task family and complexity labels are heuristic, not measured difficulty.',
            'AST header extraction is static and does not execute code.',
            'Passing a keyword screen does not establish safe execution, correct oracle behavior, or clean held-out separation.',
            'Human review fields are intentionally blank; no independent human review is implied.',
            'Approval would require a separately reviewed and versioned guard/policy amendment.',
        ],
        'tasks': review_entries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Verify and display selected tasks, write nothing')
    args = parser.parse_args()
    result = build_packet()
    print('=' * 72)
    print('PHASE 2D: RESTRICTED DEVELOPMENT CONTRACT REVIEW PACKET V1')
    print('=' * 72)
    print('Source proposal SHA256 verified:', result['proposal_sha256'])
    print('Recomputed proposal matches saved proposal: True')
    print('Task count:', result['task_count'])
    print('Dataset counts:', result['dataset_counts'])
    for item in result['tasks']:
        print(f"  {item['review_rank']:02d}. {item['task_id']} | {item['family_heuristic']} | "
              f"static flags={len(item['automated_review_flags_not_conclusions'])}")
    print('No new execution, guard change, or split-freeze authorization.')
    if args.preview:
        print('PREVIEW ONLY. No output written.')
        return
    output = ROOT / OUTPUT_REL
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(result, indent=2, sort_keys=True) + '\n').encode('utf-8')
    with output.open('xb') as f:
        f.write(payload)
    print('CREATED:', OUTPUT_REL)
    print('SHA256:', sha(payload))
    print('Original evidence, manifest, and V3 guard unchanged.')


if __name__ == '__main__':
    main()
