#!/usr/bin/env python3
"""Offline, no-Docker unit tests for manifest-selected runner accounting.

Run: python test_phase2f_primary_cohort_eval_v1.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

E = types.ModuleType('phase2f_guarded_candidate_eval_v1')
E.O = types.SimpleNamespace(ORDER=['HumanEval/129'])
E.P = types.SimpleNamespace(stable_bytes=lambda d: (json.dumps(d, sort_keys=True) + '\n').encode())
E.check_permission = Mock()
E.run_one = Mock()
sys.modules[E.__name__] = E

path = Path(__file__).with_name('phase2f_primary_cohort_eval_v1.py')
spec = importlib.util.spec_from_file_location('phase2f_primary_cohort_eval_v1_testsubject', path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CohortGateTests(unittest.TestCase):
    def test_duplicate_never_executed_and_re_run_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            runner.ROOT = Path(folder).resolve()
            task = 'HumanEval/129'
            direct = 'generated/phase2f/HumanEval_129/original_direct_001.py'
            stems = ('sample_sampling_001', 'variation_diverse_001', 'boundary_boundary_001')
            rows = []
            registered = {}
            for method, stem in zip(('sampling', 'diverse', 'boundary'), stems):
                source_path = f'generated/phase2f/HumanEval_129/{stem}.py'
                rows.append({
                    'candidate_id': stem,
                    'method': method,
                    'source_path': source_path,
                    'source_sha256': 'samehash' if method == 'sampling' else method + 'hash',
                    'duplicate_of': direct if method == 'sampling' else None,
                })
                registered[source_path] = {
                    'path': runner.ROOT / source_path,
                    'metadata': {'task_id': task, 'method': method},
                    'hash': rows[-1]['source_sha256'],
                    'static_problem': 'missing_required_entry_point' if method == 'diverse' else None,
                }
            E.run_one.reset_mock()
            E.check_permission.reset_mock()
            E.run_one.return_value = {
                'status': 'no_failure_on_frozen_development_suite',
                'case_count': 128, 'passed': 128, 'failed': 0,
            }
            runner.run_task(
                task, rows, {'source_path': direct, 'sha256': 'samehash'},
                registered, {'tasks': {task: {'cases': [1]}}},
                {'tasks': {task: [2]}}, 'inputhash', 'labelhash',
            )
            self.assertEqual(E.run_one.call_count, 1)
            self.assertEqual(E.run_one.call_args[0][1], registered[rows[2]['source_path']])
            output = list((runner.ROOT / runner.REPORT_REL).glob('*_cohort_v1_*.json'))
            report_files = [p for p in output if 'run_intent' not in p.name]
            self.assertEqual(len(report_files), 1)
            report = json.loads(report_files[0].read_text())
            self.assertEqual([r['status'] for r in report['reports']], [
                'duplicate_source_not_executed',
                'static_generation_failure',
                'no_failure_on_frozen_development_suite',
            ])
            self.assertEqual(report['primary_candidate_count'], 3)
            self.assertTrue(report['reports'][0]['baseline_reused_not_retested'])
            with self.assertRaises(runner.CohortGateError):
                runner.run_task(task, rows, {'source_path': direct}, registered, {}, {}, '', '')

    def test_bad_paths_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            runner.ROOT = Path(folder).resolve()
            for bad in ('../outside.py', '/tmp/absolute.py', 'folder/../../outside.py'):
                with self.assertRaises(runner.CohortGateError):
                    runner.safe_path(bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
