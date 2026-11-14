# Phase 2D — Manual overlap batch 2 + quarantine guard v2

## Scope

This package adds an **eight-pair provisional public-prompt review** while keeping the existing six-pair review unchanged, then upgrades the shared task guard to quarantine **13 development tasks** (six previous + seven additional). The MBPP/440–584 validation/held-out pair remains a watchlist finding; those tasks are blocked by their non-development partitions.

The package does **not** modify the task split manifest, public datasets, private tests, existing audit reports, or candidates; it cannot authorize evaluation of BigCodeBench/854 or held-out tasks. The previous v1 entry-point hooks stay in place and call the upgraded shared policy. The installer updates exactly three files: `phase2d_quarantine_guard.py`, `phase2d_quarantine_check.py`, and `tests/test_phase2d_quarantine_guard.py` (the legacy tests' fixture is updated to include batch 2). It creates timestamped verified backups and blocks on unexpected local edits.

Important: This is an *application-level* guard on previously installed hook points, not a universal runtime security boundary. Legacy/new scripts or direct low-level runtimes require their own authorization integration.

## Installation from Downloads (Mac)

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_quarantine_guard_v2.zip -d .
```

**1. Verify the second public-specification review, read-only:**

```bash
.venv/bin/python phase2d_record_manual_overlap_batch2.py
```

The command must report eight reviewed pairs, seven new proposed development exclusions, and the MBPP/440 ↔ MBPP/584 watchlist. It must verify the *existing* `global_overlap_report.json` and `manual_review.json` against the draft split and all prepared public task hashes. On failure do not continue.

**2. Create only the new batch-2 record (exclusive-create):**

```bash
.venv/bin/python phase2d_record_manual_overlap_batch2.py --write
```

Creates `results/phase2d/global_overlap_audit_v1/manual_review_batch2.json`. If it already exists, creation refuses to overwrite; do not delete or regenerate records just to get the guard to pass.

**3. Inspect the v2 change before applying, read-only:**

```bash
.venv/bin/python phase2d_apply_quarantine_v2.py --check
```

This requires the eight-pair review and the original six-pair evidence. It verifies existing v1 hooks, the two source guards, and all thirteen quarantined IDs (generation + evaluation) before any writes. It expects exactly three `READY TO UPGRADE` entries if the original verified v1 files are present, or `ALREADY V2` entries after successful installation.

**4. Apply the verified upgrade and run tests:**

```bash
.venv/bin/python phase2d_apply_quarantine_v2.py --apply
.venv/bin/python phase2d_quarantine_check.py
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_quarantine*.py' -v
```

Expected from the self-check:

```text
QUARANTINE BLOCKS: 26 of 26
EXISTING PILOT PERMISSIONS: 3 of 3
BCB/854 CURRENT POLICY: BLOCKED ... manifest is still draft
GUARD SELF-CHECK PASSED.
```

The last unittest command should report 23 passing synthetic tests for the guard versions; other tests in your project are unaffected. No generated candidate is executed by any step.

## Reviewed pairs and actions

| Development task | Corresponding validation / held-out task | Provisional classification |
|---|---|---|
| MBPP/439 | MBPP/673 (held-out) | Likely equivalent |
| MBPP/933 | MBPP/965 (held-out) | Near-equivalent |
| MBPP/43 | MBPP/16 (held-out) | Near-equivalent |
| MBPP/178 | MBPP/186 (held-out) | Contract needs review |
| MBPP/970 | MBPP/404 (held-out) | Likely equivalent |
| MBPP/569 | MBPP/104 (validation) | Near-equivalent |
| MBPP/595 | MBPP/699 (held-out) | Likely equivalent |
| None | MBPP/440 (validation) ↔ MBPP/584 (held-out) | Near-equivalent; watchlist only |

The first six development exclusions remain `MBPP/779`, `MBPP/883`, `MBPP/935`, `MBPP/534`, `MBPP/922`, and `BigCodeBench/895`.

## Evidence and safeguards

- Requires 3,333 prepared public task IDs and hashes to match `splits.json`.
- Requires the previous immutable six-pair review, and the pinned global lexical report; hashes are checked on every permission request.
- Requires the second review's eight exact pair IDs, their partitions, their normalized prompt hashes, lexical scores, and the seven proposed quarantine IDs.
- Prevents the watchlist pair from being misrepresented as a *development*-quarantined ID.
- Unrecognized or missing evidence fails closed, including missing batch 2 after upgrade, source edits, and manifest freeze without reconciled evidence.
- Keeps existing pilot exceptions `HumanEval/0`, `HumanEval/1`, and `MBPP/545` during the draft stage.
- No new BigCodeBench/854 candidate execution is authorized.

The tests and installer smoke check used synthetic data only. The actual files on your Mac are verified when you run the commands above. Do not force an upgrade if the v1 file hashes or hook checks differ; share the error instead.
