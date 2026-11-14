# Batch 4 sample-source reconciliation — V1

The reviewed source snapshot is the *exact 81-row uploaded CSV text* from the review, verified as SHA-256:

`48a98d45721a40f9da34b31572dbc82cd3e22b2e21d59ef9cba807669d3c5462`

The existing Batch 4 provisional review pins that digest. The CSV currently in the user's project has different raw bytes. This package diagnoses differences without guessing their cause. There is **no change** to the triage/guard code, review records, manifests, candidates or private tests.

## Read-only check

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_batch4_source_reconciliation_v1.zip -d .
.venv/bin/python phase2d_batch4_source_reconciliation_v1/reconcile_batch4_source.py
```

This authenticates both the uploaded source snapshot and existing Batch 4 review record, uses the existing review verifier, and compares all 26 fields in all 81 rows, including prompts, order, and sampling metadata.

- **CSV CONTENT MATCHES**: the current local CSV has the exact same parsed rows, but potentially different CSV quoting/newline serialization. The original bytes can be safely restored with an automatic backup.
- **CSV CONTENT DIFFERS**: prints the first changed fields and refuses any restoration. Stop and inspect those differences; don't replace the dataset or edit the review record.

## Optional explicit restoration after CONTENT MATCHES

```bash
.venv/bin/python phase2d_batch4_source_reconciliation_v1/reconcile_batch4_source.py --restore-reviewed-bytes
```

Only if every field matches, back up the original CSV to `results/phase2d/global_overlap_stratified_v1/source_reconciliation_backups/backup_<timestamp>_<sha>/`, with its SHA-256 manifest, then atomically replace **only** the sample review CSV with the exact uploaded bytes already reviewed. The operation refuses any field changes or changed review records. It never overwrites the backup. The user can restore the backed-up original if needed.

## Check the inherited triage and tests

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_batch4_policy_triage.py' -v
.venv/bin/python phase2d_batch4_policy_triage.py
```

Expect the existing 21 tests to pass if there are no unrelated environment issues. Export triage only after both checks pass; this is still **provisional**, not split approval.

If the source differs by field content, share the diagnostic summary only; do not run the restoration option.
