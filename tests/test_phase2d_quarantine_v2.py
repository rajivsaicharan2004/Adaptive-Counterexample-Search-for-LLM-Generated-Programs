"""Synthetic-only tests for batch-2 review and v2 guard. No code candidates."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from phase2d_global_overlap_audit import DATASETS, sha256_file, normalized_prompt
from phase2d_record_manual_overlap_batch2 import PAIRS, QUARANTINE, BATCH2_REL, REPORT_REL, BATCH1_REL, build, create_new, matches_public_excerpt

V2_PATH = Path(__file__).resolve().parent.parent / 'phase2d_v2_sources' / 'phase2d_quarantine_guard.py'
spec=importlib.util.spec_from_file_location('_guard_v2_under_test',V2_PATH)
v2=importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)


from phase2d_quarantine_v2_fixture import make_fixture as make_v2_fixture, dump_json


class V2GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        make_v2_fixture(cls.root)
        cls.batch2=cls.root/BATCH2_REL
        cls.data=build(cls.root)
        cls.original=cls.batch2.read_bytes()
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def tearDown(self):self.batch2.write_bytes(self.original)

    def test_mbpp699_known_typo_and_find_wording_accepted(self):
        needle = 'minimum number of swaps required to convert one binary string to another'
        variants = (
            'Write a python function to find the minimum number of swaps required to convert one binary string toanother.',
            'Write a python function to find the minimum number of swaps required to convert one binary string to another.',
            'Write a python function to count minimum number of swaps required to convert one binary string to another.',
        )
        for prompt in variants:
            with self.subTest(prompt=prompt):
                self.assertTrue(matches_public_excerpt('MBPP/699', needle, prompt))

    def test_mbpp699_semantic_change_rejected(self):
        needle = 'minimum number of swaps required to convert one binary string to another'
        self.assertFalse(matches_public_excerpt('MBPP/699', needle,
            'Find the minimum number of replacements required to convert one binary string toanother.'))
        self.assertFalse(matches_public_excerpt('MBPP/699', needle,
            'Find the maximum number of swaps required to convert one binary string toanother.'))
        self.assertFalse(matches_public_excerpt('MBPP/699', needle,
            'Find the minimum number of swaps required to convert one binary string to a third string.'))

    def test_typo_normalization_is_task_specific(self):
        needle = 'minimum number of swaps required to convert one binary string to another'
        prompt = 'Find the minimum number of swaps required to convert one binary string toanother.'
        self.assertFalse(matches_public_excerpt('MBPP/595', needle, prompt))

    def test_realistic_mbpp699_public_prompt_passes_full_review(self):
        import hashlib
        from phase2d_global_overlap_audit import DATASETS
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            make_v2_fixture(root)
            path = root / 'data/public/mbpp.jsonl'
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
            example = ('Write a python function to find the minimum number of swaps '
                       'required to convert one binary string toanother.')
            changed = 0
            for row in rows:
                if row['task_id'] == 'MBPP/699':
                    row['prompt'] = example
                    changed += 1
            self.assertEqual(changed, 1)
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
            manifest_path = root / 'results/phase2d/splits.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['tasks']['MBPP/699']['public_prompt_sha256'] = hashlib.sha256(
                normalized_prompt(example).encode()
            ).hexdigest()
            dump_json(manifest_path, manifest)
            hashes = {str(path.relative_to(root)): sha256_file(path)
                      for path in [manifest_path]+[root/'data/public'/f'{name}.jsonl' for name in DATASETS]}
            report = json.loads((root/REPORT_REL).read_text(encoding='utf-8'))
            report['input_sha256'] = hashes
            dump_json(root/REPORT_REL, report)
            first = json.loads((root/BATCH1_REL).read_text(encoding='utf-8'))
            first['input_sha256'] = hashes
            first['lexical_report_sha256'] = sha256_file(root/REPORT_REL)
            dump_json(root/BATCH1_REL, first)
            record = build(root)
            self.assertEqual(record['reviewed_pair_count'], 8)
            self.assertEqual(len(record['quarantine']['development_task_ids']), 7)

    def test_synthetic_record_created_and_no_overwrite(self):
        self.assertEqual(len(self.data['pairs']),8)
        self.assertEqual(len(self.data['quarantine']['development_task_ids']),7)
        with self.assertRaises(FileExistsError):
            create_new(self.batch2,self.data)

    def test_total_thirteen_tasks_blocked_both_intents(self):
        self.assertEqual(len(v2.KNOWN_QUARANTINE),13)
        for task_id in v2.KNOWN_QUARANTINE:
            for intent in ('generate','evaluate'):
                with self.subTest(task=task_id,intent=intent):
                    with self.assertRaisesRegex(v2.TaskPolicyError,'QUARANTINED'):
                        v2.require_task_permission(self.root,task_id,intent)

    def test_three_existing_pilots_remain_allowed(self):
        for task in v2.PILOT_TASKS:
            self.assertIn('Allowed',v2.require_task_permission(self.root,task,'generate'))
            self.assertIn('Allowed',v2.require_task_permission(self.root,task,'evaluate'))

    def test_bcb854_remains_blocked_while_draft(self):
        with self.assertRaisesRegex(v2.TaskPolicyError,'still draft'):
            v2.require_task_permission(self.root,'BigCodeBench/854','evaluate')

    def test_validation_heldout_pair_blocked_not_misclassified_as_dev(self):
        for task in ('MBPP/440','MBPP/584'):
            with self.assertRaisesRegex(v2.TaskPolicyError,'not assigned to development'):
                v2.require_task_permission(self.root,task,'evaluate')

    def test_missing_second_review_fails_closed(self):
        self.batch2.unlink()
        try:
            with self.assertRaisesRegex(v2.TaskPolicyError,'Missing or unreadable'):
                v2.require_task_permission(self.root,'HumanEval/0','evaluate')
        finally:
            self.batch2.write_bytes(self.original)

    def test_second_review_missing_quarantine_id_fails_closed(self):
        obj=json.loads(self.original)
        obj['quarantine']['development_task_ids'].pop()
        dump_json(self.batch2,obj)
        with self.assertRaisesRegex(v2.TaskPolicyError,'mismatch'):
            v2.require_task_permission(self.root,'HumanEval/0','evaluate')

    def test_second_review_pair_replacement_fails_closed(self):
        obj=json.loads(self.original)
        obj['pairs'][0]['task_b']='MBPP/synthetic_999'
        dump_json(self.batch2,obj)
        with self.assertRaisesRegex(v2.TaskPolicyError,'Unexpected or duplicate'):
            v2.require_task_permission(self.root,'HumanEval/0','evaluate')

    def test_second_review_watchlist_tamper_fails_closed(self):
        obj=json.loads(self.original)
        obj['quarantine']['validation_heldout_watchlist']=[]
        dump_json(self.batch2,obj)
        with self.assertRaisesRegex(v2.TaskPolicyError,'watchlist mismatch'):
            v2.require_task_permission(self.root,'HumanEval/0','evaluate')

    def test_second_review_source_hash_tamper_fails_closed(self):
        obj=json.loads(self.original)
        obj['input_sha256']['data/public/mbpp.jsonl']='0'*64
        dump_json(self.batch2,obj)
        with self.assertRaisesRegex(v2.TaskPolicyError,'STALE REVIEW'):
            v2.require_task_permission(self.root,'HumanEval/0','evaluate')

    def test_second_review_first_batch_hash_tamper_fails_closed(self):
        obj=json.loads(self.original)
        obj['first_review_sha256']='0'*64
        dump_json(self.batch2,obj)
        with self.assertRaisesRegex(v2.TaskPolicyError,'STALE REVIEW'):
            v2.require_task_permission(self.root,'HumanEval/0','evaluate')

    def test_second_review_rejects_unauthorized_execution(self):
        obj=json.loads(self.original)
        obj['execution_authorized']=True
        dump_json(self.batch2,obj)
        with self.assertRaisesRegex(v2.TaskPolicyError,'provisional'):
            v2.require_task_permission(self.root,'HumanEval/0','evaluate')


if __name__=='__main__':unittest.main()
