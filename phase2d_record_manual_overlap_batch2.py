#!/usr/bin/env python3
"""Audit and optionally create the SECOND batch of provisional public-prompt overlap reviews.

Default is READ ONLY. --write uses exclusive creation; NEVER modifies splits,
existing batch-1 review, generated candidates, or any trusted/private tests.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import re
from pathlib import Path
import sys

from phase2d_global_overlap_audit import load_and_verify, sha256_file

ROOT = Path(__file__).resolve().parent
REPORT_REL = Path('results/phase2d/global_overlap_audit_v1/global_overlap_report.json')
BATCH1_REL = Path('results/phase2d/global_overlap_audit_v1/manual_review.json')
BATCH2_REL = Path('results/phase2d/global_overlap_audit_v1/manual_review_batch2.json')
DRAFT = 'draft_requires_review_and_freeze'
RECORD_TYPE = 'PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_BATCH2_NOT_PARTITION_APPROVAL'

# Public prompts were supplied by the researcher in their terminal transcript.
# Ratings are conservatively provisional. Official MBPP tests were NOT consulted.
# Each string is a SOURCE EXCERPT checked case-insensitively in a local public prompt.
PAIRS = (
    dict(a='MBPP/439', b='MBPP/673', pa='development', pb='held_out',
         ea='multiple_to_single', eb='convert',
         a_text='convert a list of multiple integers into a single integer',
         b_text='convert a list of multiple integers into a single integer',
         verdict='likely_equivalent_public_specification', dev='MBPP/439',
         evidence='Both convert a list of integers into one integer; function names differ.',
         limitation='Leading zeros, negative values and exact return contract need public-example/official-contract review.'),
    dict(a='MBPP/933', b='MBPP/965', pa='development', pb='held_out',
         ea='camel_to_snake', eb='camel_to_snake',
         a_text='convert camel case string to snake case string',
         b_text='convert camel case string to snake case string',
         verdict='near_equivalent_solution_transfer', dev='MBPP/933',
         evidence='Same camel-to-snake conversion and entry point; one explicitly requires regex.',
         limitation='Edge-case behavior and potential regex methodology distinction not verified.'),
    dict(a='MBPP/16', b='MBPP/43', pa='held_out', pb='development',
         ea='text_lowercase_underscore', eb='text_match',
         a_text='sequences of lowercase letters joined with an underscore',
         b_text='sequences of lowercase letters joined with an underscore',
         verdict='near_equivalent_solution_transfer', dev='MBPP/43',
         evidence='Same lowercase-underscore sequence recognition task; regex specified in one.',
         limitation='Regex match semantics, returned value and boundaries need review.'),
    dict(a='MBPP/178', b='MBPP/186', pa='development', pb='held_out',
         ea='string_literals', eb='check_literals',
         a_text='search some literals strings in a string',
         b_text='search some literals strings in a string',
         verdict='needs_contract_review', dev='MBPP/178',
         evidence='Both search literal strings; one explicitly requires regex.',
         limitation='Matching interpretation and output contract unspecified.'),
    dict(a='MBPP/440', b='MBPP/584', pa='validation', pb='held_out',
         ea='find_adverb_position', eb='find_adverbs',
         a_text='find all adverbs and their positions',
         b_text='find all adverbs and their positions',
         verdict='near_equivalent_solution_transfer', dev=None,
         evidence='Same adverb-and-position extraction goal; regex required in one.',
         limitation='Adverb definition and returned index/format uncertain. Validation/held-out transfer risk.'),
    dict(a='MBPP/404', b='MBPP/970', pa='held_out', pb='development',
         ea='minimum', eb='min_of_two',
         a_text='find the minimum of two numbers',
         b_text='find minimum of two numbers',
         verdict='likely_equivalent_public_specification', dev='MBPP/970',
         evidence='Both compute the minimum of two numbers; function identifiers differ.',
         limitation='Allowed input types and tie details not verified.'),
    dict(a='MBPP/104', b='MBPP/569', pa='validation', pb='development',
         ea='sort_sublists', eb='sort_sublists',
         a_text='sort each sublist of strings',
         b_text='sort each sublist of strings',
         verdict='near_equivalent_solution_transfer', dev='MBPP/569',
         evidence='Same sorting objective and function name; lambda method explicit in one.',
         limitation='Mutation/copy behavior and return format not fully verified.'),
    dict(a='MBPP/595', b='MBPP/699', pa='development', pb='held_out',
         ea='min_Swaps', eb='min_Swaps',
         a_text='minimum number of swaps required to convert one binary string to another',
         b_text='minimum number of swaps required to convert one binary string to another',
         verdict='likely_equivalent_public_specification', dev='MBPP/595',
         evidence='Same entry point and minimum-swap binary-string transformation objective.',
         limitation='Swap adjacency, impossibility and duplicate-character semantics not verified.'),
)

QUARANTINE = frozenset(p['dev'] for p in PAIRS if p['dev'])
WATCH = frozenset({frozenset(('MBPP/440','MBPP/584'))})
EXPECTED = frozenset(frozenset((p['a'],p['b'])) for p in PAIRS)


def matches_public_excerpt(task_id: str, expected_fragment: str, prompt: str) -> bool:
    """Exact excerpt check with one documented upstream whitespace typo.

    MBPP/699's prepared public prompt may spell "toanother" without a space.
    Normalize only this specific known variant, while the pre-existing
    manifest/source hashes independently enforce exact public-data identity.
    """
    if not isinstance(prompt, str):
        return False
    actual = " ".join(prompt.casefold().split())
    expected = " ".join(expected_fragment.casefold().split())
    if task_id == "MBPP/699":
        actual = re.sub(r"\btoanother\b", "to another", actual)
        expected = re.sub(r"\btoanother\b", "to another", expected)
    return expected in actual


def json_object(path: Path) -> dict:
    with path.open(encoding='utf-8') as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return data


def build(root: Path) -> dict:
    root = Path(root).resolve()
    tasks, manifest, hashes = load_and_verify(root)
    if manifest.get('status') != DRAFT:
        raise ValueError('Manifest must remain draft; refusing review creation')
    task_map = {t.task_id:t for t in tasks}
    report = json_object(root / REPORT_REL)
    first = json_object(root / BATCH1_REL)
    if report.get('report_type') != 'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION':
        raise ValueError('Unrecognized global lexical report')
    if report.get('all_public_task_count') != 3333 or report.get('input_sha256') != hashes:
        raise ValueError('Global report is stale or invalid')
    if first.get('record_type') != 'PROVISIONAL_PUBLIC_SPECIFICATION_OVERLAP_REVIEW_NOT_PARTITION_APPROVAL':
        raise ValueError('Unexpected first batch review type')
    if first.get('input_sha256') != hashes or first.get('reviewed_pair_count') != 6:
        raise ValueError('First batch review stale or incomplete')
    if first.get('lexical_report_sha256') != sha256_file(root / REPORT_REL):
        raise ValueError('First batch lexical evidence changed')
    if first.get('execution_authorized') is not False or first.get('final_split_freeze_authorized') is not False:
        raise ValueError('First review is not provisional')
    queue = {}
    for row in report.get('cross_partition_review_queue', []):
        key = frozenset((row['task_a'], row['task_b']))
        if key in queue:
            raise ValueError('Repeated pair in lexical queue')
        queue[key] = row
    # The global report's top-200 queue contains the eight requested pairs.
    public = {}
    for line in (root / 'data/public/mbpp.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            public[row['task_id']] = row
    records = []
    for p in PAIRS:
        left, right = task_map[p['a']], task_map[p['b']]
        key = frozenset((p['a'], p['b']))
        if key not in queue:
            raise ValueError(f'Pair not found in exported cross-partition queue: {p["a"]}, {p["b"]}')
        if (left.partition,right.partition) != (p['pa'],p['pb']):
            raise ValueError(f'Partition mismatch: {p["a"]}, {p["b"]}')
        if left.partition == right.partition:
            raise ValueError('Not a cross-partition pair')
        for label,entry,expected_entry,expected_fragment in (
            ('a',p['a'],p['ea'],p['a_text']),('b',p['b'],p['eb'],p['b_text'])
        ):
            row = public.get(entry)
            if not row or row.get('entry_point') != expected_entry:
                raise ValueError(f'Public entry point mismatch: {entry}')
            if not matches_public_excerpt(entry, expected_fragment, row.get('prompt') or ''):
                raise ValueError(f'Public prompt changed: {entry}')
        if p['dev'] is not None and task_map[p['dev']].partition != 'development':
            raise ValueError('Development quarantine task changed partition')
        if p['dev'] is None and {left.partition,right.partition} != {'validation','held_out'}:
            raise ValueError('Expected validation/held-out watchlist pair')
        source = queue[key]
        records.append(dict(
            task_a=p['a'], task_b=p['b'], partition_a=left.partition,
            partition_b=right.partition, entry_point_a=p['ea'],entry_point_b=p['eb'],
            normalized_prompt_sha256_a=left.normalized_hash,
            normalized_prompt_sha256_b=right.normalized_hash,
            lexical_weighted_jaccard=source['lexical_weighted_jaccard'],
            char_5gram_jaccard=source['char_5gram_jaccard'],
            verdict=p['verdict'], evidence_from_public_prompts=p['evidence'],
            limitations=p['limitation'],
            review_status='provisional_public_specification_review',
            proposed_action=('quarantine_development_partner_pending_group_split_decision'
                             if p['dev'] else 'watchlist_validation_heldout_pending_group_split_decision'),
            proposed_quarantine_task=p['dev'], manifest_changed=False,
            enforcement_installed=False,
        ))
    counts = Counter(r['verdict'] for r in records)
    return dict(
        schema_version=1, record_type=RECORD_TYPE,
        review_date='2026-11-13',
        review_origin='manual comparison of eight supplied PUBLIC prompt specifications',
        review_provenance='User-provided public prompts; official tests and model outputs not consulted',
        manifest_status_at_review=DRAFT,
        input_sha256=hashes, lexical_report_path=str(REPORT_REL),
        lexical_report_sha256=sha256_file(root / REPORT_REL),
        first_review_path=str(BATCH1_REL),
        first_review_sha256=sha256_file(root / BATCH1_REL),
        reviewed_pair_count=len(records), verdict_counts=dict(sorted(counts.items())),
        pairs=records,
        quarantine=dict(status='proposed_not_enforced',
                        development_task_ids=sorted(QUARANTINE),
                        validation_heldout_watchlist=[['MBPP/440','MBPP/584']]),
        research_caveats=[
            'No full official benchmark tests or trusted reference programs were accessed.',
            'The equivalence/transfer verdicts are provisional based only on public prompts.',
            'Do not use quarantined development partners for generation, repair, or controller training.',
            'The validation-to-held-out pair requires group-level split review; validation and held-out usage remain blocked by the task guard.',
            'This record does not change manifest partitions or grant execution permission.',
        ],
        manifest_modified=False,execution_authorized=False,final_split_freeze_authorized=False,
    )


def create_new(path: Path, data: dict) -> None:
    if not path.parent.is_dir():
        raise FileNotFoundError('Existing review directory required')
    with path.open('x', encoding='utf-8') as fh:
        json.dump(data,fh,indent=2,sort_keys=True,ensure_ascii=False)
        fh.write('\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=ROOT)
    ap.add_argument('--write',action='store_true')
    ns=ap.parse_args(argv)
    try:
        data = build(ns.root)
        print('AUDIT VERIFIED: 3,333 public tasks and eight cross-partition review leads')
        print('MANIFEST:',data['manifest_status_at_review'])
        print('VERDICTS:',data['verdict_counts'])
        print('PROPOSED NEW DEVELOPMENT EXCLUSIONS:',', '.join(sorted(QUARANTINE)))
        print('VALIDATION/HELD-OUT WATCHLIST: MBPP/440 <-> MBPP/584')
        out=Path(ns.root).resolve()/BATCH2_REL
        if ns.write:
            create_new(out,data)
            print('CREATED:',out)
            print('No data, manifest, candidates, or first-batch review modified.')
        else:
            print('READ-ONLY VERIFIED. To create second review:',out,'using --write')
        return 0
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError) as ex:
        print('FAILED CLOSED:',ex,file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
