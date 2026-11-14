# Phase 2B-5 Fairness V1: versioned synthetic fault-detection pilot

## Scope
This is a NEW benchmark entry point, not an in-place edit of the old file.
The historical `phase2b5_fault_benchmark.py` and its results stay untouched.
No V3 quarantine policy, split manifest, candidate, dataset, or saved test corpus is modified by installation.

New files:
- `phase2b5_fault_benchmark_fair_v1.py` (separate entry point)
- `phase2b_fairness_preflight.py` (read-only integrity and environment check)
- `tests/test_phase2b_fairness_v1.py` (offline fixture tests)
- `README_PHASE2B_FAIRNESS_V1.md`

## Install
In your Mac VS Code terminal:

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2b_fairness_v1.zip -d .
```

Do not use `unzip -o` or overwrite files. If one of these filenames exists,
inspect it before proceeding.

## Step 1. Verify source identity (read-only)

```bash
.venv/bin/python phase2b_fairness_preflight.py
```

This checks that the old benchmark matches the exact source reviewed for
this correction (SHA-256 `951bf1b9...48aac186c`), that the new clone's
hash matches the package, and that the Phase 2D Hypothesis generator has
seeded, non-derandomized settings. A mismatch exits nonzero; stop then.

## Step 2. Run offline unit tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_phase2b_fairness_v1.py' -v
```

17 tests are expected to pass. The fixture tests do not run real Hypothesis,
Docker, models, synthetic mutants, or candidate programs.

## Step 3. Real Hypothesis seed audit (no Docker or candidates)

```bash
.venv/bin/python phase2b5_fault_benchmark_fair_v1.py --seed-audit --budget 20 --seed 2026
```

Expect `SEED AUDIT PASS` for HumanEval/0 and HumanEval/1, plus distinct
SHA-256 hashes for seeds 2026 and 2027. A repeat of seed 2026 must have
the same sequence and hash. The script stops if a repeat differs or two
adjacent seeds produce the same selected input sequence. This is a
reproducibility/diversity check, NOT a proof of statistical independence.

## Optional: Inspect a different budget without running programs

```bash
.venv/bin/python phase2b5_fault_benchmark_fair_v1.py --seed-audit --budget 40 --seed 2026
```

## Not yet authorized: synthetic Docker trials

Docker trials require an explicit `--execute-synthetic-docker` flag. Do not
use it until seed-audit and protocol review have succeeded. Historical
outcomes cannot be pooled with fairness-v1 because the seeded Phase 2D
Hypothesis generator has a different input distribution from the legacy
Phase 2B generator.

## Accounting and research limitations

The total nominal budget B is **target candidate sandbox calls plus probe
sandbox calls**, per synthetic mutant per method:
- Property: B target, 0 probe.
- Mutation: B target, 0 probe.
- Differential: B/2 target, B/2 probe.
- Metamorphic: B target executions, grouped into B/2 base/follow-up pairs.

Reports now store separate target, probe, reference-oracle counts, source
hashes, Hypothesis version, seed, corpus hashes, and generation timing.
Reference-oracle outputs are generated once per method/task and shared
across the five synthetic mutants. Their cost is not matched between
methods. Input preparation and Docker overhead are also not matched.
The reported first-failure index is calculated post hoc after full
corpus execution; it is not observed online early-stopping compute.

The synthetic fault benchmark can diagnose testing machinery, not measure
real LLM correctness or held-out accuracy. HumanEval/1 has a recognized
procedural overlap with held-out HumanEval/6, so its pilot results should
not be used as evidence of independent generalization to that task.

If any step fails closed, do not run Docker or edit the old benchmark;
share the preflight or seed-audit output for a targeted correction.
