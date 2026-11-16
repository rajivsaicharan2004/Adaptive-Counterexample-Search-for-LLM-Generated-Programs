# Phase 2D restricted development selection closure V1

**Purpose**: Close only the eight-task, self-attested **development selection** milestone, not the global 3,333-task partition freeze. The original V3 guard and draft split remain unchanged. This closure authorizes **no** model calls, program execution, validation, held-out access, or temporal benchmark use.

## Install

Download `phase2d_restricted_closure_v1.zip`, then on your Mac:

```sh
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_restricted_closure_v1.zip
```

The ZIP contains the closure script plus two previously produced, SHA-pinned technical-review documents. It does not replace your source files (`unzip -n`). The script also expects the already-created Phase 2D eligibility proposal, 24-task contract packet, review addenda, original dataset files, unchanged V3 guard, and `phase2d_restricted_development_eligibility_v1.py` in your project.

## Run the five-step closure gate

1. **Preview (read-only)**

   ```sh
   .venv/bin/python phase2d_close_restricted_scope_v1.py --preview
   ```

   This calls the verified V3 dataset/review chain, recomputes the 264-edge precautionary eligibility screen, and checks the eight frozen task IDs and prompt hashes. Missing or stale artifacts halt it. It does not write files.

2. **Create the inactive owner form** (new file only)

   ```sh
   .venv/bin/python phase2d_close_restricted_scope_v1.py --prepare
   ```

   Creates `results/phase2d/restricted_dev_owner_attestation_v1.json` with `owner_accepted=false` and no execution permissions.

3. **Explicit solo-researcher attestation** (only owner form updated)

   ```sh
   .venv/bin/python phase2d_close_restricted_scope_v1.py --attest
   ```

   Read the risk statement and enter your actual name and the exact confirmation phrase when asked. This records researcher self-attestation, *not* an independent human review. You can alternatively edit the four documented owner fields in the JSON manually; the gate refuses any modification to locked fields.

4. **Immutable scoped selection freeze** (new file only)

   ```sh
   .venv/bin/python phase2d_close_restricted_scope_v1.py --finalize
   ```

   Creates `results/phase2d/restricted_dev_scope_closure_v1.json`. Re-running `--finalize` refuses overwrite.

5. **Read-only end-to-end verification**

   ```sh
   .venv/bin/python phase2d_close_restricted_scope_v1.py --check
   ```

   Expected: `SCOPED PHASE 2D COMPLETION CHECK: PASS`. Keep the printed closure SHA-256 for your paper's provenance appendix.

## Exact task scope

Approved for **development selection only**: `HumanEval/129`, `/69`, `/112`, `/90`, `/111`, `/74`, `/148`, `/150` (all eight are in the original development partition and not in the original 21 quarantines). `HumanEval/132` and `/91` remain conditional and not in this scope. MBPP and BigCodeBench are not included in this phase's selected execution batch. All LiveCodeBench temporal tasks remain excluded.

## What remains open

- The global manifest is still `draft_requires_review_and_freeze`, and this program does **not** claim to freeze it.
- The original V3 guard continues to authorize only the old pilot tasks. The scoped selection record does not silently extend V3.
- Pretraining contamination, unreviewed semantic overlaps, and temporal provenance are unresolved; clean held-out claims require a separate global policy gate.
- Oracle verification, frozen challenge generation, synthetic mutant calibration, secure Docker and real-model experiments belong to Phase 2F.
- The separate Phase 2F V4 scope gate requires its own explicit owner attestation and verified oracle evidence before generated programs can be evaluated. This Phase 2D attestation does not grant those permissions.

**Scientific status**: Self-reviewed restricted development selection is closable. Independent human-reviewer agreement and global held-out split integrity are **not** established.
