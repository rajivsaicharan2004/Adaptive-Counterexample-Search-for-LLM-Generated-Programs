"""Synthetic-only Batch 3 and shared guard regression tests. No candidate execution."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from phase2d_quarantine_v3_fixture import make_fixture,dump_json
from phase2d_record_manual_overlap_batch3 import (
    BATCH1_REL, BATCH2_REL, BATCH3_REL, PRIORITY_REL, SUMMARY_REL,
    QUARANTINE, WATCH, build, create_new,
)
from phase2d_quarantine_guard import KNOWN_QUARANTINE, PILOT_TASKS, TaskPolicyError, require_task_permission

class V3GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        make_fixture(cls.root)
        cls.paths=[cls.root/p for p in (BATCH1_REL,BATCH2_REL,BATCH3_REL,PRIORITY_REL,SUMMARY_REL)]
        cls.original={p:p.read_bytes() for p in cls.paths}
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()
    def tearDown(self):
        for p,data in self.original.items():
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(data)
    def modify(self,path,func):
        data=json.loads(path.read_text(encoding='utf-8'))
        func(data)
        dump_json(path,data)
    def assert_fails(self,needle):
        with self.assertRaisesRegex(TaskPolicyError,needle):
            require_task_permission(self.root,'HumanEval/0','evaluate')

    def test_batch3_record_matches_current_public_evidence(self):
        rec=build(self.root)
        self.assertEqual(rec['reviewed_pair_count'],14)
        self.assertEqual(len(rec['pairs']),14)
        self.assertEqual(len(rec['quarantine']['development_task_ids']),8)
        self.assertEqual(len(rec['quarantine']['validation_heldout_watchlist']),6)
    def test_record_is_exclusive_and_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):
            create_new(self.root/BATCH3_REL,build(self.root))
    def test_all_twentyone_quarantine_tasks_block_both_intents(self):
        self.assertEqual(len(KNOWN_QUARANTINE),21)
        self.assertEqual(len(QUARANTINE),8)
        for task in KNOWN_QUARANTINE:
            for intent in ('generate','evaluate'):
                with self.subTest(task=task,intent=intent):
                    with self.assertRaisesRegex(TaskPolicyError,'QUARANTINED'):
                        require_task_permission(self.root,task,intent)
    def test_existing_pilots_eligible(self):
        self.assertEqual(len(PILOT_TASKS),3)
        for task in PILOT_TASKS:
            self.assertIn('Allowed',require_task_permission(self.root,task,'evaluate'))
    def test_bcb854_still_blocked_in_draft(self):
        with self.assertRaisesRegex(TaskPolicyError,'still draft'):
            require_task_permission(self.root,'BigCodeBench/854','generate')
    def test_six_watchlist_pairs_remain_non_development(self):
        self.assertEqual(len(WATCH),6)
        for a,b in WATCH:
            for task in (a,b):
                with self.assertRaisesRegex(TaskPolicyError,'not assigned to development'):
                    require_task_permission(self.root,task,'evaluate')
    def test_missing_third_review_fails_closed(self):
        (self.root/BATCH3_REL).unlink()
        self.assert_fails('Missing or unreadable')
    def test_removed_quarantine_id_fails_closed(self):
        self.modify(self.root/BATCH3_REL,lambda d:d['quarantine']['development_task_ids'].pop())
        self.assert_fails('quarantine/watchlist mismatch')
    def test_changed_verdict_fails_closed(self):
        self.modify(self.root/BATCH3_REL,lambda d:d['pairs'][0].__setitem__('verdict','equivalent'))
        self.assert_fails('pair identity, verdict or action')
    def test_changed_watchlist_fails_closed(self):
        self.modify(self.root/BATCH3_REL,lambda d:d['quarantine'].__setitem__('validation_heldout_watchlist',[]))
        self.assert_fails('quarantine/watchlist mismatch')
    def test_third_review_source_hash_tamper_fails_closed(self):
        self.modify(self.root/BATCH3_REL,lambda d:d['input_sha256'].__setitem__('data/public/mbpp.jsonl','0'*64))
        self.assert_fails('STALE REVIEW')
    def test_first_review_change_fails_closed(self):
        self.modify(self.root/BATCH1_REL,lambda d:d.__setitem__('extra','unexpected'))
        self.assert_fails('STALE REVIEW')
    def test_second_review_change_fails_closed(self):
        self.modify(self.root/BATCH2_REL,lambda d:d.__setitem__('extra','unexpected'))
        self.assert_fails('STALE REVIEW')
    def test_priority_csv_change_fails_closed(self):
        path=self.root/PRIORITY_REL
        path.write_text(path.read_text()+'\n',encoding='utf-8')
        self.assert_fails('STALE REVIEW')
    def test_stratified_summary_change_fails_closed(self):
        self.modify(self.root/SUMMARY_REL,lambda d:d.__setitem__('extra','unexpected'))
        self.assert_fails('STALE REVIEW')
    def test_execution_permission_must_remain_false(self):
        self.modify(self.root/BATCH3_REL,lambda d:d.__setitem__('execution_authorized',True))
        self.assert_fails('provisional')
    def test_batch3_task_identity_change_fails_closed(self):
        self.modify(self.root/BATCH3_REL,lambda d:d['pairs'][0].__setitem__('task_b','MBPP/synthetic_not_real'))
        self.assert_fails('pair identity')

if __name__=='__main__':
    unittest.main()
