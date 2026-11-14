# Global public-task lexical near-duplicate screening (development audit)

## Purpose

This utility reviews **all 3,333 public task records** across HumanEval (164), MBPP (974), BigCodeBench (1140), and LiveCodeBench (1055), against `results/phase2d/splits.json`. It is an offline candidate-finding step before manual semantic review, **not an automated semantic duplicate detector**.

It fails closed on a missing task, duplicate task ID, incorrect dataset tag, or a mismatch between a raw public prompt's normalized SHA-256 and the draft manifest's `public_prompt_sha256`. No private files or hidden tests are accessed.

### Install in VS Code

Extract the archive into `/Users/jo/projects/Research/` (it contains only a new script, test, and README).

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_global_overlap_audit.zip -d .
.venv/bin/python phase2d_global_overlap_audit.py --self-test
.venv/bin/python -m unittest discover -s tests -p 'test_phase2d_global_overlap_audit.py' -v
```

### Run the full read-only screen

```bash
.venv/bin/python phase2d_global_overlap_audit.py --top 80 --same-top 25
```

Default mode **writes nothing**. You will see public task counts, manifest status, exact normalized-prompt groups, cross-partition lexical review leads, and separate same-partition leads.

### Export reproducible review files (optional)

```bash
.venv/bin/python phase2d_global_overlap_audit.py \
  --top 200 --same-top 50 --per-dataset-pair 15 \
  --export-dir results/phase2d/global_overlap_audit_v1
```

This writes **only three new report files** under the chosen results directory:
- `global_overlap_report.json` (input SHA-256 fingerprints, settings, exact-duplicate groups, ranked leads, limitations)
- `global_overlap_cross_partition.csv` (manual review queue, initial `verdict` blank)
- `global_overlap_same_partition.csv` (additional review queue)
- `global_overlap_cross_dataset.csv` (stratified cross-dataset, cross-partition leads so one dataset does not dominate the global ranking)

Existing files are *never overwritten*. Use a different output directory for another run. No dataset, candidate, split manifest, or source file is modified. No model, Docker, or network access is needed.

### Interpretation

1. **Exact normalized prompt** = lowercase and whitespace-normalized identical public prompt. This is deterministic evidence of prompt duplication, not proof of identical hidden tests.
2. **Lexical candidate** = an IDF-weighted token/bigram overlap, retrieved through a sparse inverted index. It is a **lead** for manual inspection, not a finding of semantic equivalence. `char_5gram_jaccard` provides a second *descriptive* similarity signal.
3. **Cross-partition** = different manifest partition labels; `held_out_temporal_pending` is treated as a separate provisional protected partition.
4. Pair scores and score thresholds are heuristics. Different wording, changed variable names, code-only similarities, and task translations can escape detection. A low score does not establish non-duplication.
5. Exact duplicate groups are shown **regardless of lexical candidate thresholds**, avoiding accidental suppression of common vocabulary pairs.
6. Before approval, human reviewers should inspect the highest-ranked cross-partition leads, a sample of low-scoring pairs, and any cross-dataset high-overlap cases. Record task IDs, evidence, decision, reviewer, and rationale in a separate reviewed decision log; do not modify the manifest based on scores alone.

### Scope that remains open after this screen

- Manual semantic review of flagged pairs, including cross-dataset task formulations and code structure; optional embedding-based retrieval later for semantic paraphrases (a local offline model only after approved inputs/provenance).
- Exact source-to-prepared-record verification for LiveCodeBench's pinned Hugging Face revision.
- Contest-date normalization policy documented separately, including timezone-naive date-only records.
- Approved split policy and only then a deliberate manifest freeze. This tool cannot freeze or approve partitions.
- No claims of data being absent from any language model's training set.
