"""Offline tests for conservative Batch-4 triage; no candidate execution."""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from phase2d_global_overlap_audit import normalized_prompt, sha256_text
from phase2d_batch4_policy_triage import (
    analyze, write_report, PreflightError, DEFAULT_SAMPLE, DEFAULT_REVIEW,
    PRIORITY_REVIEW, SECONDARY_REVIEW,
)

ROOT=Path(__file__).resolve().parents[1]


def synthetic_loader(root):
    with (root/DEFAULT_SAMPLE).open(encoding='utf-8',newline='') as f:
        rows=list(csv.DictReader(f))
    tasks={}
    for r in rows:
        for side in 'ab':
            tid=r['task_'+side]
            partition=r['partition_'+side]
            if tid in tasks and tasks[tid]['partition']!=partition:
                raise ValueError('Bad synthetic manifest')
            tasks[tid]={'partition':partition,'public_prompt_sha256':sha256_text(normalized_prompt(r['prompt_'+side]))}
    return ({'status':'draft_requires_review_and_freeze','tasks':tasks},
            frozenset('simulated-v3-id-'+str(i) for i in range(21)),
            frozenset(('HumanEval/0','HumanEval/1','MBPP/545')))


class Batch4TriageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert (ROOT/DEFAULT_SAMPLE).is_file(), 'Needs exact Batch4 original sample CSV'
        assert (ROOT/DEFAULT_REVIEW).is_file(), 'Needs provisional Batch4 review JSON'

    def evaluate(self, sample=DEFAULT_SAMPLE, review=DEFAULT_REVIEW, loader=synthetic_loader):
        return analyze(ROOT,sample_rel=sample,review_rel=review,policy_loader=loader)

    def changed_review(self, change):
        d=json.loads((ROOT/DEFAULT_REVIEW).read_text(encoding='utf-8'))
        change(d)
        temp=tempfile.TemporaryDirectory()
        path=Path(temp.name)/'review.json'
        path.write_text(json.dumps(d),encoding='utf-8')
        self.addCleanup(temp.cleanup)
        return path

    def changed_sample(self, change):
        source=(ROOT/DEFAULT_SAMPLE).read_text(encoding='utf-8')
        temp=tempfile.TemporaryDirectory()
        path=Path(temp.name)/'sample.csv'
        path.write_text(change(source),encoding='utf-8')
        self.addCleanup(temp.cleanup)
        return path

    def test_full_81_pair_review_verified(self):
        a=self.evaluate();self.assertEqual(a['report']['batch4_new_development_review_candidates'],21)
    def test_priority_13_secondary_8(self):
        a=self.evaluate();self.assertEqual(len(PRIORITY_REVIEW),13);self.assertEqual(len(SECONDARY_REVIEW),8)
        c={x['review_priority']:0 for x in a['development']}
        for x in a['development']:c[x['review_priority']]+=1
        self.assertEqual(c['priority_independent_review'],13)
        self.assertEqual(c['secondary_independent_review'],8)
    def test_dev_ids_all_unique(self):
        d=[x['development_task'] for x in self.evaluate()['development']]
        self.assertEqual(len(set(d)),21)
    def test_pilot_is_flagged_not_deleted(self):
        a=self.evaluate()
        self.assertEqual([r['development_task'] for r in a['development'] if r['pilot_exception']=='yes'],['HumanEval/1'])
        self.assertEqual(a['report']['pilot_reporting_restriction']['related_held_out'],'HumanEval/6')
    def test_non_development_watch_14(self):
        self.assertEqual(len(self.evaluate()['nondevelopment']),14)
    def test_two_equivalence_watch_pairs(self):
        eq=[x for x in self.evaluate()['nondevelopment'] if x['initial_verdict']=='equivalent']
        self.assertEqual(len(eq),2)
    def test_only_one_ambiguous(self):
        self.assertEqual(self.evaluate()['ambiguous'],[['MBPP/707','MBPP/903']])
    def test_guard_unmodified_by_review(self):
        path=ROOT/'phase2d_quarantine_guard.py'
        before=hashlib.sha256(path.read_bytes()).digest() if path.exists() else None
        self.evaluate()
        after=hashlib.sha256(path.read_bytes()).digest() if path.exists() else None
        self.assertEqual(before,after)
    def test_changed_source_fails_closed(self):
        path=self.changed_sample(lambda x:x.replace('BigCodeBench/204','BigCodeBench/9999',1))
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(sample=path)
    def test_modified_review_note_fails_closed(self):
        path=self.changed_review(lambda d:d['reviews'][0].update(review_notes='Different reasoning here'))
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(review=path)
    def test_changed_verdict_fails_closed(self):
        path=self.changed_review(lambda d:d['reviews'][0].update(manual_verdict='equivalent'))
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(review=path)
    def test_tampered_development_hold_list_fails(self):
        path=self.changed_review(lambda d:d['proposed_development_task_review_holds'].remove('HumanEval/1'))
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(review=path)
    def test_changed_pilot_review_action_fails(self):
        path=self.changed_review(lambda d:d['reviews'][33].update(risk_action='no_new_quarantine_proposed'))
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(review=path)
    def test_changed_watchlist_fails(self):
        path=self.changed_review(lambda d:d['watchlist_cross_non_development_pairs'].pop())
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(review=path)
    def test_changed_contract_fails(self):
        path=self.changed_review(lambda d:d['needs_contract_review_pairs'].clear())
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(review=path)
    def test_changed_partition_in_manifest_fails(self):
        def bad_policy(root):
            manifest, excluded, pilots=synthetic_loader(root)
            manifest['tasks']['HumanEval/1']={'partition':'held_out'}
            return manifest,excluded,pilots
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(loader=bad_policy)
    def test_changed_v3_active_quarantines_fails(self):
        def bad_policy(root):
            manifest,excluded,pilots=synthetic_loader(root)
            return manifest,frozenset(('x',)),pilots
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(loader=bad_policy)
    def test_changed_existing_pilot_permissions_fails(self):
        def bad_policy(root):
            manifest,excluded,pilots=synthetic_loader(root)
            return manifest,excluded,frozenset(('HumanEval/0','MBPP/545'))
        with self.assertRaises((PreflightError,ValueError)):self.evaluate(loader=bad_policy)
    def test_read_only_does_not_write_source_or_review(self):
        files=[ROOT/DEFAULT_SAMPLE,ROOT/DEFAULT_REVIEW]
        before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
        self.evaluate()
        self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in files])
    def test_export_exclusive_directory_and_four_files(self):
        a=self.evaluate()
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)/'triage'
            write_report(d,a)
            self.assertEqual(len(list(d.iterdir())),4)
            with self.assertRaises(FileExistsError):write_report(d,a)
    def test_no_automatic_execution_or_manifest_approval(self):
        r=self.evaluate()['report']
        self.assertFalse(r['execution_authorized'])
        self.assertFalse(r['final_split_freeze_authorized'])
        self.assertFalse(r['v3_guard_modified'])


if __name__=='__main__':unittest.main()
