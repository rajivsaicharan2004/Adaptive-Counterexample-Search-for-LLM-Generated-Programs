import csv
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase2d_stratified_overlap_sampling as m


def row(a, b, score, ds_a='mbpp', ds_b='mbpp', p_a='development', p_b='held_out'):
    return {'task_a': a, 'task_b': b, 'dataset_a': ds_a, 'dataset_b': ds_b,
            'partition_a': p_a, 'partition_b': p_b,
            'lexical_weighted_jaccard': score}


class SamplerTests(unittest.TestCase):
    def test_pair_canonical(self):
        self.assertEqual(m.pair_key('z', 'a'), m.pair_key('a', 'z'))

    def test_pair_rejects_same_task(self):
        with self.assertRaises(ValueError):
            m.pair_key('a', 'a')

    def test_band_endpoints(self):
        self.assertEqual(m.score_band(0.12), '[0.12,0.20)')
        self.assertEqual(m.score_band(0.20), '[0.20,0.35)')
        self.assertEqual(m.score_band(0.35), '[0.35,0.50)')
        self.assertEqual(m.score_band(0.50), '[0.50,0.65)')
        self.assertEqual(m.score_band(0.65), 'priority_ge_0.65')

    def test_stratum_unordered_partitions_and_datasets(self):
        left = row('a', 'b', .23, 'mbpp', 'humaneval', 'validation', 'held_out')
        right = row('b', 'a', .23, 'humaneval', 'mbpp', 'held_out', 'validation')
        self.assertEqual(m.stratum_key(left), m.stratum_key(right))

    def test_priority_excludes_reviewed(self):
        rows = [row('a', 'b', .92), row('a', 'c', .8), row('a', 'd', .23)]
        priority, sample, inv = m.split_priority_and_sample(
            rows, {m.pair_key('a', 'b')}, per_stratum=5)
        self.assertEqual([p['task_b'] for p in priority], ['c'])
        self.assertEqual([p['task_b'] for p in sample], ['d'])
        self.assertEqual(inv[0]['population_N'], 1)

    def test_deterministic_under_input_reordering(self):
        rows = [row('a', 'x'+str(i), 0.2 + i * 0.001) for i in range(20)]
        one = m.split_priority_and_sample(rows, set(), seed=2026, per_stratum=4)
        two = m.split_priority_and_sample(list(reversed(rows)), set(), seed=2026, per_stratum=4)
        self.assertEqual(one, two)
        self.assertEqual(one[2][0]['population_N'], 20)
        self.assertEqual(one[2][0]['sample_n'], 4)
        self.assertEqual(one[2][0]['sampling_fraction'], .2)

    def test_no_repeated_pairs_even_reversed(self):
        rows = [row('a', 'b', .25), row('b', 'a', .26)]
        with self.assertRaisesRegex(ValueError, 'Repeated lexical pair'):
            m.split_priority_and_sample(rows, set())

    def test_sampling_separate_dataset_strata(self):
        rows = [row('a', 'b', .21), row('c', 'd', .24, 'humaneval', 'mbpp')]
        _, samples, inv = m.split_priority_and_sample(rows, set(), per_stratum=1)
        self.assertEqual(len(inv), 2)
        self.assertEqual(len(samples), 2)

    def test_export_new_only_and_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'reports'
            r = row('a', 'b', 0.7)
            p = {**r, 'prompt_a': 'safe', 'prompt_b': '=1+2',
                 'manual_verdict':'', 'review_notes':''}
            outputs = m.export_files(dest, {'x': 1}, [p], [], [])
            self.assertEqual(len(outputs), 4)
            self.assertEqual(json.loads(outputs[0].read_text()), {'x': 1})
            with outputs[1].open(newline='') as f:
                item = list(csv.DictReader(f))[0]
            self.assertEqual(item['prompt_b'], "'=1+2")
            with self.assertRaisesRegex(ValueError, 'Refusing to overwrite'):
                m.export_files(dest, {'x':2}, [], [], [])

    def test_fail_closed_on_missing_report(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Missing input file'):
                m.verify_evidence(Path(folder), {}, {'status': 'draft_requires_review_and_freeze'}, [])

    def test_fail_closed_on_frozen_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'Manifest changed from draft'):
                m.verify_evidence(Path(folder), {}, {'status': 'frozen'}, [])

    def test_reject_bad_sample_size(self):
        with self.assertRaises(ValueError):
            m.split_priority_and_sample([], set(), per_stratum=0)

    def test_evidence_verified_and_stale_hash_rejected(self):
        from phase2d_global_overlap_audit import Task, features, normalized_prompt, sha256_text
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = root / 'results/phase2d/global_overlap_audit_v1'
            base.mkdir(parents=True)
            tasks = []
            pair_sets = [[], []]
            for n in range(14):
                a, b = f'mbpp/a{n}', f'mbpp/b{n}'
                for tid, part in ((a, 'development'), (b, 'held_out')):
                    prompt = f'Unique factorial target {tid}'
                    tasks.append(Task(tid, 'mbpp', prompt,
                                      sha256_text(normalized_prompt(prompt)),
                                      part, features(prompt)))
                pair_sets[0 if n < 6 else 1].append({
                    'task_a': a, 'task_b': b,
                    'partition_a': 'development', 'partition_b': 'held_out',
                })
            hashes = {'manifest': 'mocksha'}
            report = {'report_type': 'PUBLIC_LEXICAL_SCREENING_ONLY_NOT_SEMANTIC_DEDUPLICATION',
                      'all_public_task_count': len(tasks),
                      'input_sha256': hashes,
                      'exact_normalized_prompt_groups': []}
            report_path = root / m.REPORT_REL
            report_path.write_text(json.dumps(report))
            report_sha = m.sha256_file(report_path)
            for rel, pairs in zip(m.REVIEW_RELS, pair_sets):
                doc = {'manifest_status_at_review': m.EXPECTED_MANIFEST_STATUS,
                       'input_sha256': hashes,
                       'lexical_report_sha256': report_sha,
                       'execution_authorized': False,
                       'final_split_freeze_authorized': False,
                       'reviewed_pair_count': len(pairs), 'pairs': pairs}
                (root / rel).write_text(json.dumps(doc))
            verified, reviewed, _ = m.verify_evidence(
                root, hashes, {'status':m.EXPECTED_MANIFEST_STATUS}, tasks)
            self.assertEqual(len(reviewed), 14)
            self.assertEqual(verified, report)
            hashes['manifest'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'stale'):
                m.verify_evidence(root, hashes,
                                  {'status':m.EXPECTED_MANIFEST_STATUS}, tasks)


if __name__ == '__main__':
    unittest.main()
