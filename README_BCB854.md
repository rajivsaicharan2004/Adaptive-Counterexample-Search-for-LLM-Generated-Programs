# BigCodeBench/854 — Phase 2D task-specific development adapter

**Research status: development proposal, not approved evaluation.**

This is a non-destructive overlay for the existing Phase 2D project. It does
not change `results/phase2d/splits.json`, private tests, model files, existing
candidate sources, or the general evaluator's BigCodeBench dependency blocker.
No Gemini API calls occur in this code.

## What you get

- `phase2d/bcb854.py`: independently derived bounded oracle (0–4 integers),
  exception and input rules, semantic comparator, strict Python-type comparator,
  and a conservative source inspection check. Not a security proof.
- `phase2d_bcb854_cli.py`: read-only review command; explicitly gated future
  development execution using the shared network-disabled Docker sandbox.
- `proposals/bcb854_review.json`: **16 proposed, UNREVIEWED** development cases.
  No hidden/official benchmark tests were used to create them. The proposal is
  *not* automatically promoted to a reviewed suite.
- `phase2d_tests/test_bcb854.py`: offline regression tests, including a tiny
  locally authored runner fixture (no generated candidate or network).
- `patches/bcb854_sandbox.patch`: opt-in `describe_types=True` feature. The
  existing default behavior for other tasks remains unchanged.

## Install and verify in your VS Code terminal

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2d_bcb854_adapter.zip -d .

# Verify patch compatibility BEFORE modifying the existing sandbox.
patch -C -p0 < patches/bcb854_sandbox.patch

# Only if the dry run succeeds; applies the small, opt-in runner change.
patch -p0 < patches/bcb854_sandbox.patch

.venv/bin/python -m compileall -q phase2d phase2d_bcb854_cli.py
.venv/bin/python -m unittest discover -s phase2d_tests -v
.venv/bin/python phase2d_bcb854_cli.py --review
```

`--review` **does not execute** generated code, invoke Docker, make Gemini
calls, access the network, or modify the manifest. It prints the current split
status, partition, and proposed-suite readiness. An existing project-local
sandbox that differs from the released Phase 2D version may not accept the
patch; **do not force the patch** or overwrite the file in that case.

## Evaluation design

The public task asks for factorial sums paired with all permutations of a
nonnegative-integer list. `[]` must yield two empty lists. The result order is
**(factorial sums, permutations)**. The example prints tuple permutations
but one part of the prose says list-of-list-of-int.

Two outcomes are therefore recorded separately:

- `semantic_pass`: accepts permutation values whether represented as tuples or
  lists (the sandbox JSON encoder makes these indistinguishable); compares a
  multiset of `(factorial_sum, permutation)` pairs, preserving duplicates but
  ignoring enumeration order.
- `strict_pass`: additionally requires trusted nested Python-type metadata:
  root tuple, first output list, second output list, each permutation a tuple.
  This is an *explicit exploratory representation policy*, **not** the official
  BigCodeBench grader.

The trusted runner optionally computes a bounded nested type tree **before**
serializing returned objects to JSON. It is opt-in via `describe_types=True`,
so other Phase 2D evaluation paths are unaffected.

Known, deliberately unresolved policy ambiguities:

- Tuple vs list representation for each permutation.
- Whether repeated-input permutations are compared with multiplicity. The
  proposed development policy uses position-based permutations, preserving
  duplicates, as in `itertools.permutations`.
- Whether Boolean values count as integers. Proposed tests **omit** boolean
  element inputs until that ambiguity is reviewed.
- Only JSON-serializable inputs are proposed. The existing sandbox cannot
  preserve a Python tuple **input** (as distinct from a JSON list), so the
  proposed negative-input suite does not test that distinction.

Both semantic and strict results must be reported. Neither is an official
benchmark score. The original public task prompt and its hash must be used
for any final approval; neither private tests nor the benchmark's reference
implementation should be imported into the development oracle.

## Important approval gate

The CLI intentionally **refuses** `--execute` until **all** are true:

1. Your manifest is `status: frozen` with this task in `development`.
2. You have manually reviewed and approved the proposed cases, including the
   representation ambiguities, and saved the reviewed suite at
   `data/development/bigcodebench/BigCodeBench_854.json` with
   `provenance: independently_reviewed_development`.
3. Candidate run directories are supplied explicitly.

Do **not** freeze the manifest just to run this pilot. Semantic near-duplicates
and authoritative LiveCodeBench timestamps remain open review items. The
`--execute` pathway is provided for later, not recommended now.

When the partition audit and suite review are genuinely complete, one future
example invocation is:

```bash
.venv/bin/python phase2d_bcb854_cli.py --execute \
  --runs generated/phase1/SOME_REAL_BigCodeBench_854_RUN --batch-size 10
```

No candidate generation command is intentionally provided here.

## Testing notes

Development verification in the builder environment: **29 unit tests**
passed or skipped (28 passed, 1 skipped because optional Hypothesis was not
installed), including original Phase 2D tests. The task's proposed cases,
comparator, static source check, opt-in type-tree runner behavior, and the
manifest execution guard were checked. No generated candidate was executed.
Actual candidate execution on the user's Mac has **not** been performed.
