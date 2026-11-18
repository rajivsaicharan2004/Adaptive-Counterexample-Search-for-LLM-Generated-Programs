#!/usr/bin/env python3
"""Explicit V4 *development-only* researcher scope extension. V3 is never edited.

This is a new, independent authorization boundary, not a claim that the
original V3 guard has approved these tasks. It re-verifies V3 source integrity,
original draft partitions, 8 pinned prompt hashes, and frozen oracle artifacts.
It fails closed until the research owner explicitly completes an attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import phase2d_quarantine_guard as original_v3
import phase2f_oracles_v1 as O
import phase2f_prepare_dev_suite_v1 as P

ROOT = Path(__file__).resolve().parent
ATTEST_REL = Path('results/phase2f/owner_scope_attestation_v1.json')
TECH_REVIEW_REL = Path('results/phase2d/phase2d_restricted_development_technical_feasibility_review_v1.json')
TECH_REVIEW_SHA256 = '9dc2e7939d71f7c24bf7eb7dd658539f99a4ab414e8b3f3670980857927aa433'
PROPOSAL_REL = Path('results/phase2d/restricted_development_eligibility_proposal_v1.json')
PROPOSAL_SHA256 = '3be9c55c8d835e52cca1c96f4249211ebadabfd8ab17a0f94a23f9d5db1cc024'
ACK = ('I authorize this eight-task development-only experiment under a self-attested '
       'research protocol; independent human review and clean held-out generalization '
       'have not been established.')


class ScopeError(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_json_no_symlink(path):
    if path.is_symlink() or not path.is_file():
        raise ScopeError(f'Missing or unsafe evidence file: {path}')
    return json.loads(path.read_text(encoding='utf-8'))


def verify_source_file(root, rel, expected):
    path = root / rel
    if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != expected:
        raise ScopeError(f'STALE SOURCE HASH: {rel}')


def attestation_template(root=ROOT):
    inputs_path = root / P.INPUTS_REL
    labels_path = root / P.LABELS_REL
    if not inputs_path.is_file() or not labels_path.is_file():
        raise ScopeError('Build and verify frozen oracle evidence first')
    return {
        'record_type': 'PHASE2F_OWNER_RESEARCHER_SELF_ATTESTATION_V1',
        'source_policy': 'V3 provenance verified, with separate V4 restricted scope extension',
        'research_review_type': 'researcher_self_attested_not_independent_human_review',
        'authorization_granted': False,
        'reviewer_identity': '',
        'review_date_utc': '',
        'exact_scope_acknowledgement': '',
        'allowed_intents': ['generate', 'evaluate'],
        'approved_task_ids': sorted(O.ORDER),
        'experimental_partition': 'development',
        'original_manifest_sha256': P.MANIFEST_SHA256,
        'source_eligibility_proposal_sha256': PROPOSAL_SHA256,
        'source_technical_review_sha256': TECH_REVIEW_SHA256,
        'frozen_inputs_sha256': sha(inputs_path.read_bytes()),
        'dual_oracle_labels_sha256': sha(labels_path.read_bytes()),
        'official_validation_heldout_or_temporal_use_authorized': False,
        'original_V3_guard_modified': False,
        'limitations': [
            'This self-attestation is not independent human reviewer approval.',
            'Public benchmark pretraining exposure and all unscreened semantic duplicates are not ruled out.',
            'Tested domains are bounded and do not prove full functional correctness.',
            'No validation, held-out, temporal, or quarantined tasks are authorized.',
        ],
    }


def verify_attestation(intent, task, root=ROOT):
    if intent not in ('generate', 'evaluate') or task not in O.ORDER:
        raise ScopeError(f'OUT OF SCOPE: {task}, {intent}')
    # This reproduces historical policy evidence verification WITHOUT pretending
    # the original V3 pilot allowlist has been amended.
    manifest, quarantined = original_v3.load_verified_policy(root)
    if manifest.get('status') != 'draft_requires_review_and_freeze':
        raise ScopeError('Unexpected original split status')
    if task in quarantined or manifest['tasks'].get(task, {}).get('partition') != 'development':
        raise ScopeError('Task not eligible in original V3 verified development partition')
    for rel, expected in ((TECH_REVIEW_REL, TECH_REVIEW_SHA256),
                          (PROPOSAL_REL, PROPOSAL_SHA256)):
        verify_source_file(root, rel, expected)
    # Rebuild and compare full frozen input and dual-oracle evidence.
    provenance = P.source_provenance(root)
    _, _, inputs, labels = P.make_documents(provenance, root)
    for rel, data in ((P.INPUTS_REL, inputs), (P.LABELS_REL, labels)):
        if not (root / rel).is_file() or (root / rel).is_symlink() or (root / rel).read_bytes() != data:
            raise ScopeError(f'Frozen evidence does not match its reproducible derivation: {rel}')
    record = load_json_no_symlink(root / ATTEST_REL)
    expected = attestation_template(root)
    locked_fields = (
        'record_type', 'source_policy', 'research_review_type',
        'allowed_intents', 'approved_task_ids', 'experimental_partition',
        'original_manifest_sha256', 'source_eligibility_proposal_sha256',
        'source_technical_review_sha256', 'frozen_inputs_sha256',
        'dual_oracle_labels_sha256',
        'official_validation_heldout_or_temporal_use_authorized',
        'original_V3_guard_modified', 'limitations',
    )
    for field in locked_fields:
        if record.get(field) != expected[field]:
            raise ScopeError(f'Owner attestation changed locked field: {field}')
    if record.get('authorization_granted') is not True:
        raise ScopeError('BLOCKED: no explicit owner authorization')
    if record.get('exact_scope_acknowledgement') != ACK:
        raise ScopeError('BLOCKED: exact researcher risk acknowledgement missing')
    if not isinstance(record.get('reviewer_identity'), str) or not record['reviewer_identity'].strip():
        raise ScopeError('BLOCKED: researcher identity required')
    try:
        parsed = datetime.fromisoformat(record['review_date_utc'].replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('missing timezone')
    except (ValueError, TypeError, AttributeError) as exc:
        raise ScopeError('BLOCKED: ISO-8601 UTC-offset review date required') from exc
    if intent not in record['allowed_intents']:
        raise ScopeError('Intent not granted')
    return {
        'task_id': task, 'intent': intent,
        'scope_type': 'researcher_self_attested_development_only_V4_extension',
        'attestation_sha256': sha((root / ATTEST_REL).read_bytes()),
        'owner_identity': record['reviewer_identity'],
        'review_timestamp_utc': record['review_date_utc'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--template', action='store_true')
    choice.add_argument('--check', action='store_true')
    parser.add_argument('--task-id', choices=O.ORDER, default='HumanEval/69')
    args = parser.parse_args()
    if args.template:
        # Validate the original immutable sources before drafting any scope.
        P.source_provenance(ROOT)
        record = attestation_template(ROOT)
        output = ROOT / ATTEST_REL
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf-8') as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write('\n')
        print('CREATED INACTIVE OWNER ATTESTATION TEMPLATE:', ATTEST_REL)
        print('SHA256:', sha(output.read_bytes()))
        print('No execution authorization; human must manually review and edit explicit fields.')
        print('ACKNOWLEDGEMENT REQUIRED EXACTLY:', ACK)
    else:
        print(verify_attestation('evaluate', args.task_id))
        print('SELF-ATTESTED RESTRICTED SCOPE; NOT INDEPENDENT HUMAN APPROVAL')


if __name__ == '__main__':
    main()
