#!/usr/bin/env python3
"""Read-only-by-default Batch 3 public-prompt review recorder. No candidate execution.

Reads the 14-item stratified priority census, source public prompts and audit files;
--write exclusively creates a provisional review JSON (never edits prior reviews).
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
import json
from pathlib import Path
import sys

from phase2d_global_overlap_audit import load_and_verify, sha256_file

ROOT = Path(__file__).resolve().parent
BASE = Path('results/phase2d/global_overlap_audit_v1')
STRAT = Path('results/phase2d/global_overlap_stratified_v1')
REPORT_REL = BASE / 'global_overlap_report.json'
BATCH1_REL = BASE / 'manual_review.json'
BATCH2_REL = BASE / 'manual_review_batch2.json'
BATCH3_REL = BASE / 'manual_review_batch3.json'
SUMMARY_REL = STRAT / 'stratified_overlap_summary.json'
PRIORITY_REL = STRAT / 'priority_manual_review.csv'
DRAFT = 'draft_requires_review_and_freeze'
RECORD_TYPE = 'PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_BATCH3_NOT_PARTITION_APPROVAL'

# Exact public-prompt pairs and human interpretations from the November 13 review.
# These are provisional transfer-risk judgments, not official-test verdicts.
# tuple: a, b, partition_a, partition_b, score, verdict, suggested dev quarantine, evidence, caveat
PAIRS = (
 ('MBPP/362','MBPP/658','validation','held_out',.881577,'likely_equivalent_public_specification',None,'Both return an item having maximum frequency in a list.','Tie behavior and output type need contract review.'),
 ('MBPP/591','MBPP/625','development','held_out',.758341,'likely_equivalent_public_specification','MBPP/591','Both interchange first and last list elements.','Length-0/1 and in-place mutation semantics remain unverified.'),
 ('MBPP/174','MBPP/653','validation','held_out',.726468,'near_equivalent_solution_transfer',None,'Both group key-value pairs into dictionary lists, one explicitly using collections.','Ordering and defaults unverified.'),
 ('MBPP/49','MBPP/154','held_out','development',.710959,'needs_contract_review','MBPP/154','Both extract a specified element from 2D lists; one has an explicit first-element default.','Default index, errors, shape and output type unresolved.'),
 ('BigCodeBench/349','BigCodeBench/351','validation','held_out',.703853,'near_equivalent_solution_transfer',None,'Same randomized pandas sales-report workflow with range configuration and labels.','Different function signatures and random generation requirements.'),
 ('MBPP/420','MBPP/504','held_out','development',.703539,'near_equivalent_solution_transfer','MBPP/504','Sum cubes over even natural numbers versus all natural numbers.','Different function values; direct evaluation transfer not claimed.'),
 ('MBPP/170','MBPP/649','development','held_out',.702122,'likely_equivalent_public_specification','MBPP/170','Both sum list elements across an index range.','Index endpoint convention needs review.'),
 ('MBPP/402','MBPP/952','development','validation',.673768,'likely_equivalent_public_specification','MBPP/402','nCr % p is the same mathematical operation as nCr mod p.','Handling invalid n/r/p not verified.'),
 ('MBPP/145','MBPP/763','validation','held_out',.673501,'related_but_distinct',None,'Maximum versus minimum pairwise difference are distinct functions.','Similar input shape; potential solution-template transfer but not duplicate.'),
 ('MBPP/505','MBPP/632','validation','held_out',.659391,'likely_equivalent_public_specification',None,'Both move all zeroes to sequence end.','Mutation and order of other elements need checking.'),
 ('MBPP/191','MBPP/762','validation','held_out',.657289,'near_equivalent_solution_transfer',None,'Both determine whether a month has 30 days, with names versus numbers.','Different input representation and edge cases.'),
 ('MBPP/271','MBPP/549','development','held_out',.655261,'near_equivalent_solution_transfer','MBPP/271','Fifth powers of first n even versus odd natural numbers.','Different numerical function despite transferable structure.'),
 ('MBPP/634','MBPP/770','held_out','development',.652937,'near_equivalent_solution_transfer','MBPP/770','Fourth powers of first n even versus odd natural numbers.','Different numerical function despite transferable structure.'),
 ('MBPP/120','MBPP/409','validation','development',.652859,'near_equivalent_solution_transfer','MBPP/409','Maximum versus minimum product of tuple pairs.','Distinct objective and possible tie behavior.'),
)
KNOWN_PAIRS = frozenset(frozenset((r[0],r[1])) for r in PAIRS)
QUARANTINE = frozenset(r[6] for r in PAIRS if r[6])
WATCH = tuple(sorted((r[0],r[1])) for r in PAIRS if r[6] is None)
assert len(KNOWN_PAIRS) == len(PAIRS) == 14
assert len(QUARANTINE) == 8 and len(WATCH) == 6


def _json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return data


def build(root: Path) -> dict:
    root = Path(root).resolve()
    tasks, manifest, hashes = load_and_verify(root)
    if len(tasks) != 3333 or manifest.get('status') != DRAFT:
        raise ValueError('Requires original 3333 tasks and unchanged draft manifest')
    public = {t.task_id: t for t in tasks}
    report = _json(root / REPORT_REL)
    if (report.get('report_type') != 'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION'
            or report.get('input_sha256') != hashes or report.get('all_public_task_count') != 3333):
        raise ValueError('Global lexical report is stale or unexpected')
    report_sha = sha256_file(root / REPORT_REL)
    reviews = {}
    for rel, count in ((BATCH1_REL, 6), (BATCH2_REL, 8)):
        doc = _json(root / rel)
        if (doc.get('input_sha256') != hashes or doc.get('lexical_report_sha256') != report_sha
                or doc.get('reviewed_pair_count') != count
                or doc.get('manifest_status_at_review') != DRAFT
                or doc.get('execution_authorized') is not False
                or doc.get('final_split_freeze_authorized') is not False):
            raise ValueError(f'Prior review is stale or invalid: {rel}')
        reviews[str(rel)] = sha256_file(root / rel)
    summary = _json(root / SUMMARY_REL)
    if (summary.get('report_type') != 'PUBLIC_STRATIFIED_LEXICAL_REVIEW_QUEUE_NOT_DUPLICATE_VERDICTS'
            or summary.get('manifest_status') != DRAFT
            or summary.get('input_sha256') != hashes
            or summary.get('original_report_sha256') != report_sha
            or summary.get('manual_review_sha256') != reviews
            or summary.get('already_manually_reviewed') != 14
            or summary.get('priority_census_count') != 14):
        raise ValueError('Stratified summary is stale, missing or inconsistent')
    # The priority CSV is a human-review artifact; match its full public prompts
    # against hash-verified dataset data. No test cases or code are accessed.
    with (root / PRIORITY_REL).open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 14:
        raise ValueError('Expected exactly 14 priority-lead rows')
    queue = {}
    for row in rows:
        key = frozenset((row.get('task_a'), row.get('task_b')))
        if len(key) != 2 or key in queue:
            raise ValueError('Repeated or malformed priority pair')
        queue[key] = row
    if set(queue) != KNOWN_PAIRS:
        raise ValueError('Unexpected priority pair identities: refuse review')
    out = []
    for a,b,pa,pb,score,verdict,dev,evidence,caveat in PAIRS:
        left, right = public[a], public[b]
        if (left.partition, right.partition) != (pa,pb):
            raise ValueError(f'Unexpected partitions for {a}, {b}')
        if dev and public[dev].partition != 'development':
            raise ValueError('Quarantine partner no longer development')
        row = queue[frozenset((a,b))]
        if row['task_a'] != a or row['task_b'] != b:
            raise ValueError(f'Unexpected priority pair order for {a}, {b}')
        if row['partition_a'] != pa or row['partition_b'] != pb:
            raise ValueError('Priority partition mismatch')
        if row['prompt_a'] != left.prompt or row['prompt_b'] != right.prompt:
            raise ValueError(f'Priority prompt differs from hashed public record: {a}, {b}')
        actual = float(row['lexical_weighted_jaccard'])
        if abs(actual - score) > 0.000002:
            raise ValueError(f'Priority lexical score changed: {a}, {b}')
        out.append(dict(task_a=a,task_b=b,partition_a=pa,partition_b=pb,
                        normalized_prompt_sha256_a=left.normalized_hash,
                        normalized_prompt_sha256_b=right.normalized_hash,
                        lexical_weighted_jaccard=actual,
                        char_5gram_jaccard=float(row['char_5gram_jaccard']),
                        verdict=verdict,evidence_from_public_prompts=evidence,
                        limitations=caveat,review_status='provisional_public_specification_review',
                        proposed_quarantine_task=dev,
                        proposed_action=('quarantine_development_partner_pending_group_split_decision'
                                         if dev else 'watchlist_validation_heldout_pending_group_split_decision'),
                        manifest_changed=False,enforcement_installed=False))
    counts = Counter(row['verdict'] for row in out)
    return dict(schema_version=1, record_type=RECORD_TYPE,
                review_date=str(date(2026,11,13)),
                review_origin='Manual review of 14 stratified-priority public specifications',
                review_provenance='Researcher-provided public prompts; official tests not consulted',
                input_sha256=hashes,manifest_status_at_review=DRAFT,
                lexical_report_path=str(REPORT_REL),lexical_report_sha256=report_sha,
                first_review_path=str(BATCH1_REL),first_review_sha256=reviews[str(BATCH1_REL)],
                second_review_path=str(BATCH2_REL),second_review_sha256=reviews[str(BATCH2_REL)],
                stratified_summary_path=str(SUMMARY_REL),stratified_summary_sha256=sha256_file(root/SUMMARY_REL),
                priority_csv_path=str(PRIORITY_REL),priority_csv_sha256=sha256_file(root/PRIORITY_REL),
                reviewed_pair_count=14,verdict_counts=dict(sorted(counts.items())),pairs=out,
                quarantine=dict(status='proposed_not_enforced',development_task_ids=sorted(QUARANTINE),
                                validation_heldout_watchlist=[list(pair) for pair in WATCH]),
                research_caveats=[
                    'No authoritative test contracts or hidden/private tests were accessed.',
                    'Likely-equivalent and near-equivalent verdicts are provisional public-specification judgments.',
                    'The 81 sampled leads are not yet manually reviewed.',
                    'A lexical audit cannot establish the absence of semantic duplicates outside the retrieved pool.',
                    'This record does not authorize execution or change splits.',
                ],manifest_modified=False,execution_authorized=False,
                final_split_freeze_authorized=False)


def create_new(path: Path, record: dict) -> None:
    if not path.parent.is_dir():
        raise FileNotFoundError(f'Review output directory does not exist: {path.parent}')
    with path.open('x',encoding='utf-8') as stream:
        json.dump(record, stream,indent=2,sort_keys=True,ensure_ascii=False)
        stream.write('\n')


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--write',action='store_true')
    args=parser.parse_args(argv)
    try:
        obj=build(args.root)
        print('VERIFIED: 3,333 public tasks, 14 existing review pairs, 14 priority leads')
        print('MANIFEST:',obj['manifest_status_at_review'])
        print('VERDICTS:',obj['verdict_counts'])
        print('PROPOSED NEW QUARANTINES:',', '.join(obj['quarantine']['development_task_ids']))
        print('WATCHLIST VALIDATION/HELD-OUT:',len(obj['quarantine']['validation_heldout_watchlist']))
        path=args.root.resolve()/BATCH3_REL
        if args.write:
            create_new(path,obj)
            print('CREATED:',path)
        else:
            print('READ-ONLY VERIFIED; use --write for exclusive creation:',path)
        print('No manifest, datasets, candidates, or earlier review files changed.')
        return 0
    except (ValueError,TypeError,KeyError,OSError,json.JSONDecodeError) as exc:
        print('FAILED CLOSED:',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
