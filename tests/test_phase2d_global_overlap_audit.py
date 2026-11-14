"""Tests run only static/synthetic public data, never generated candidate code."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase2d_global_overlap_audit as audit


class GlobalAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data' / 'public').mkdir(parents=True)
        (self.root / 'results' / 'phase2d').mkdir(parents=True)
        self.records = {
            'humaneval': [
                ('HumanEval/0', 'development', 'Generate all permutations and sum factorials of numbers'),
                ('HumanEval/1', 'held_out', 'find the maximum element in an array'),
            ],
            'mbpp': [('MBPP/1', 'held_out', 'Generate ALL permutations and sum factorials of numbers')],
            'bigcodebench': [('BigCodeBench/1', 'validation', 'Read the CSV file and plot a graph')],
            'livecodebench': [('LiveCodeBench/x', 'held_out_temporal_pending', 'find greatest element in a list')],
        }
        self.make_dataset()

    def tearDown(self):
        self.tmp.cleanup()

    def make_dataset(self):
        manifest = {'status': 'draft_requires_review_and_freeze', 'tasks': {}}
        for dataset, records in self.records.items():
            p = self.root / 'data' / 'public' / (dataset + '.jsonl')
            with p.open('w') as f:
                for task_id, partition, prompt in records:
                    row = {'task_id': task_id, 'dataset': dataset, 'prompt': prompt}
                    f.write(json.dumps(row) + '\n')
                    manifest['tasks'][task_id] = {
                        'public_prompt_sha256': audit.sha256_text(audit.normalized_prompt(prompt)),
                        'dataset': dataset, 'partition': partition,
                    }
        self.manifest_path = self.root / 'results' / 'phase2d' / 'splits.json'
        self.manifest_path.write_text(json.dumps(manifest))

    def test_manifest_and_exact_cross_dataset(self):
        tasks, manifest, provenance = audit.load_and_verify(self.root, expected_count=5)
        self.assertEqual(5, len(tasks))
        report = audit.build_report(tasks, manifest, provenance,
                                    top=10, same_top=10, per_dataset_pair=10, max_df=100, min_score=0.0)
        # the same normalized prompt exists despite capitalization differences.
        exact = report['exact_normalized_prompt_groups']
        self.assertEqual(1, len(exact))
        self.assertTrue(exact[0]['cross_partition'])
        self.assertEqual({'HumanEval/0', 'MBPP/1'}, set(exact[0]['task_ids']))
        self.assertTrue(any({x['task_a'], x['task_b']} == {'HumanEval/0', 'MBPP/1'}
                            for x in report['cross_partition_review_queue']))
        self.assertEqual('draft_requires_review_and_freeze', report['source_manifest_status'])
        self.assertEqual(5, report['all_public_task_count'])
        self.assertTrue(any({x['task_a'], x['task_b']} == {'HumanEval/0', 'MBPP/1'}
                            for x in report['cross_dataset_stratified_review_queue']))

    def test_corrupt_prompt_hash_fails_closed(self):
        m = json.loads(self.manifest_path.read_text())
        m['tasks']['HumanEval/0']['public_prompt_sha256'] = 'wrong'
        self.manifest_path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            audit.load_and_verify(self.root, expected_count=5)

    def test_missing_task_fails_closed(self):
        m = json.loads(self.manifest_path.read_text())
        del m['tasks']['HumanEval/0']
        self.manifest_path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'manifest entry'):
            audit.load_and_verify(self.root, expected_count=5)

    def test_no_reports_unless_explicit_export(self):
        tasks, m, provenance = audit.load_and_verify(self.root, expected_count=5)
        report = audit.build_report(tasks, m, provenance,
                                    top=5, same_top=5, per_dataset_pair=10, max_df=100, min_score=.05)
        out = self.root / 'review_reports'
        self.assertFalse(out.exists())
        paths = audit.export_reports(report, out)
        self.assertEqual(4, len(paths))
        self.assertTrue(all(path.is_file() for path in paths))
        with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
            audit.export_reports(report, out)
        self.assertEqual(5, len(audit.load_and_verify(self.root, expected_count=5)[0]))

    def test_default_boilerplate_removal(self):
        p = 'Generate all permutations of input integers.\nYou should write self-contained code starting with:\n```\nimport itertools\n```'
        self.assertNotIn('itertools', audit.strip_template(p))
        self.assertIn('permutations', audit.strip_template(p))

    def test_empty_inputs_no_division_by_zero(self):
        self.assertEqual(0.0, audit.weighted_jaccard(frozenset(), frozenset(), {}))
        self.assertEqual(frozenset(), audit.char_ngrams(''))


if __name__ == '__main__':
    unittest.main()
