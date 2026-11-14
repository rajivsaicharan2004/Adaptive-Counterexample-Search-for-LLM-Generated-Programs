# Phase 1 / Phase 2D quarantine guard, version 1

**Purpose:** Enforce the six provisional cross-partition development exclusions as an application-level safeguard, before supported Gemini-generation or development-evaluation entry points are invoked. This does **not** approve or freeze the split manifest, establish official correctness, or eliminate all possible data leakage.

## Source requirements

Install this package at the root of the existing research project, containing:

- `results/phase2d/splits.json` (currently draft)
- `results/phase2d/global_overlap_audit_v1/global_overlap_report.json`
- `results/phase2d/global_overlap_audit_v1/manual_review.json`
- `phase2d_global_overlap_audit.py`
- The existing Phase 1 and Phase 2D scripts

The package does not overwrite any of those evidence/data files. The guard independently checks all 3,333 current public task IDs and prompt hashes, the current SHA256 of the split manifest and four public data files, the lexical report SHA256, the six reviewed pair identities, and the six quarantine IDs. If evidence is missing/stale/inconsistent, **all generation and execution requests fail closed** in the patched entry points.

## Installation (Mac VS Code terminal)

From `/Users/jo/projects/Research`, after downloading `phase2d_quarantine_guard_v1.zip`:

```bash
unzip -n ~/Downloads/phase2d_quarantine_guard_v1.zip -d .
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_quarantine_*.py' -v
.venv/bin/python phase2d_install_quarantine.py --check
```

Inspect the preflight output. Only if it shows expected `READY TO PATCH` / `ALREADY PATCHED` results:

```bash
.venv/bin/python phase2d_install_quarantine.py --apply
.venv/bin/python phase2d_quarantine_check.py
.venv/bin/python -m compileall -q phase1_generator.py phase1_advanced.py phase2d phase2d_cli.py phase2d_bcb854_cli.py phase2d_strategy_cli.py phase2d_replay.py phase2d_shrink_cli.py
```

The installer always preflights all installed target files, requires an exact one-time match for each insertion anchor, verifies syntax of candidate edits, makes a timestamped backup of every modified file inside `results/phase2d/patch_backups/`, and verifies the changes. It does not change the task manifest, review record, datasets, or generated candidates. Rerunning `--apply` is idempotent (no-op) if already patched. If the preflight fails, **do not manually force the patch**; report the missing anchor/file.

## Enforcement policy

- Six quarantined development IDs: `MBPP/779`, `MBPP/883`, `MBPP/935`, `MBPP/534`, `MBPP/922`, `BigCodeBench/895`.
- Under the existing **draft** split: only three previously established development pilots (`HumanEval/0`, `HumanEval/1`, `MBPP/545`) are allowed for supported **non-dry-run generation/evaluation**. All other development tasks remain blocked until a reviewed split policy is established. They may still be inspected with read-only tools.
- Validation, held-out and temporal-pending tasks are never allowed for iterative generation/evaluation by this guard.
- A future change from draft to frozen invalidates the recorded review hashes and therefore blocks all tasks until a new, documented audit reconciliation is performed; **do not regenerate or edit the review record just to bypass the guard**.
- The reviewed BigCodeBench/854 development suite remains installed, but **its candidate execution stays blocked while the manifest is draft**.

## Patched enforcement points

- Phase 1: `phase1_generator.py`, `phase1_advanced.py` (check after dry-run and before any LLM call)
- Phase 2D: `phase2d_cli.py`, `phase2d/engine.py` (protects direct calls to the unified evaluate function), `phase2d_bcb854_cli.py`, `phase2d_strategy_cli.py`, `phase2d_replay.py`, `phase2d_shrink_cli.py`
- If present: `phase2d_bcb146_mock.py`

**Scope limitations:** This is an application-level guard for the listed entry points. It cannot stop arbitrary ad-hoc scripts, direct calls to a low-level Docker sandbox, newly added generator scripts, legacy standalone scripts, or external model API invocations. Any future batch controller, repair loop, or training script must call `require_task_permission(ROOT, task_id, intent)` at its own trust boundary. To enforce a universal guarantee across all code paths, move authorization into a common runtime service and disable legacy direct runners; that architecture is not implemented by this patch.

## Safe verification

```bash
.venv/bin/python phase2d_quarantine_check.py
```

This script does not contact Gemini, open private tests, execute generated code, run Docker, or modify task files. Expected output includes `QUARANTINE BLOCKS: 12 of 12`, `EXISTING PILOT PERMISSIONS: 3 of 3`, and that BigCodeBench/854 is blocked under the draft manifest.

## Research interpretation

The source review classifies two pairs as equivalent public specifications, three as near-equivalent solution-transfer risks, and one as needing contract review. The guard's six-task exclusion is **conservative**, not a finding that all six have identical official behavior. The original `manual_review.json` remains provisional as a historical evidence record; after installation the application guard enforces its proposed exclusions. No new official benchmark score or generalization claim follows from these changes.
