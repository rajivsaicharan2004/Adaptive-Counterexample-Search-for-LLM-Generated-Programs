#!/usr/bin/env python3
"""Fail-closed task policy based on BOTH provisional public-prompt reviews.

Reads public task files, unchanged draft split manifest, global lexical report,
and two independently preserved manual reviews. No candidate execution.
"""
from __future__ import annotations

import json
from pathlib import Path

from phase2d_global_overlap_audit import load_and_verify, sha256_file

REVIEW_REL = Path("results/phase2d/global_overlap_audit_v1/manual_review.json")
REPORT_REL = Path("results/phase2d/global_overlap_audit_v1/global_overlap_report.json")
DRAFT_STATUS = "draft_requires_review_and_freeze"
PILOT_TASKS = frozenset(("HumanEval/0", "HumanEval/1", "MBPP/545"))
# Defense in depth: review content may not silently remove any of these IDs.
KNOWN_BATCH1_QUARANTINE = frozenset((
    "MBPP/779", "MBPP/883", "MBPP/935", "MBPP/534", "MBPP/922",
    "BigCodeBench/895",
))
KNOWN_PAIRS = frozenset((
    frozenset(("MBPP/758", "MBPP/779")),
    frozenset(("MBPP/817", "MBPP/883")),
    frozenset(("MBPP/931", "MBPP/935")),
    frozenset(("MBPP/534", "MBPP/607")),
    frozenset(("MBPP/415", "MBPP/922")),
    frozenset(("BigCodeBench/894", "BigCodeBench/895")),
))
RECORD_TYPE = "PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_REVIEW_NOT_PARTITION_APPROVAL"
REPORT_TYPE = "PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION"


class TaskPolicyError(RuntimeError):
    """Refuse a task before any generation, candidate execution, or model call."""


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TaskPolicyError(f"Missing or unreadable required audit file: {path}") from exc
    if not isinstance(data, dict):
        raise TaskPolicyError(f"Invalid audit JSON object: {path}")
    return data


def _load_verified_policy_batch1(root: Path) -> tuple[dict, frozenset[str]]:
    """Validate current manifest, all public hashes and review provenance.

    No caching: a later in-session edit cannot reuse an earlier authorization.
    """
    root = Path(root).resolve()
    try:
        tasks, manifest, current_hashes = load_and_verify(root)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise TaskPolicyError(f"Public/manifest verification failed: {exc}") from exc

    review = _json(root / REVIEW_REL)
    report = _json(root / REPORT_REL)
    if review.get("schema_version") != 1 or review.get("record_type") != RECORD_TYPE:
        raise TaskPolicyError("Unrecognized manual-review schema or type")
    if report.get("report_type") != REPORT_TYPE:
        raise TaskPolicyError("Unrecognized source lexical-audit report")
    if review.get("input_sha256") != current_hashes or report.get("input_sha256") != current_hashes:
        raise TaskPolicyError("STALE REVIEW: source dataset or split manifest hashes changed")
    if review.get("lexical_report_path") != str(REPORT_REL):
        raise TaskPolicyError("Manual review refers to an unexpected lexical report")
    if review.get("lexical_report_sha256") != sha256_file(root / REPORT_REL):
        raise TaskPolicyError("STALE REVIEW: lexical report hash changed")
    if report.get("all_public_task_count") != len(tasks) or len(tasks) != 3333:
        raise TaskPolicyError("Unexpected task count or incomplete lexical report")
    if manifest.get("status") not in (DRAFT_STATUS, "frozen"):
        raise TaskPolicyError("Unknown or unsupported manifest status")
    if review.get("manifest_status_at_review") != DRAFT_STATUS:
        raise TaskPolicyError("Unexpected original manual-review manifest status")
    if review.get("execution_authorized") is not False or review.get("final_split_freeze_authorized") is not False:
        raise TaskPolicyError("Review is not a valid provisional-only record")
    if review.get("reviewed_pair_count") != 6:
        raise TaskPolicyError("Incomplete manual review")
    pairs = review.get("pairs")
    if not isinstance(pairs, list) or len(pairs) != 6:
        raise TaskPolicyError("Missing or incomplete reviewed pairs")
    pair_keys = []
    paired_development_ids = set()
    manifest_rows = manifest.get("tasks", {})
    for row in pairs:
        if not isinstance(row, dict):
            raise TaskPolicyError("Malformed reviewed pair")
        a, b, partner = row.get("task_a"), row.get("task_b"), row.get("proposed_quarantine_task")
        if not all(isinstance(x, str) for x in (a, b, partner)) or partner not in (a, b):
            raise TaskPolicyError("Malformed reviewed pair IDs")
        key = frozenset((a, b))
        if len(key) != 2:
            raise TaskPolicyError("A reviewed pair cannot refer to the same task twice")
        pair_keys.append(key)
        paired_development_ids.add(partner)
        if row.get("review_status") != "provisional_public_specification_review":
            raise TaskPolicyError("Review contains non-provisional verdict")
        if row.get("proposed_action") != "quarantine_development_partner_pending_group_split_decision":
            raise TaskPolicyError("Unexpected reviewed-pair action")
        # Verify pair was development vs another partition at review time.
        parts = {row.get("partition_a"), row.get("partition_b")}
        if "development" not in parts or len(parts) != 2:
            raise TaskPolicyError("Unexpected reviewed-pair partition relationship")
        current = manifest_rows.get(partner)
        if not isinstance(current, dict) or current.get("partition") != "development":
            raise TaskPolicyError("Reviewed development partner has moved; re-review before use")
    if frozenset(pair_keys) != KNOWN_PAIRS or len(pair_keys) != len(KNOWN_PAIRS):
        raise TaskPolicyError("Reviewed pair identities changed unexpectedly")
    q = review.get("quarantine")
    if not isinstance(q, dict) or q.get("status") != "proposed_not_enforced":
        raise TaskPolicyError("Unexpected provisional quarantine schema")
    actual = q.get("development_task_ids")
    if (not isinstance(actual, list) or not all(isinstance(x, str) for x in actual)
            or len(actual) != len(set(actual))):
        raise TaskPolicyError("Invalid quarantined ID list")
    ids = frozenset(actual)
    if ids != KNOWN_BATCH1_QUARANTINE or ids != frozenset(paired_development_ids):
        raise TaskPolicyError("Quarantine task IDs do not match the reviewed six pairs")
    return manifest, ids


# phase2d-quarantine-policy-v2
BATCH2_REL = Path("results/phase2d/global_overlap_audit_v1/manual_review_batch2.json")
BATCH2_RECORD_TYPE = "PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_BATCH2_NOT_PARTITION_APPROVAL"
KNOWN_BATCH2_QUARANTINE = frozenset((
    "MBPP/439", "MBPP/933", "MBPP/43", "MBPP/178", "MBPP/970", "MBPP/569", "MBPP/595",
))
KNOWN_BATCH2_PAIRS = {
    frozenset(("MBPP/439", "MBPP/673")): ("development", "held_out", "MBPP/439"),
    frozenset(("MBPP/933", "MBPP/965")): ("development", "held_out", "MBPP/933"),
    frozenset(("MBPP/16", "MBPP/43")): ("held_out", "development", "MBPP/43"),
    frozenset(("MBPP/178", "MBPP/186")): ("development", "held_out", "MBPP/178"),
    frozenset(("MBPP/440", "MBPP/584")): ("validation", "held_out", None),
    frozenset(("MBPP/404", "MBPP/970")): ("held_out", "development", "MBPP/970"),
    frozenset(("MBPP/104", "MBPP/569")): ("validation", "development", "MBPP/569"),
    frozenset(("MBPP/595", "MBPP/699")): ("development", "held_out", "MBPP/595"),
}
KNOWN_QUARANTINE = KNOWN_BATCH1_QUARANTINE | KNOWN_BATCH2_QUARANTINE


def _load_verified_policy_batch2(root: Path) -> tuple[dict, frozenset[str]]:
    """Verify both reviews, their provenance, and all thirteen exclusions.

    The older six-pair review is always validated first, unchanged. After
    batch 2 is installed, missing or stale batch-2 evidence blocks ALL tasks.
    """
    root = Path(root).resolve()
    manifest, batch1 = _load_verified_policy_batch1(root)
    second = _json(root / BATCH2_REL)
    first = _json(root / REVIEW_REL)
    report = _json(root / REPORT_REL)
    if second.get("schema_version") != 1 or second.get("record_type") != BATCH2_RECORD_TYPE:
        raise TaskPolicyError("Unrecognized batch-2 manual review")
    if second.get("input_sha256") != first.get("input_sha256"):
        raise TaskPolicyError("STALE REVIEW: batch-2 source hash mismatch")
    if second.get("manifest_status_at_review") != DRAFT_STATUS:
        raise TaskPolicyError("Unexpected batch-2 manifest status")
    if (second.get("first_review_path") != str(REVIEW_REL)
            or second.get("first_review_sha256") != sha256_file(root / REVIEW_REL)):
        raise TaskPolicyError("STALE REVIEW: batch-1 evidence changed")
    if (second.get("lexical_report_path") != str(REPORT_REL)
            or second.get("lexical_report_sha256") != sha256_file(root / REPORT_REL)):
        raise TaskPolicyError("STALE REVIEW: batch-2 lexical report changed")
    if second.get("execution_authorized") is not False or second.get("final_split_freeze_authorized") is not False:
        raise TaskPolicyError("Batch-2 review must remain provisional")
    if second.get("reviewed_pair_count") != 8:
        raise TaskPolicyError("Incomplete batch-2 review count")
    rows = second.get("pairs")
    if not isinstance(rows, list) or len(rows) != 8:
        raise TaskPolicyError("Missing or incomplete batch-2 review")
    expected_score = {}
    for row in report.get("cross_partition_review_queue", []):
        key = frozenset((row.get("task_a"), row.get("task_b")))
        if key in KNOWN_BATCH2_PAIRS:
            if key in expected_score:
                raise TaskPolicyError("Repeated lexical review pair")
            expected_score[key] = row
    if set(expected_score) != set(KNOWN_BATCH2_PAIRS):
        raise TaskPolicyError("Batch-2 pair absent from original lexical queue")
    seen = set()
    partners = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TaskPolicyError("Malformed batch-2 pair")
        a, b = row.get("task_a"), row.get("task_b")
        if not isinstance(a, str) or not isinstance(b, str) or a == b:
            raise TaskPolicyError("Malformed batch-2 pair task IDs")
        key = frozenset((a, b))
        if key not in KNOWN_BATCH2_PAIRS or key in seen:
            raise TaskPolicyError("Unexpected or duplicate batch-2 pair")
        seen.add(key)
        expected_a, expected_b, expected_dev = KNOWN_BATCH2_PAIRS[key]
        # Check orientation independently of the unordered pair key.
        if (a, b) == ("MBPP/440", "MBPP/584"):
            pass
        elif (a, b) not in (
            ("MBPP/439", "MBPP/673"), ("MBPP/933", "MBPP/965"),
            ("MBPP/16", "MBPP/43"), ("MBPP/178", "MBPP/186"),
            ("MBPP/404", "MBPP/970"), ("MBPP/104", "MBPP/569"),
            ("MBPP/595", "MBPP/699"),
        ):
            raise TaskPolicyError("Batch-2 pair orientation changed")
        if (row.get("partition_a"), row.get("partition_b")) != (expected_a, expected_b):
            raise TaskPolicyError("Batch-2 partitions changed")
        for task_id, expected_partition, hash_key in (
            (a, expected_a, "normalized_prompt_sha256_a"),
            (b, expected_b, "normalized_prompt_sha256_b"),
        ):
            entry = manifest.get("tasks", {}).get(task_id)
            if (not isinstance(entry, dict) or entry.get("partition") != expected_partition
                    or entry.get("public_prompt_sha256") != row.get(hash_key)):
                raise TaskPolicyError("Batch-2 task partition or prompt digest changed")
        score = expected_score[key]
        if (row.get("lexical_weighted_jaccard") != score.get("lexical_weighted_jaccard")
                or row.get("char_5gram_jaccard") != score.get("char_5gram_jaccard")):
            raise TaskPolicyError("Batch-2 similarity evidence changed")
        if row.get("review_status") != "provisional_public_specification_review":
            raise TaskPolicyError("Unexpected batch-2 review status")
        if expected_dev:
            if (row.get("proposed_quarantine_task") != expected_dev
                    or row.get("proposed_action") != "quarantine_development_partner_pending_group_split_decision"):
                raise TaskPolicyError("Batch-2 quarantine target changed")
            partners.add(expected_dev)
        elif (row.get("proposed_quarantine_task") is not None
              or row.get("proposed_action") != "watchlist_validation_heldout_pending_group_split_decision"):
            raise TaskPolicyError("Validation/held-out watchlist changed")
    if seen != set(KNOWN_BATCH2_PAIRS) or partners != set(KNOWN_BATCH2_QUARANTINE):
        raise TaskPolicyError("Incomplete batch-2 quarantine evidence")
    q = second.get("quarantine")
    if (not isinstance(q, dict) or q.get("status") != "proposed_not_enforced"
            or q.get("development_task_ids") != sorted(KNOWN_BATCH2_QUARANTINE)
            or q.get("validation_heldout_watchlist") != [["MBPP/440", "MBPP/584"]]):
        raise TaskPolicyError("Batch-2 quarantine/watchlist mismatch")
    if batch1 != KNOWN_BATCH1_QUARANTINE:
        raise TaskPolicyError("First batch quarantine changed")
    return manifest, KNOWN_BATCH1_QUARANTINE | KNOWN_BATCH2_QUARANTINE



# phase2d-quarantine-policy-v3: all previous reviews are still validated first.
from phase2d_record_manual_overlap_batch3 import (
    BATCH3_REL, SUMMARY_REL, PRIORITY_REL, RECORD_TYPE as BATCH3_RECORD_TYPE,
    PAIRS as EXPECTED_BATCH3_METADATA, QUARANTINE as KNOWN_BATCH3_QUARANTINE,
    WATCH as KNOWN_BATCH3_WATCH,
)
import csv

KNOWN_QUARANTINE = KNOWN_BATCH1_QUARANTINE | KNOWN_BATCH2_QUARANTINE | KNOWN_BATCH3_QUARANTINE


def load_verified_policy(root: Path) -> tuple[dict, frozenset[str]]:
    """Fail closed unless ALL THREE original review records validate unchanged."""
    root = Path(root).resolve()
    manifest, old_ids = _load_verified_policy_batch2(root)
    if old_ids != KNOWN_BATCH1_QUARANTINE | KNOWN_BATCH2_QUARANTINE:
        raise TaskPolicyError('Earlier quarantine set changed')
    first = _json(root / REVIEW_REL)
    second = _json(root / BATCH2_REL)
    third = _json(root / BATCH3_REL)
    summary = _json(root / SUMMARY_REL)
    if third.get('schema_version') != 1 or third.get('record_type') != BATCH3_RECORD_TYPE:
        raise TaskPolicyError('Unexpected batch-3 review type')
    if third.get('input_sha256') != first.get('input_sha256') or third.get('input_sha256') != second.get('input_sha256'):
        raise TaskPolicyError('STALE REVIEW: batch-3 source hashes differ')
    if third.get('manifest_status_at_review') != DRAFT_STATUS:
        raise TaskPolicyError('Batch-3 was not created under draft manifest')
    for label,rel,key in (
        ('first',REVIEW_REL,'first_review_sha256'),
        ('second',BATCH2_REL,'second_review_sha256'),
        ('lexical',REPORT_REL,'lexical_report_sha256'),
        ('stratified',SUMMARY_REL,'stratified_summary_sha256'),
        ('priority',PRIORITY_REL,'priority_csv_sha256'),
    ):
        pathkey = {'first':'first_review_path', 'second':'second_review_path',
                   'lexical':'lexical_report_path','stratified':'stratified_summary_path',
                   'priority':'priority_csv_path'}[label]
        if third.get(pathkey) != str(rel) or third.get(key) != sha256_file(root / rel):
            raise TaskPolicyError(f'STALE REVIEW: batch-3 {label} evidence changed')
    if (third.get('execution_authorized') is not False
            or third.get('final_split_freeze_authorized') is not False
            or third.get('manifest_modified') is not False):
        raise TaskPolicyError('Batch-3 review must remain provisional and non-executing')
    if (summary.get('report_type') != 'PUBLIC_STRATIFIED_LEXICAL_REVIEW_QUEUE_NOT_DUPLICATE_VERDICTS'
            or summary.get('input_sha256') != third['input_sha256']
            or summary.get('original_report_sha256') != third['lexical_report_sha256']
            or summary.get('manual_review_sha256') != {
                str(REVIEW_REL): third['first_review_sha256'],
                str(BATCH2_REL): third['second_review_sha256']}
            or summary.get('priority_census_count') != 14
            or summary.get('already_manually_reviewed') != 14):
        raise TaskPolicyError('STALE REVIEW: priority population or source provenance changed')
    rows = third.get('pairs')
    if not isinstance(rows, list) or len(rows) != 14 or third.get('reviewed_pair_count') != 14:
        raise TaskPolicyError('Incomplete batch-3 manual review')
    # Prevent a new record from silently removing or relabeling a known pair.
    if len(EXPECTED_BATCH3_METADATA) != 14:
        raise TaskPolicyError('Unexpected built-in batch-3 policy')
    for actual, expected in zip(rows, EXPECTED_BATCH3_METADATA):
        a,b,pa,pb,score,verdict,dev,_,_ = expected
        if ((actual.get('task_a'),actual.get('task_b'),actual.get('partition_a'),
             actual.get('partition_b'),actual.get('verdict'),actual.get('proposed_quarantine_task'))
            != (a,b,pa,pb,verdict,dev)):
            raise TaskPolicyError('Batch-3 review pair identity, verdict or action changed')
        if actual.get('review_status') != 'provisional_public_specification_review':
            raise TaskPolicyError('Batch-3 review was not provisional')
        expected_action = ('quarantine_development_partner_pending_group_split_decision' if dev
                           else 'watchlist_validation_heldout_pending_group_split_decision')
        if actual.get('proposed_action') != expected_action:
            raise TaskPolicyError('Batch-3 pair proposed action changed')
        for ident,part,key in ((a,pa,'normalized_prompt_sha256_a'),
                               (b,pb,'normalized_prompt_sha256_b')):
            item = manifest.get('tasks',{}).get(ident)
            if not isinstance(item,dict) or item.get('partition') != part or item.get('public_prompt_sha256') != actual.get(key):
                raise TaskPolicyError('Batch-3 task prompt hash or partition changed')
        if abs(float(actual.get('lexical_weighted_jaccard',-100))-score)>0.000002:
            raise TaskPolicyError('Batch-3 lexical score changed')
    q=third.get('quarantine')
    if (not isinstance(q,dict) or q.get('status') != 'proposed_not_enforced'
            or q.get('development_task_ids') != sorted(KNOWN_BATCH3_QUARANTINE)
            or q.get('validation_heldout_watchlist') != [list(pair) for pair in KNOWN_BATCH3_WATCH]):
        raise TaskPolicyError('Batch-3 quarantine/watchlist mismatch')
    return manifest, KNOWN_QUARANTINE


def require_task_permission(root: Path, task_id: str, intent: str) -> str:
    """Authorize only appropriately partitioned tasks; refuse quarantined tasks.

    intent: 'generate' or 'evaluate'.  Read-only review operations should not
    call this function. This is an application guard, not an OS security sandbox.
    """
    if intent not in ("generate", "evaluate"):
        raise TaskPolicyError(f"Unknown task intent: {intent!r}")
    if not isinstance(task_id, str) or not task_id:
        raise TaskPolicyError("Nonempty task ID required")
    manifest, excluded = load_verified_policy(root)
    if task_id in excluded:
        raise TaskPolicyError(f"QUARANTINED: {task_id} cannot be used for iterative {intent}; "
                              "see provisional manual_review.json")
    entry = manifest.get("tasks", {}).get(task_id)
    if not isinstance(entry, dict) or entry.get("partition") != "development":
        raise TaskPolicyError(f"BLOCKED: {task_id} is not assigned to development")
    status = manifest.get("status")
    if status == DRAFT_STATUS and task_id not in PILOT_TASKS:
        raise TaskPolicyError(f"BLOCKED: {task_id} requires a frozen/re-reviewed split; "
                              "the manifest is still draft")
    return f"Allowed {intent}: {task_id} under {status} manifest; quarantine validated"
