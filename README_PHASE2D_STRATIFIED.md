# Phase 2D global overlap: reproducible stratified review

**Scope:** Prepared PUBLIC prompts only. This package does not modify `splits.json`,
public datasets, existing overlap reports, candidate code, the shared quarantine
policy, or private evaluation data. No model calls, Docker, or networking.

## Why this tool exists

The previous audit's `--top 200` export contains only 200 of 4,635
cross-partition lexical leads; the audit CLI caps `--top` at 2,000. This
sampler imports the already installed `phase2d_global_overlap_audit.py` and
reruns its same public-data lexical retrieval to obtain the **complete screened
cross-partition population** before sampling. It checks the dataset/manifest
hashes, global report, exact prompt groups and both manual-review records.

It excludes all 14 previously reviewed high-priority pairs. The results are:

1. **Priority census:** all remaining score >=0.65 leads, not automatically
   labeled duplicates.
2. **Fixed-seed stratified random queue:** up to three cases in each nonempty
   dataset-pair x partition-pair x lexical-score-band group below 0.65.
   The score bands are `[.12,.20)`, `[.20,.35)`, `[.35,.50)`, `[.50,.65)`.

The sampling fraction n/N is for the specific nonpriority lexical-candidate
stratum, not for all task pairs, all semantic duplicates, or LLM training data.
Some relevant pairs have very different words or no shared rare features and
will never appear in this lexical retrieval; semantic retrieval and blind
controls should be separate later work.

## Install

Download ZIP, then in your Mac's VS Code terminal:

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_stratified_overlap_v1.zip -d .
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_stratified_overlap_sampling.py' -v
.venv/bin/python phase2d_stratified_overlap_sampling.py --self-test
```

The existing `phase2d_global_overlap_audit.py` must be in your project root.

## Dry-run (reads public data, no files written)

```bash
.venv/bin/python phase2d_stratified_overlap_sampling.py --seed 2026 --per-stratum 3
```

The output should include `cross_partition_lexical_leads_above_threshold: 4635`
and `already_manually_reviewed: 14`. If not, the tool fails closed or reports
a discrepancy; do not write/approve a new review until investigated.

## Export new, non-overwriting review queues

```bash
.venv/bin/python phase2d_stratified_overlap_sampling.py \
  --seed 2026 --per-stratum 3 \
  --export-dir results/phase2d/global_overlap_stratified_v1
```

Creates (no overwrite):

- `stratified_overlap_summary.json`: source hashes, counts, limitations,
  configuration, original review hashes.
- `priority_manual_review.csv`: all unreviewed high-score leads with complete
  PUBLIC prompt text and blank reviewer verdict/notes.
- `random_stratified_review.csv`: fixed-seed sample with complete PUBLIC prompt
  text, per-stratum N, n, and sample fraction.
- `stratum_inventory.csv`: counts and sampling fractions for each stratum.

**Important:** This does not approve tasks or enforce new quarantines. Any
confirmed potential leakage from the review must be recorded using the
separate manual-review policy and guarded before iterative experiments.

## Scientific interpretation

- The score threshold of 0.12 and inverted-index retrieval mechanism remain
  unchanged from the previous lexical audit.
- The 14 already reviewed pairs are explicitly excluded and tracked as a
  separate purposive-review set.
- Scores >=0.65 are reviewed as a priority census; the remaining candidate
  population is stratified and sampled reproducibly.
- No inference about unseen **semantic** duplicates across all ~5.5 million
  task pairs is valid from this sample alone.
- All `held_out_temporal_pending` assignments remain provisional.
- The manifest is not frozen; candidate execution remains blocked.
