#!/usr/bin/env python3
"""Read-only adjudication preflight for Phase 2D's provisional Batch-4 overlaps.

Does not approve a split, change the task permission policy, or execute candidates.
The only write mode creates a fresh output directory with provisional reports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

DEFAULT_SAMPLE = Path('results/phase2d/global_overlap_stratified_v1/random_stratified_review.csv')
DEFAULT_REVIEW = Path('results/phase2d/global_overlap_stratified_v1/manual_review_batch4_provisional.json')
DEFAULT_OUT = Path('results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1')
SUMMARY = Path('results/phase2d/global_overlap_stratified_v1/stratified_overlap_summary.json')
DRAFT = 'draft_requires_review_and_freeze'

# First-pass risk priorities, NOT authoritative semantic-duplicate judgments.
# Each of these IDs is the *development* side of a reviewed cross-partition pair.
PRIORITY_REVIEW = frozenset((
    'BigCodeBench/506', 'BigCodeBench/608', 'BigCodeBench/426',
    'BigCodeBench/812', 'HumanEval/1', 'HumanEval/85',
    'MBPP/66', 'MBPP/503', 'MBPP/784', 'MBPP/457',
    'MBPP/25', 'MBPP/497', 'MBPP/79',
))
SECONDARY_REVIEW = frozenset((
    'BigCodeBench/753', 'BigCodeBench/3', 'BigCodeBench/288',
    'BigCodeBench/417', 'BigCodeBench/730', 'MBPP/696',
    'MBPP/287', 'MBPP/436',
))
EXPECTED_WATCH_EQUIVALENT = frozenset((
    frozenset(('HumanEval/59', 'MBPP/32')),
    frozenset(('MBPP/263', 'MBPP/821')),
))
EXPECTED_CONTRACT = frozenset(('MBPP/707', 'MBPP/903'))
VERDICTS = {
    'equivalent': 2, 'near_equivalent': 33, 'related_distinct': 22,
    'unrelated': 23, 'needs_contract_review': 1,
}
SOURCE_TYPE = 'PROVISIONAL_STRATIFIED_PUBLIC_PROMPT_REVIEW_NOT_SPLIT_APPROVAL'
# Pin the exact previously verified public-source review; changing it requires a new revision.
REVIEW_SHA256 = '84b0e2e541a075c151e6f742bd21267b34410f6000eb8032f9019693e570d84f'
SAMPLE_SHA256 = '48a98d45721a40f9da34b31572dbc82cd3e22b2e21d59ef9cba807669d3c5462'
OUTPUT_TYPE = 'PROVISIONAL_BATCH4_POLICY_TRIAGE_NOT_SPLIT_OR_EXECUTION_APPROVAL'


class PreflightError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise PreflightError(f'Expected JSON object: {path}')
    return obj


def review_verifier(root: Path):
    # The same verifier shipped and used with the original Batch 4 review.
    path = root / 'phase2d_stratified_review_batch4/phase2d_verify_sample_review_batch4.py'
    if not path.is_file():
        raise PreflightError('Missing original Batch-4 source verifier: ' + str(path))
    import importlib.util
    spec = importlib.util.spec_from_file_location('batch4_original_source_verifier', path)
    if not spec or not spec.loader:
        raise PreflightError('Cannot import Batch-4 source verifier')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify


def analyze(root: Path, sample_rel=DEFAULT_SAMPLE, review_rel=DEFAULT_REVIEW, policy_loader=None) -> dict:
    root = root.resolve()
    sample = root / sample_rel
    review = root / review_rel
    summary_path = root / SUMMARY
    if not all(x.is_file() for x in (sample, review, summary_path)):
        raise PreflightError('Required Batch-4 CSV/review or sampling summary missing')
    doc = load_json(review)
    if doc.get('record_type') != SOURCE_TYPE or doc.get('schema_version') != 1:
        raise PreflightError('Unrecognized provisional Batch-4 review schema')
    if doc.get('reviewed_pairs') != 81 or doc.get('num_strata') != 34 or doc.get('verdict_counts') != VERDICTS:
        raise PreflightError('Unexpected Batch-4 sample or verdict counts')
    if sha256(review) != REVIEW_SHA256:
        raise PreflightError('STALE REVIEW: saved Batch-4 provisional judgments changed; re-review required')
    if sha256(sample) != SAMPLE_SHA256 or sha256(sample) != doc.get('source_file_sha256'):
        raise PreflightError('STALE SOURCE: sample bytes differ from recorded Batch-4 source')
    # Verify every row, prompt hash, score, stratum and review note before triage.
    result = review_verifier(root)(sample, review, strict_file_hash=True)
    if result['pairs'] != 81 or result['strata'] != 34:
        raise PreflightError('Original Batch-4 verifier disagrees with expected counts')
    sampling = load_json(summary_path)
    if sampling.get('report_type') != 'PUBLIC_STRATIFIED_LEXICAL_REVIEW_QUEUE_NOT_DUPLICATE_VERDICTS':
        raise PreflightError('Unexpected stratified sampling provenance')
    if sampling.get('priority_census_count') != 14 or sampling.get('already_manually_reviewed') != 14:
        raise PreflightError('Original sampled population was not the reviewed Batch-4 frame')

    # V3 verifies all 3333 public tasks, their hashes, the draft manifest,
    # original 3 manual-review records, and existing 21 quarantines.
    if policy_loader is None:
        import phase2d_quarantine_guard as guard
        manifest, active = guard.load_verified_policy(root)
        pilots = set(guard.PILOT_TASKS)
    else:
        # Test-only injection; CLI always uses the installed V3 guard.
        manifest, active, pilots = policy_loader(root)
    if manifest.get('status') != DRAFT:
        raise PreflightError('Draft split status changed: re-review before policy triage')
    if len(active) != 21 or 'HumanEval/1' in active:
        raise PreflightError('Unexpected currently installed V3 quarantine policy')
    if set(pilots) != {'HumanEval/0', 'HumanEval/1', 'MBPP/545'}:
        raise PreflightError('Historical pilot policy changed')
    manifest_rows = manifest.get('tasks', {})

    from phase2d_global_overlap_audit import normalized_prompt, sha256_text
    with sample.open(encoding='utf-8', newline='') as stream:
        source_rows = list(csv.DictReader(stream))
    rows = doc.get('reviews')
    if not isinstance(rows, list) or len(rows) != 81:
        raise PreflightError('Missing Batch-4 pair reviews')
    developer = []
    nondev = []
    ambiguous = []
    all_pairs = set()
    for r, source_row in zip(rows, source_rows):
        a,b = r['task_a'],r['task_b']
        key = frozenset((a,b))
        if len(key) != 2 or key in all_pairs:
            raise PreflightError('Duplicate or self-matched reviewed pair')
        all_pairs.add(key)
        for tid, partition, side in ((a,r['partition_a'],'a'), (b,r['partition_b'],'b')):
            item=manifest_rows.get(tid,{})
            if item.get('partition') != partition:
                raise PreflightError(f'Split for {tid} has changed since Batch-4 review')
            digest=sha256_text(normalized_prompt(source_row['prompt_'+side]))
            if item.get('public_prompt_sha256') != digest:
                raise PreflightError(f'Public prompt hash for {tid} disagrees with the verified manifest')
        verdict = r['manual_verdict']
        pa,pb = r['partition_a'],r['partition_b']
        action = r['risk_action']
        if verdict in ('near_equivalent','equivalent') and 'development' in (pa,pb):
            if action != 'proposed_quarantine_review':
                raise PreflightError(f'Unrecorded development overlap action: {a}, {b}')
            dev = a if pa=='development' else b
            tier = ('priority_independent_review' if dev in PRIORITY_REVIEW else
                    'secondary_independent_review' if dev in SECONDARY_REVIEW else None)
            if tier is None:
                raise PreflightError(f'Unexpected development overlap ID: {dev}')
            developer.append({
                'review_index': r['review_index'], 'development_task':dev,
                'task_a':a,'task_b':b,'partition_a':pa,'partition_b':pb,
                'initial_verdict':verdict, 'review_priority':tier,
                'pilot_exception': 'yes' if dev=='HumanEval/1' else 'no',
                'evidence_note':r['review_notes'],
                'action':'SECOND_REVIEW_REQUIRED_NO_GUARD_CHANGE',
            })
        elif verdict in ('near_equivalent','equivalent') and 'development' not in (pa,pb):
            if action != 'partition_watchlist':
                raise PreflightError(f'Watchlist action changed: {a}, {b}')
            nondev.append({
                'review_index':r['review_index'], 'task_a':a,'task_b':b,
                'partition_a':pa,'partition_b':pb,'initial_verdict':verdict,
                'evidence_note':r['review_notes'],
                'action':'HOLD_FOR_GROUP_SPLIT_REVIEW_NOT_GUARD_QUARANTINE',
            })
        elif verdict == 'needs_contract_review':
            if action != 'needs_human_contract_review' or key != EXPECTED_CONTRACT:
                raise PreflightError('Unexpected unresolved contract case')
            ambiguous.append([a,b])
        elif action != 'no_new_quarantine_proposed':
            raise PreflightError(f'Non-overlap pair has unsupported action: {a}, {b}')

    ids = [r['development_task'] for r in developer]
    if set(ids) != PRIORITY_REVIEW | SECONDARY_REVIEW or len(ids) != 21 or len(set(ids)) != 21:
        raise PreflightError('Unexpected development task review-hold set')
    if sorted(ids) != sorted(doc.get('proposed_development_task_review_holds', [])):
        raise PreflightError('Development hold summary differs from pair evidence')
    if len(nondev) != 14 or set(map(frozenset,doc.get('watchlist_cross_non_development_pairs',[]))) != {frozenset((r['task_a'],r['task_b'])) for r in nondev}:
        raise PreflightError('Non-development watchlist differs from review evidence')
    if {frozenset((r['task_a'],r['task_b'])) for r in nondev if r['initial_verdict']=='equivalent'} != EXPECTED_WATCH_EQUIVALENT:
        raise PreflightError('Equivalent pair watchlist changed')
    if ambiguous != doc.get('needs_contract_review_pairs'):
        raise PreflightError('Unresolved-contract identity changed')
    if set(ids) & set(active):
        raise PreflightError('Batch-4 review IDs already collide with existing V3 quarantine list; re-triage')

    # Structural caveat: this is one provisional reviewer, not independent adjudication.
    report = {
        'record_type':OUTPUT_TYPE,
        'schema_version':1,
        'state':'provisional_second_review_not_completed',
        'execution_authorized':False,
        'final_split_freeze_authorized':False,
        'v3_guard_modified':False,
        'input_sha256':{
            str(sample_rel):sha256(sample),
            str(review_rel):sha256(review),
            str(SUMMARY):sha256(summary_path),
        },
        'manifest_status':manifest['status'],
        'active_v3_quarantined_development_tasks':len(active),
        'batch4_new_development_review_candidates':len(ids),
        'priority_independent_review':len(PRIORITY_REVIEW),
        'secondary_independent_review':len(SECONDARY_REVIEW),
        'cross_non_development_watchlist_pairs':len(nondev),
        'unresolved_contract_pairs':len(ambiguous),
        'original_review_verdict_counts':VERDICTS,
        'source_sampling_strata':34,
        'sampling_frame_limitations':[
          '81 of the 4607 non-priority screened lexical candidates were sampled across 34 strata; 14 priority and 14 previously reviewed pairs are separate, not part of this random sample.',
          'Priority tiers are subjective triage, not independent reviewer agreement or confirmed semantic equivalence.',
          'No claim about unscreened pairs, pretraining contamination, or true held-out generalization is supported.',
        ],
        'pilot_reporting_restriction':{
            'development_pilot':'HumanEval/1',
            'related_held_out':'HumanEval/6',
            'rule':'Keep prior pilot artifacts for provenance; do not count HumanEval/6 as independent evidence for changes developed or tuned using HumanEval/1 until adjudicated.',
            'scope':'experimental reporting only; existing guard permissions unchanged',
        },
        'recommended_next_gate':'Independent second review of 13 priority cases; adjudicate 8 secondary cases and 14 validation/held-out overlaps; then decide split grouping and task exclusions before freezing.',
    }
    return {'report':report, 'development':developer, 'nondevelopment':nondev, 'ambiguous':ambiguous}


def write_report(outdir: Path, analysis: dict) -> None:
    # Export is opt-in and exclusive: never overwrite previous evidence or outputs.
    outdir.mkdir(parents=True, exist_ok=False)
    (outdir/'batch4_policy_triage_summary.json').write_text(json.dumps(analysis['report'], indent=2,sort_keys=True)+'\n',encoding='utf-8')
    for fname, items in (
        ('development_second_review_queue.csv', analysis['development']),
        ('validation_heldout_watchlist.csv', analysis['nondevelopment']),
    ):
        with (outdir/fname).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
    (outdir/'pilot_generalization_notice.txt').write_text(
        'PROVISIONAL PUBLIC-PROMPT OVERLAP: HumanEval/1 (existing development pilot) and HumanEval/6 (held out) share a nested-parentheses parsing subroutine.\n'
        'Historic HumanEval/1 work is retained and labeled exploratory. Do not claim independent generalization to HumanEval/6 based on tuning that used HumanEval/1, until a second reviewer and split grouping decision are recorded.\n'
        'This notice changes no guard permission, split, or candidate.\n', encoding='utf-8'
    )


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--source',type=Path,default=DEFAULT_SAMPLE)
    p.add_argument('--review',type=Path,default=DEFAULT_REVIEW)
    p.add_argument('--export-dir',type=Path,help='Create a NEW report directory only (exclusive; never overwrite)')
    a=p.parse_args(argv)
    root=a.root.resolve()
    sys.path.insert(0,str(root))
    try:
        analysis=analyze(root,a.source,a.review)
        r=analysis['report']
        print('BATCH4 POLICY TRIAGE PASSED -- PROVISIONAL')
        print('V3 EXISTING QUARANTINES:',r['active_v3_quarantined_development_tasks'])
        print('NEW DEVELOPMENT REVIEW CANDIDATES:',r['batch4_new_development_review_candidates'])
        print('PRIORITY SECOND REVIEW:',r['priority_independent_review'])
        print('SECONDARY SECOND REVIEW:',r['secondary_independent_review'])
        print('VALIDATION/HELD-OUT WATCHLIST:',r['cross_non_development_watchlist_pairs'])
        print('UNRESOLVED CONTRACT:',r['unresolved_contract_pairs'])
        print('PILOT GENERALIZATION FLAG: HumanEval/1 vs HumanEval/6')
        print('GUARD/MANIFEST CHANGES: NONE')
        if a.export_dir is not None:
            path=a.export_dir if a.export_dir.is_absolute() else root/a.export_dir
            write_report(path,analysis)
            print('CREATED NEW REPORT DIRECTORY:',path)
    except (OSError,ValueError,KeyError,TypeError,PreflightError,ImportError) as exc:
        print('BATCH4 POLICY TRIAGE FAILED CLOSED:',exc,file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':
    raise SystemExit(main())
