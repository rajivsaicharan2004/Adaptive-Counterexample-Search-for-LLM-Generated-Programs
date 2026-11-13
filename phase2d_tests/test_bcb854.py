"""Offline tests: no Docker, LLM APIs, public hidden tests, or candidate code."""
from __future__ import annotations
import math
import unittest
import subprocess
import sys
import json
from phase2d.bcb854 import (
    independently_derived_expectation, proposed_cases, compare, type_tree,
    conservative_source_review,
)


def observed_good(numbers):
    # Test response assembled from the proposed independent expectation,
    # not produced by running a generated candidate.
    ex = independently_derived_expectation(numbers)
    if ex['status'] == 'exception':
        return {'status': 'exception', 'error_type': ex['error_type']}
    sums, perms = ex['value']
    python_value = (sums, [tuple(row) for row in perms])
    return {'status': 'ok', 'type': 'tuple', 'value': ex['value'],
            'type_tree': type_tree(python_value)}


class TestPublicSpecification(unittest.TestCase):
    def test_independent_hand_calculations(self):
        self.assertEqual(independently_derived_expectation([])['value'], [[], []])
        self.assertEqual(independently_derived_expectation([0, 4])['value'],
                         [[25, 25], [[0, 4], [4, 0]]])
        self.assertEqual(independently_derived_expectation([1, 2, 3])['value'][0], [9] * 6)
        self.assertEqual(independently_derived_expectation([2, 2])['value'],
                         [[4, 4], [[2, 2], [2, 2]]])

    def test_input_contract(self):
        for x in ('3', 4, None, [1, 2.5], [1, '2'], [None]):
            self.assertEqual(independently_derived_expectation(x)['error_type'], 'TypeError')
        for x in ([-1], [2, -1]):
            self.assertEqual(independently_derived_expectation(x)['error_type'], 'ValueError')
        self.assertEqual(independently_derived_expectation([True])['error_type'], 'TypeError')

    def test_only_bounded_proposals(self):
        rows = proposed_cases()
        self.assertEqual(len(rows), 16)
        self.assertEqual(len({row['name'] for row in rows}), len(rows))
        self.assertTrue(all(len(row['args']) == 1 for row in rows))


class TestComparator(unittest.TestCase):
    def test_good_fixture_all_cases(self):
        for row in proposed_cases():
            with self.subTest(case=row['name']):
                self.assertTrue(compare(observed_good(row['args'][0]), row['expected'])['strict_pass'])

    def test_semantic_accepts_list_permutations_but_strict_rejects(self):
        want = independently_derived_expectation([0, 4])
        value = ([25, 25], [[0, 4], [4, 0]])
        got = {'status': 'ok', 'value': want['value'], 'type': 'tuple',
               'type_tree': type_tree(value)}
        verdict = compare(got, want)
        self.assertTrue(verdict['semantic_pass'])
        self.assertFalse(verdict['strict_pass'])

    def test_order_independent_but_pair_sensitive(self):
        want = independently_derived_expectation([1, 2, 3])
        sums, perms = want['value']
        changed = ([9] * len(sums), list(reversed(perms)))
        got = {'status': 'ok', 'value': [*changed], 'type': 'tuple',
               'type_tree': type_tree((changed[0], [tuple(p) for p in changed[1]]))}
        self.assertTrue(compare(got, want)['strict_pass'])
        wrong = {'status': 'ok', 'type': 'tuple',
                 'value': [[9] * 6, [[1, 2, 3]] * 6],
                 'type_tree': type_tree(([9] * 6, [(1, 2, 3)] * 6))}
        self.assertFalse(compare(wrong, want)['semantic_pass'])

    def test_duplicates_not_collapsed(self):
        want = independently_derived_expectation([2, 2])
        got = {'status': 'ok', 'type': 'tuple',
               'value': [[4], [[2, 2]]],
               'type_tree': type_tree(([4], [(2, 2)]))}
        self.assertFalse(compare(got, want)['semantic_pass'])

    def test_wrong_exception_rejected(self):
        want = independently_derived_expectation([-1])
        self.assertFalse(compare({'status': 'exception', 'error_type': 'TypeError'}, want)['semantic_pass'])
        self.assertTrue(compare({'status': 'exception', 'error_type': 'ValueError'}, want)['strict_pass'])

    def test_missing_type_metadata_semantic_only(self):
        want = independently_derived_expectation([0, 4])
        got = {'status': 'ok', 'type': 'tuple', 'value': want['value']}
        verdict = compare(got, want)
        self.assertTrue(verdict['semantic_pass'])
        self.assertFalse(verdict['strict_pass'])

    def test_malformed_shape_rejected(self):
        want = independently_derived_expectation([0, 4])
        for got in [
            {'status': 'ok', 'type': 'tuple', 'value': [25, 25]},
            {'status': 'ok', 'type': 'tuple', 'value': [[True, True], [[0, 4], [4, 0]]]},
            {'status': 'ok', 'type': 'tuple', 'value': [[25], [[0, 4], [4, 0]]]},
        ]:
            self.assertFalse(compare(got, want)['semantic_pass'])


if __name__ == '__main__':
    unittest.main()


class TestConservativeSourceReview(unittest.TestCase):
    def test_allowlist_and_disallowed_ops(self):
        safe = "from math import factorial\ndef task_func(xs): return [factorial(x) for x in xs]"
        self.assertEqual(conservative_source_review(safe), [])
        for unsafe in (
            "import subprocess\ndef task_func(xs): pass",
            "import socket\ndef task_func(xs): pass",
            "def task_func(xs): return open('/etc/passwd').read()",
            "def task_func(xs): return eval('2+2')",
            "def task_func(xs): return __import__('os')",
        ):
            self.assertTrue(conservative_source_review(unsafe), unsafe)

    def test_runner_type_metadata_with_harmless_local_fixture(self):
        # Only a constant, locally authored fixture is executed in a child.
        # No generated candidates, external libraries, Docker, or network.
        from phase2d.sandbox import CHILD
        payload = {
            'code': 'def f(): return ([25,25], [(0,4),(4,0)])',
            'entry_point': 'f', 'interface': 'callable', 'args': [],
            'describe_types': True, 'coverage': False,
        }
        child = subprocess.run(
            [sys.executable, '-I', '-S', '-B', '-c', CHILD],
            input=json.dumps(payload), capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        outcome = json.loads(child.stdout)
        self.assertEqual(outcome['status'], 'ok')
        self.assertEqual(outcome['type_tree']['kind'], 'tuple')
        self.assertEqual(outcome['type_tree']['items'][1]['items'][0]['kind'], 'tuple')
