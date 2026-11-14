"""Offline, Docker-free regression suite for versioned fairness pilot.

Live Hypothesis behavior must be verified on the user's environment with
--seed-audit. Local fixtures validate the wiring, not Hypothesis itself.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def historical_source():
    choices = (ROOT / 'phase2b5_fault_benchmark.py',
               ROOT.parent / 'phase2b5_fault_benchmark.py',
               Path('/mnt/data/phase2b5_fault_benchmark.py'))
    return next((p for p in choices if p.is_file()), Path('/nonexistent/phase2b5_fault_benchmark.py'))


def fake_property_inputs(task, count, seed):
    r = random.Random(f'{task}:{seed}')
    if task == 'HumanEval/0':
        return [[[float(r.randint(-20, 20)), float(r.randint(-20, 20))], float(r.randint(0, 20))]
                for _ in range(count)]
    return [['()' * r.randint(1, 4) + ' ' * r.randint(0, 4)] for _ in range(count)]


def fake_valid_numbers(args):
    return isinstance(args, list) and len(args) == 2 and isinstance(args[0], list)


def fake_valid_parens(args):
    return isinstance(args, list) and len(args) == 1 and isinstance(args[0], str)


def load_fairness_module():
    # Fixtures guarantee no Docker or untrusted candidate execution in unit tests.
    hypothesis = types.ModuleType('hypothesis')
    hypothesis.__version__ = 'synthetic-fixture'
    strategies = types.ModuleType('phase2d.strategies')
    strategies.property_inputs = fake_property_inputs
    phase2d = types.ModuleType('phase2d')
    phase2d.__path__ = []
    phase2d.strategies = strategies
    base = types.ModuleType('phase2a_validator')
    base.MAX_CASES = 20
    base.matching_result = lambda observed, expected, expected_type: (
        observed.get('status') == 'ok' and observed.get('value') == expected)
    mutation = types.ModuleType('phase2b2_mutation')
    mutation.valid_numbers = fake_valid_numbers
    mutation.valid_parens = fake_valid_parens
    metamorphic = types.ModuleType('phase2b4_metamorphic')
    metamorphic.canonical = lambda x: json.dumps(x, sort_keys=True)
    metamorphic.relation_holds = lambda a,b,r,info: a.get('value') == b.get('value')
    fixtures = {
        'hypothesis': hypothesis, 'phase2d': phase2d, 'phase2d.strategies': strategies,
        'phase2a_validator': base, 'phase2b2_mutation': mutation,
        'phase2b4_metamorphic': metamorphic,
    }
    with patch.dict(sys.modules, fixtures):
        spec = importlib.util.spec_from_file_location('fairness_test_subject',
                                                       ROOT / 'phase2b5_fault_benchmark_fair_v1.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    # Imports are resolved at import time; module remains usable after fixture teardown.
    return mod


class FairnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_fairness_module()

    def test_historical_source_hash_matches_fixture(self):
        old = historical_source()
        if old.exists():
            self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),
                             '951bf1b9b898a81bf5f1ca18918a0a60155fcdacf0bb46b66075c441532a5aca')

    def test_fairness_clone_compiles(self):
        source = (ROOT / 'phase2b5_fault_benchmark_fair_v1.py').read_text()
        compile(source, 'fair_v1.py', 'exec')

    def test_corpora_repeat_given_seed(self):
        a, am = self.mod.property_cases('HumanEval/0', 20, 2026)
        b, bm = self.mod.property_cases('HumanEval/0', 20, 2026)
        self.assertEqual(a,b)
        self.assertEqual(am['corpus_sha256'],bm['corpus_sha256'])

    def test_seed_is_passed_to_source(self):
        calls=[]
        def capture(task,count,seed):
            calls.append((task,count,seed))
            return fake_property_inputs(task,count,seed)
        with patch.object(self.mod,'seeded_property_inputs',capture):
            self.mod.property_cases('HumanEval/0',20,17)
        self.assertEqual(calls,[('HumanEval/0',60,17)])

    def test_independent_seed_changes_corpus(self):
        a,_ = self.mod.property_cases('HumanEval/0',20,2026)
        b,_ = self.mod.property_cases('HumanEval/0',20,2027)
        self.assertNotEqual(a,b)

    def test_seed_zero_supported(self):
        a,_=self.mod.property_cases('HumanEval/0',20,0)
        b,_=self.mod.property_cases('HumanEval/0',20,0)
        self.assertEqual(a,b)

    def test_property_generator_validates_cases(self):
        with patch.object(self.mod, 'seeded_property_inputs', lambda *x: [['bad']] * x[1]):
            with self.assertRaisesRegex(RuntimeError,'only 0/10'):
                self.mod.property_cases('HumanEval/0',10,3)

    def test_property_generator_de_duplicates_before_budget(self):
        with patch.object(self.mod,'seeded_property_inputs',
                          lambda task,count,seed:[[[1.0,2.0],1.0]]*count):
            with self.assertRaisesRegex(RuntimeError,'only 1/10'):
                self.mod.property_cases('HumanEval/0',10,3)

    def test_seed_metadata(self):
        _,s=self.mod.property_cases('HumanEval/1',10,3)
        self.assertEqual(s['hypothesis_seed'],3)
        self.assertEqual(s['hypothesis_derandomize'],False)
        self.assertIsNone(s['hypothesis_database'])

    def test_seed_audit_never_probes(self):
        with patch.object(self.mod, 'probe_code', side_effect=AssertionError('probe read during seed audit')):
            with patch.object(sys,'argv',['fair','--task-id','HumanEval/0','--seed-audit','--budget','20']):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.mod.main()
        self.assertIn('SEED AUDIT PASS',out.getvalue())

    def test_default_requires_explicit_docker_flag(self):
        with patch.object(sys,'argv',['fair','--task-id','HumanEval/0']):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    self.mod.main()
        self.assertEqual(exc.exception.code,2)

    def test_differential_accounting(self):
        calls=[]
        def execute(code,entry,inputs,batch):
            calls.append((code,len(inputs)))
            return [{'status':'ok','value': ('bad' if code=='mutant' else 'good')} for _ in inputs]
        m=self.mod
        corpus={'differential':[[1],[2]]}
        expected={'differential':[{'status':'ok','value':'good','type':'str'} for _ in range(2)]}
        with patch.object(m,'execute',execute):
            result=m.evaluate_method('differential','mutant','probe','f',corpus,expected,5)
        self.assertEqual(result['target_candidate_executions'],2)
        self.assertEqual(result['differential_probe_executions'],2)
        self.assertEqual(result['candidate_executions'],4)
        self.assertEqual(result['reference_oracle_executions'],2)
        self.assertTrue(result['budget_ledger_matches'])
        self.assertTrue(result['first_failure_cost_is_posthoc_index'])

    def test_property_budget_accounting(self):
        m=self.mod
        def execute(code,entry,inputs,batch):
            return [{'status':'ok','value':'bad'} for _ in inputs]
        corpus={'property':[[1],[2],[3],[4]]}
        expected={'property':[{'status':'ok','value':'good','type':'str'} for _ in range(4)]}
        with patch.object(m,'execute',execute):
            result=m.evaluate_method('property','mutant',None,'f',corpus,expected,2)
        self.assertEqual(result['target_candidate_executions'],4)
        self.assertEqual(result['differential_probe_executions'],0)
        self.assertEqual(result['candidate_executions'],4)

    def test_metamorphic_pair_accounting(self):
        m=self.mod
        corpus={'metamorphic':[[1],[2],[3],[4]],'pairs':[{'relation':'same','relation_info':{}}, {'relation':'same','relation_info':{}}]}
        expected={'metamorphic':[{'status':'ok','value':'good','type':'str'} for _ in range(4)]}
        def execute(code,entry,inputs,batch):
            return [{'status':'ok','value':i%2} for i,_ in enumerate(inputs)]
        with patch.object(m,'execute',execute):
            result=m.evaluate_method('metamorphic','mutant',None,'f',corpus,expected,2)
        self.assertEqual(result['target_candidate_executions'],4)
        self.assertEqual(result['differential_probe_executions'],0)
        self.assertEqual(result['candidate_executions'],4)

    def test_zero_calls_not_claimed_as_equal_oracle_budget(self):
        m=self.mod
        corpus={'differential':[[1],[2]]}
        expected={'differential':[{'status':'ok','value':'good','type':'str'} for _ in range(2)]}
        def execute(code,entry,inputs,batch):
            return [{'status':'ok','value':'good'} for _ in inputs]
        with patch.object(m,'execute',execute):
            r=m.evaluate_method('differential','mutant','probe','f',corpus,expected,2)
        self.assertNotEqual(r['reference_oracle_executions'],r['candidate_executions'])

    def test_source_preflight_passes_matching_fixture(self):
        spec=importlib.util.spec_from_file_location('preflight',ROOT/'phase2b_fairness_preflight.py')
        pf=importlib.util.module_from_spec(spec);spec.loader.exec_module(pf)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'phase2d').mkdir()
            expected=historical_source()
            if not expected.exists():
                self.skipTest('original source fixture unavailable')
            (root/'phase2b5_fault_benchmark.py').write_bytes(expected.read_bytes())
            (root/'phase2b5_fault_benchmark_fair_v1.py').write_bytes((ROOT/'phase2b5_fault_benchmark_fair_v1.py').read_bytes())
            (root/'phase2d'/'strategies.py').write_text('def property_inputs():\n    pass\n# @hypothesis_seed(seed_value)\n# derandomize=False\n')
            self.assertIn('PREFLIGHT PASSED',pf.check(root,check_installed_hypothesis=False)['status'])
            (root/'phase2b5_fault_benchmark.py').write_text('tampered')
            with self.assertRaisesRegex(RuntimeError,'Historical benchmark source differs'):
                pf.check(root,check_installed_hypothesis=False)

    def test_preflight_clone_tampering_fails_closed(self):
        spec=importlib.util.spec_from_file_location('preflight2',ROOT/'phase2b_fairness_preflight.py')
        pf=importlib.util.module_from_spec(spec);spec.loader.exec_module(pf)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'phase2d').mkdir()
            old=historical_source()
            if not old.exists():self.skipTest('original source fixture unavailable')
            (root/'phase2b5_fault_benchmark.py').write_bytes(old.read_bytes())
            (root/'phase2b5_fault_benchmark_fair_v1.py').write_text('tampered')
            (root/'phase2d'/'strategies.py').write_text('def property_inputs():\n    pass\n# @hypothesis_seed(seed_value)\n# derandomize=False\n')
            with self.assertRaisesRegex(RuntimeError,'Fairness benchmark clone differs'):
                pf.check(root,check_installed_hypothesis=False)

if __name__=='__main__':
    unittest.main()
