"""Regression tests requiring no API key or Docker daemon."""
from __future__ import annotations
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from phase2d.models import TaskSpec, Case, CostLedger, result_matches, value_equal, sha256_text
from phase2d.adapters import public_task, load_development_suite, readiness, task_filename
from phase2d.candidates import discover, static_check
from phase2d.engine import evaluate
from phase2d.sandbox import CHILD
from phase2d import strategies
from phase2d_experiments import simulate
from phase2d_splits import generate_splits


class DummySandbox:
    image="fake-pinned-image"
    timeout=3
    def __init__(self): self.ready=False
    def ensure_ready(self): self.ready=True
    def run(self, code, entry_point, interface, cases, *,coverage=False):
        # Simulated execution only; no generated code executes on the host.
        responses=[]
        for row in cases:
            expected=any(abs(row["args"][0][i]-row["args"][0][j])<row["args"][1]
                         for i in range(len(row["args"][0]))
                         for j in range(i+1,len(row["args"][0])))
            responses.append({"status":"ok", "type":"bool", "value":expected,
                              "execution_seconds":0.001})
        return responses,0.01


class TestComparison(unittest.TestCase):
    def setUp(self):
        self.spec=TaskSpec("humaneval","HumanEval/0","prompt","has_close_elements","callable")

    def test_exact_type_safety(self):
        self.assertFalse(result_matches({"status":"ok","type":"int","value":1},Case("x",[],True),self.spec))
        self.assertFalse(value_equal(True,1,"numeric",1e-6,1e-6))
        self.assertFalse(value_equal([1,"x"],[1,2],"exact",0,0))

    def test_numeric_tolerance(self):
        spec=TaskSpec("mbpp","MBPP/10","prompt","f","callable",comparison="numeric",abs_tol=1e-5)
        self.assertTrue(result_matches({"status":"ok","type":"float","value":1.000001},Case("x",[],1.0),spec))
        self.assertFalse(result_matches({"status":"ok","type":"float","value":1.01},Case("x",[],1.0),spec))
        self.assertTrue(value_equal([2,1,1],[1,2,1],"unordered_list",0,0))

    def test_cost_accounting(self):
        ledger=CostLedger()
        ledger.record_executions("candidate",3,0.6)
        ledger.record_executions("reference",2,0.1)
        self.assertEqual(ledger.snapshot()["candidate_executions"],3)
        self.assertEqual(ledger.snapshot()["reference_executions"],2)
        self.assertAlmostEqual(ledger.snapshot()["execution_seconds"],0.7)


class TestDatasetRegistry(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)
        (self.root/"data/public").mkdir(parents=True)
        (self.root/"generated/phase1/a_HumanEval_0").mkdir(parents=True)
        rows=[{"dataset":"humaneval","task_id":"HumanEval/0","prompt":"has_close_elements", "entry_point":"has_close_elements"},
              {"dataset":"mbpp","task_id":"MBPP/545","prompt":"toggle_F_and_L_bits", "entry_point":"toggle_F_and_L_bits"},
              {"dataset":"livecodebench","task_id":"LiveCodeBench/leetcode/3360","prompt":"method", "entry_point":"minimumDeletions"}]
        (self.root/"data/public/problems.jsonl").write_text("\n".join(json.dumps(x) for x in rows),encoding="utf-8")
        folder=self.root/"generated/phase1/a_HumanEval_0"
        code="def has_close_elements(numbers, threshold):\n    return False\n"
        (folder/"mcts_001.py").write_text(code,encoding="utf-8")
        (folder/"mcts_001.json").write_text(json.dumps({"status":"generated","method":"mcts",
            "task_id":"HumanEval/0","code_sha256":sha256_text(code.rstrip("\n"))}),encoding="utf-8")

    def tearDown(self): self.t.cleanup()

    def test_public_task_and_dev(self):
        spec=public_task(self.root,"humaneval","HumanEval/0")
        cases,source,spec=load_development_suite(self.root,spec)
        self.assertEqual(len(cases),8)
        self.assertTrue(readiness(spec,len(cases))["ready"])
        self.assertEqual(len(discover(self.root,["generated/phase1/a_HumanEval_0"],"HumanEval/0")),1)
        live=public_task(self.root,"livecodebench","LiveCodeBench/leetcode/3360")
        self.assertEqual(live.interface,"leetcode_method")
        self.assertFalse(readiness(live)["ready"])

    def test_mbpp_builtin_cases(self):
        spec=public_task(self.root,"mbpp","MBPP/545")
        cases, _, spec=load_development_suite(self.root,spec)
        self.assertEqual(len(cases),20)
        self.assertTrue(all(x.expected_type=="int" for x in cases))

    def test_diagnostic_excluded(self):
        folder=self.root/"generated/phase1/a_HumanEval_0"
        meta=json.loads((folder/"mcts_001.json").read_text())
        meta["diagnostic_only"]=True
        (folder/"mcts_001.json").write_text(json.dumps(meta))
        with self.assertRaises(ValueError):
            discover(self.root,["generated/phase1/a_HumanEval_0"],"HumanEval/0")
        self.assertEqual(len(discover(self.root,["generated/phase1/a_HumanEval_0"],"HumanEval/0",
                                      include_diagnostics=True)),1)

    def test_engine_fake(self):
        fake=DummySandbox()
        result=evaluate(self.root,"humaneval","HumanEval/0",
                        ["generated/phase1/a_HumanEval_0"],fake,
                        execute=True,batch_size=3)
        self.assertTrue(fake.ready)
        self.assertEqual(result["results"][0]["passed"],8)
        self.assertEqual(result["ledger"]["candidate_executions"],8)
        self.assertEqual(result["ledger"]["reference_executions"],0)
        self.assertTrue(Path(result["report_path"]).is_file())

    def test_static_interface(self):
        self.assertTrue(static_check("class Solution:\n def minimumDeletions(self,s): return 1",
                                     "minimumDeletions","leetcode_method")[0])
        self.assertFalse(static_check("def wrong(): return 1","needed","callable")[0])


class TestStrategies(unittest.TestCase):
    def test_input_contract(self):
        self.assertTrue(strategies.valid_args("HumanEval/0",[[1.0,1.1],0.5]))
        self.assertFalse(strategies.valid_args("HumanEval/1",["(()"]))
        self.assertTrue(strategies.valid_args("MBPP/545",[65]))
        self.assertFalse(strategies.valid_args("MBPP/545",[0]))

    def test_mutation_seed(self):
        seeds=[[1],[2],[4]]
        x=strategies.mutation_inputs("MBPP/545",seeds,10,2026)
        y=strategies.mutation_inputs("MBPP/545",seeds,10,2026)
        self.assertEqual(x,y)
        self.assertEqual(len({json.dumps(v) for v in x}),10)

    def test_shrinking(self):
        result=strategies.shrink_failure("MBPP/545",[100],lambda a:a[0]>=2)
        self.assertLess(result["minimized"][0],100)

    def test_offline_baselines(self):
        costs={"property":3,"mutation":2,"differential":4,"metamorphic":None}
        self.assertTrue(simulate(costs,10,"fixed_mutation",2026)["detected"])
        self.assertFalse(simulate(costs,2,"fixed_differential",2026)["detected"])

    def test_hypothesis_reproducibility_if_installed(self):
        try: import hypothesis
        except ImportError: self.skipTest("Hypothesis unavailable in local environment")
        first=strategies.property_inputs("MBPP/545",20,2026)
        second=strategies.property_inputs("MBPP/545",20,2026)
        third=strategies.property_inputs("MBPP/545",20,2027)
        self.assertEqual(first,second)
        self.assertNotEqual(first,third)


class TestPartitioning(unittest.TestCase):
    def test_heldout_livecodebench_and_dev_pilots(self):
        rows=[("humaneval","HumanEval/1","one"),
              ("mbpp","MBPP/545","two"),
              ("livecodebench","LiveCodeBench/leetcode/3360","three")]
        result=generate_splits(rows,2026)
        self.assertEqual(result["tasks"]["HumanEval/1"]["partition"],"development")
        self.assertEqual(result["tasks"]["MBPP/545"]["partition"],"development")
        self.assertEqual(result["tasks"]["LiveCodeBench/leetcode/3360"]["partition"],
                         "held_out_temporal_pending")


class TestRunnerProtocol(unittest.TestCase):
    def run_child(self, code, args):
        payload={"code":code,"entry_point":"f","interface":"callable",
                 "args":args,"coverage":True}
        result=subprocess.run([sys.executable,"-I","-S","-B","-c",CHILD],
              input=json.dumps(payload),text=True,capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)

    def test_candidate_print_cannot_corrupt_protocol(self):
        result=self.run_child("def f(x):\n print('spoof')\n return x+1",[4])
        self.assertEqual(result["value"],5)
        self.assertTrue(result["line_coverage"])

    def test_os_write_does_not_spoof(self):
        result=self.run_child("import os\ndef f(x):\n os.write(1,b'{\"status\":\"ok\",\"value\":999}\\n')\n return x+1",[4])
        self.assertEqual(result["value"],5)

    def test_expected_exception(self):
        result=self.run_child("def f(x):\n raise ValueError('bad')",[4])
        self.assertEqual(result["status"],"exception")
        self.assertEqual(result["error_type"],"ValueError")


if __name__=="__main__":unittest.main()
