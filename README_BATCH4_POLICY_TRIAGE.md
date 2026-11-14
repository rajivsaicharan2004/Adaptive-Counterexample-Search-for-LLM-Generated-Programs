# Phase 2D — Batch 4 policy triage (provisional)

**Purpose:** preserve the user's existing V3 quarantine, critically prioritize the 81 sampled overlap leads, and document the HumanEval/1 vs HumanEval/6 pilot conflict before formal split freeze. This **does not** automatically quarantine 21 more tasks.

## Inputs (must already exist in the VS Code project)

- `results/phase2d/global_overlap_stratified_v1/random_stratified_review.csv` (the exact 81-row export)
- `results/phase2d/global_overlap_stratified_v1/manual_review_batch4_provisional.json` (the copied provisional record)
- `results/phase2d/global_overlap_stratified_v1/stratified_overlap_summary.json`
- `phase2d_stratified_review_batch4/phase2d_verify_sample_review_batch4.py` (the original read-only source verifier)
- The installed V3 `phase2d_quarantine_guard.py` and unchanged source/manifest/reviews required for its own verification.

## Run

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_batch4_policy_triage_v1.zip -d .
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_batch4_policy_triage.py' -v
.venv/bin/python phase2d_batch4_policy_triage.py
```

The default run is **read-only**. It verifies the exact original sample/review hashes, every full public prompt and partition against the validated manifest, the 81-row review, original sampling summary, current V3 guard and prior quarantines, and pilot set. If any required evidence has changed, it refuses to proceed.

If the check succeeds, export a new evidence-only report:

```bash
.venv/bin/python phase2d_batch4_policy_triage.py \
  --export-dir results/phase2d/global_overlap_stratified_v1/batch4_policy_triage_v1
```

The export is exclusive and refuses to overwrite an existing directory. Four output files:

- `batch4_policy_triage_summary.json` — evidence hashes, review counts and limitations.
- `development_second_review_queue.csv` — 21 development partners, 13 priority / 8 secondary.
- `validation_heldout_watchlist.csv` — 14 validation-to-held-out related pairs (two preliminarily equivalent).
- `pilot_generalization_notice.txt` — why historical HumanEval/1 pilot results do not establish independent evidence on HumanEval/6.

## Risk triage and evidence standards

The exact two task pairs initially judged equivalent are both **validation ↔ held_out**: HumanEval/59 ↔ MBPP/32, MBPP/263 ↔ MBPP/821. No equivalent pair in this sample newly touches development. Twenty-one development IDs occur in **near-equivalent** pair reviews, hence need independent adjudication before V4. Initial ranking for that adjudication is **13 priority** and **8 secondary**; tier assignments are conservative *triage opinions*, not independently replicated semantic judgments.

- **Priority review**: substantial shared task-specific program skeleton or nearly trivial transformations; a pilot exception needs special handling.
- **Secondary review**: generic reused libraries, repeated workflow motif, or significant input/output differences; may require only documentation rather than quarantine.

The historical pilot HumanEval/1 remains permitted in the current V3 policy. Keep previous pilot artifacts labeled **exploratory**, but do not use HumanEval/6 as independent evidence for choices developed or tuned using HumanEval/1 before a documented adjudication.

The precise total of **21 development candidates** is not an additional automatic V3 quarantine total. No new permissions are granted and no original guard is patched.

## Limitations / next gate

The sampled 81 pairs were selected from the previously screened lexical-candidate frame, not all possible pairs. Additional 14 priority leads and 14 previously reviewed leads are separate; do not pool raw percentages. This is **one provisional semantic review**, not blinded independent agreement. A separate reviewer (e.g., supervising professor) should check the prioritized pairs, explicit I/O specifications and test contracts, and then approve a grouping/exclusion policy. Only after that should the team implement a guarded partition-freeze process and a statistically fair baseline evaluation.

Only public prompts and audit metadata are accessed. **No LLM API calls, network, candidate execution, Docker runs, private tests, or files in `data/private/`**.
