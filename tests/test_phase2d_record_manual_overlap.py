import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import phase2d_record_manual_overlap as module


class ReviewRecordTests(unittest.TestCase):
    def test_six_distinct_pairs_and_targets(self):
        self.assertEqual(len(module.REVIEWS), 6)
        self.assertEqual(len({frozenset((r['a'], r['b'])) for r in module.REVIEWS}), 6)
        self.assertEqual(len({r['development_task'] for r in module.REVIEWS}), 6)
        self.assertEqual({r['verdict'] for r in module.REVIEWS},
                         {'equivalent_public_specification', 'near_equivalent_solution_transfer', 'needs_contract_review'})

    def test_provisional_and_non_enforcing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Use minimal synthetic data with a mocked public input loader. Does
            # not read source datasets or execute any candidate program.
            from types import SimpleNamespace
            fake_tasks = []
            public = {}
            for item in module.REVIEWS:
                for side in ('a', 'b'):
                    key = item[side]
                    if key not in public:
                        body = ' '.join(item['text_' + side])
                        public[key] = {'task_id': key, 'entry_point': item['entry_' + side],
                                       'prompt': body, 'starter_code': ''}
                        fake_tasks.append(SimpleNamespace(task_id=key, partition=item['partition_' + side],
                            normalized_hash='sha-' + key))
            report_path = root / module.REPORT_REL
            report_path.parent.mkdir(parents=True)
            queue = []
            for item in module.REVIEWS:
                queue.append({'task_a': item['a'], 'task_b': item['b'],
                              'lexical_weighted_jaccard': .73, 'char_5gram_jaccard': .77})
            report = {'report_type': 'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION',
                      'all_public_task_count': len(fake_tasks),
                      'input_sha256': {'a': 'b'}, 'cross_partition_review_queue': queue}
            report_path.write_text(json.dumps(report), encoding='utf-8')
            with patch.object(module, 'load_and_verify', return_value=(fake_tasks,
                 {'status': module.EXPECTED_STATUS}, {'a': 'b'})), \
                 patch.object(module, 'load_public_details', return_value=public):
                result = module.build_record(root)
                self.assertEqual(result['reviewed_pair_count'], 6)
                self.assertFalse(result['manifest_modified'])
                self.assertFalse(result['execution_authorized'])
                self.assertEqual(result['quarantine']['status'], 'proposed_not_enforced')
                self.assertEqual(result['verdict_counts']['needs_contract_review'], 1)

    def test_mismatched_hashes_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = root / module.REPORT_REL
            fp.parent.mkdir(parents=True)
            fp.write_text(json.dumps({'report_type': 'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION',
                                     'all_public_task_count': 0, 'input_sha256': {'oops': 'changed'}}))
            with patch.object(module, 'load_and_verify', return_value=([],
                 {'status': module.EXPECTED_STATUS}, {'a': 'b'})), \
                 patch.object(module, 'load_public_details', return_value={}):
                with self.assertRaises(ValueError):
                    module.build_record(root)

    def test_cannot_overwrite_existing_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'manual_review.json'
            module.write_new(dest, {'revision': 1})
            before = dest.read_bytes()
            with self.assertRaises(FileExistsError):
                module.write_new(dest, {'revision': 2})
            self.assertEqual(dest.read_bytes(), before)

    def test_missing_parent_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                module.write_new(Path(tmp) / 'missing' / 'manual_review.json', {})

    def test_no_write_on_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / module.OUTPUT_REL
            with patch.object(module, 'build_record', return_value={
                'manifest_status_at_review': module.EXPECTED_STATUS,
                'verdict_counts': {},
                'quarantine': {'development_task_ids': []}}):
                rc = module.main(['--root', str(root)])
            self.assertEqual(rc, 0)
            self.assertFalse(p.exists())


def run_self_tests():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReviewRecordTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    unittest.main()
