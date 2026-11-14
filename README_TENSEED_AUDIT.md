# Phase 2B Fairness V1 — ten-seed evidence audit

This package adds one **new** read-only-first script to the existing VS Code project. It does **not** edit `phase2b5_fault_benchmark_fair_v1.py`, the original benchmark, candidates, private tests, dataset manifest, or V3 quarantine guard. It does not invoke Docker, execute Python candidates, or call Gemini/OpenAI.

## Install on your Mac

Download `phase2b_tenseed_audit_v1.zip` and run:

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2b_tenseed_audit_v1.zip -d .
```

**Do not use `unzip -o`.** Stop and inspect if `phase2b_tenseed_audit.py` already exists.

## Step 1: verify ONLY, with no files written

```bash
.venv/bin/python phase2b_fairness_preflight.py
.venv/bin/python phase2b_tenseed_audit.py --verify-only
```

The audit selects exactly **11 specifically named report JSON files** (two individual seed-2026 task reports plus one two-task report for each seed 2027–2035). For each report, it verifies source/protocol hashes, seed, task coverage, mutant IDs, per-method budgets, aggregate totals, and the input-corpus JSON SHA-256 recorded in the report. It also verifies every method's input list and hash, and fails closed on missing or mismatched files. It does **not** infer or select alternative reports via globbing.

Expected successful summary, based on the console logs (not yet independently confirmed across all JSON files):

```
TEN-SEED AUDIT PASSED: 2026..2035, 2 tasks, 10 synthetic mutants, 11 reports, 11 corpora
  property      96/100 mutant-seed detections; 4000 target+probe executions
  mutation      97/100 mutant-seed detections; 4000 target+probe executions
  differential  79/100 mutant-seed detections; 4000 target+probe executions
  metamorphic   57/100 mutant-seed detections; 4000 target+probe executions
READ-ONLY VERIFICATION COMPLETE: no files modified or written
```

## Step 2: optional evidence bundle for upload

After verifying successfully:

```bash
.venv/bin/python phase2b_tenseed_audit.py --bundle
```

Creates one **new** ZIP under `results/phase2b/phase2b_fairness_v1_ten_seed_evidence_bundle.zip` with all 11 original report files, their 11 original input corpora, and an evidence manifest containing SHA-256 hashes and summaries. The script **refuses to overwrite** an existing evidence ZIP. Upload this archive to the conversation for deeper analysis; do not send any secrets or private reference-solution files. The archive contains only the benchmark's previously saved reports and generated inputs.

## Interpretation limits

- 100 mutant-seed observations per method are repeated observations of **ten** synthetic mutants, not 100 independent code samples.
- The equal nominal budget is 40 target-plus-probe sandbox calls per mutant per method. Differential has fewer target executions and extra probe executions.
- Oracle and input-generation costs are not equal; reference outputs are shared across mutants.
- The original benchmark's first-hit index is post hoc, not real early-stopping savings.
- HumanEval/1 has a previously flagged overlap with held-out HumanEval/6. These diagnostic results do **not** establish independent held-out performance.
- The audit does not execute any program and therefore does not independently validate the runtime behavior or safety configuration of the historical runs.

## Fail-closed behavior

On failure, leave original files untouched and share the exact error. Do not rename/replace reports or alter any source hashes just to make the verifier pass. A report could legitimately differ from the expected version; that should be investigated before aggregation.
