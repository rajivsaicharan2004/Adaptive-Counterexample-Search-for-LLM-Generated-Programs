# Phase 2D — Manual Review Batch 3 + Quarantine Guard V3

This archive is a **provisional public-specification review and fail-closed task policy extension**, NOT a benchmark split approval or permission to execute candidate programs.

## What it changes

- Records the 14 **already researcher-reviewed** priority pairs in a **new** `results/phase2d/global_overlap_audit_v1/manual_review_batch3.json`, never overwriting `manual_review.json` or `manual_review_batch2.json`.
- Proposes eight **new** quarantined development IDs: `MBPP/591`, `MBPP/154`, `MBPP/504`, `MBPP/170`, `MBPP/402`, `MBPP/271`, `MBPP/770`, `MBPP/409`.
- Extends the existing V2 policy to **21 development tasks**, blocked for `generate` and `evaluate` intents (42 checks).
- Leaves all six Batch 3 validation-versus-held-out review pairs on a watchlist; these partitions are already blocked for iterative development by the shared guard.
- Retains the original 3 draft pilot exceptions (`HumanEval/0`, `HumanEval/1`, `MBPP/545`), and continues to block BigCodeBench/854 while the split manifest is draft.

## Installation (Mac VS Code)

From `/Users/jo/projects/Research`:

```bash
unzip -n ~/Downloads/phase2d_quarantine_guard_v3.zip -d .

# Run the recorder in preview mode; do NOT immediately write.
.venv/bin/python phase2d_record_manual_overlap_batch3.py

# Only if it confirms 14 priority pairs / 8 new development IDs:
.venv/bin/python phase2d_record_manual_overlap_batch3.py --write

# Verify the V2 source hashes and test ALL V3 policy decisions without editing code.
.venv/bin/python phase2d_apply_quarantine_v3.py --check

# Only if the check passes:
.venv/bin/python phase2d_apply_quarantine_v3.py --apply

# Regression tests and final self-check:
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_quarantine*.py' -v
.venv/bin/python phase2d_quarantine_check.py
```

Expected policy self-check after apply: **42/42 blocked checks**, **3/3 existing pilot permissions**, and BigCodeBench/854 **BLOCKED** under the draft manifest. The v3 test suite contains 17 new tests; combined V1/V2/V3 synthetic suites contain 44 tests in the packaged smoke environment.

## Safeguards

- Record creation uses exclusive file creation (`open('x')`): does not overwrite earlier reviews.
- V3 installer verifies actual source and review hashes, archived priority CSV and summary, original V2 hashes, existing hooked entry points, and the resulting V3 policy.
- Installer creates a new timestamped backup directory in `results/phase2d/patch_backups/quarantine_v3_<UTC time>` before replacing **only** the installed shared guard, checker, and one regression test that must use the V3 fixture.
- On installation failure after replacement begins, the installer restores the backed-up files. If a file has been edited since V2, the installer blocks rather than overwriting it.
- Old `phase2d_v2_sources` snapshots and their historical V2 regression test remain in place, verifying the historical V2 policy and its Batch 2 review unchanged.
- The new V3 fixture and new V3 tests are synthetic only; none executes an LLM-generated program, uses Docker or reads hidden tests.
- No manifest, public/private dataset, candidate, controller or original review file is edited by this upgrade.
- **Application guard limitation:** direct model SDK calls or unpatched evaluation scripts can bypass entry-point checks. This is not a system-wide security sandbox.

## Scope and research caveats

The fourteen classifications come from supplied public task descriptions, not official test oracles. Five are **likely equivalent**, seven **near-equivalent**, one **related but distinct**, and one **needs contract review**. These are provisional. All 81 lower-score stratified review leads remain unreviewed. The split manifest stays `draft_requires_review_and_freeze`; the quarantine is not a reason to freeze it.

## If a check fails

Do not run `--apply`. Do not forcibly overwrite V2. Inspect the error and compare the current project files against your last backup (`quarantine_v2_20261113T210347Z` was the user-reported V2 backup directory). V3 only works when the three pinned V2 files match the expected installed version.
