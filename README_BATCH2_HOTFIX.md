# Phase 2D batch-2 review: targeted MBPP/699 prompt hotfix

This hotfix changes only the second-review recorder and its regression tests.
The existing draft split manifest, first review, exported lexical audit,
private tests, candidate files, and installed quarantine guard are untouched.

The upstream MBPP/699 public prompt can contain the fused word `toanother`.
The review recorder originally checked an exact substring and could reject
this unchanged prompt. The corrected checker normalizes **only that specific
known typo in MBPP/699**; it still verifies all 3,333 public task IDs,
prompt hashes, audited pair IDs, partitions, entry points, and the previous
review's evidence. It does NOT silently change source data.

## Installation from Downloads (Mac)

Run from the research project root, after extracting the original v2 archive:

```bash
cd /Users/jo/projects/Research
unzip -o ~/Downloads/phase2d_batch2_prompt_hotfix.zip -d .
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_quarantine*.py' -v
.venv/bin/python phase2d_record_manual_overlap_batch2.py
```

Expected: 27 tests pass. The second recorder should report eight reviewed
pairs in read-only mode.

Only after this succeeds:

```bash
.venv/bin/python phase2d_record_manual_overlap_batch2.py --write
.venv/bin/python phase2d_apply_quarantine_v2.py --check
```

Then, **only if preflight succeeds**, continue with the original v2
instructions: `--apply`, quarantine self-check, and regressions.

The hotfix does NOT edit any manifest partitions, grant evaluation permissions,
execute candidate code, use private tests, Docker, or make network calls.
