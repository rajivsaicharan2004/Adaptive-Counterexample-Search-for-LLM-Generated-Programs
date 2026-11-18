# Phase 2F: Restricted development starter V1

This is a **research-development kit**, not a completed Phase 2 experiment.
Its scripts are designed to be placed in the root of your existing `Research`
project. It must **not** modify the original V3 guard, the manifest, the prior
review records, validation, held-out, or temporal-pending tasks.

## Scope

Selected for the initial batch: HumanEval/129, /69, /112, /90, /111, /74,
/148, /150. HumanEval/132 and /91 are *conditional* and not included. MBPP
remains excluded pending full-contract review.

Each task has two handwritten oracle algorithms and 128 deterministic,
unique development inputs. Tuple values are JSON-encoded as arrays while
preserving their original Python runtime type in label metadata.

**No independent human review has occurred.** Two algorithms written by one
assistant can share mistakes. Tests cover explicitly bounded development domains;
they do not prove correctness on the full specifications.

## 0. Install package (Mac terminal)

Download `phase2f_dev_starter_v1.zip`, place it in `~/Downloads`, then:

```bash
cd /Users/jo/projects/Research
unzip -n ~/Downloads/phase2f_dev_starter_v1.zip
```

The ZIP contains Python scripts at its top level. The `-n` flag refuses to
replace existing files. It does not write into original `results/phase2d/`.

It expects the pre-existing modules `phase2d_quarantine_guard.py`,
`phase2a_validator.py`, `phase2e_smoke_v1.py`, `phase1_generator.py`, and the
original unchanged `data/public/` files. It also expects these two previous
artifacts under `results/phase2d/`:

- `restricted_development_eligibility_proposal_v1.json`
- `phase2d_restricted_development_technical_feasibility_review_v1.json`

## 1. Run trusted offline checks

```bash
.venv/bin/python phase2f_offline_unit_tests_v1.py
.venv/bin/python phase2f_prepare_dev_suite_v1.py --preview
```

The first command does not require the dataset. The second verifies the
original dataset, all original V3 review evidence, prompt hashes, and original
split. Expected: eight tasks, 1,024 inputs, two agreeing handwritten oracles
on every input, and more than 20,000 small-domain self-checks.

## 2. Freeze development challenge inputs BEFORE evaluating any candidate

```bash
.venv/bin/python phase2f_prepare_dev_suite_v1.py --build
.venv/bin/python phase2f_prepare_dev_suite_v1.py --verify
.venv/bin/python phase2f_mutant_calibration_v1.py --from-frozen
```

The builder refuses to overwrite `results/phase2f/dev_inputs_frozen_v1.json`
or `results/phase2f/dev_dual_oracle_labels_v1.json`. Labels are in a separate
file. Preserve the printed SHA-256 hashes. If either script/source file changes,
stop and version a new challenge; do not silently change a frozen input set.
Calibration tests deliberately faulty *handwritten* implementations only.
Do not describe the control results as failures of real LLM programs.

## 3. Research owner attestation (explicit choice)

Before model calls, the research owner reviews the technical limitations and
creates an **inactive** attestation template:

```bash
.venv/bin/python phase2f_scope_gate_v1.py --template
.venv/bin/python phase2f_scope_gate_v1.py --check
```

The second command should **fail closed** while the template is inactive.
The owner may choose to authorize this *limited development-only experiment*
by manually completing the attestation JSON at
`results/phase2f/owner_scope_attestation_v1.json`:

- Change `authorization_granted` to boolean `true` only after reviewing scope.
- Set a real `reviewer_identity` (research owner identity; not a fictitious professor).
- Set `review_date_utc` to a timezone-aware ISO-8601 timestamp.
- Enter the following acknowledgement **exactly** as the JSON string value
  for `exact_scope_acknowledgement`:

> I authorize this eight-task development-only experiment under a self-attested research protocol; independent human review and clean held-out generalization have not been established.

All other fields are locked, including the selected task IDs, challenge file
hashes, original manifest hash, and disallowance of validation/held-out/temporal
work. This is a **new V4 researcher-attested scope**, *not* a change to or approval
from original V3. V4 re-verifies V3 provenance and quarantines on every request.
For publication, disclose the scope-extension choice and its limitations.

After explicit owner review:

```bash
.venv/bin/python phase2f_scope_gate_v1.py --check --task-id HumanEval/69
.venv/bin/python phase2f_guarded_candidate_eval_v1.py --preflight
```

The second command checks all eight permissions and the frozen evidence, but
still executes no model-generated code or Docker container.

## 4. Generate real candidate programs (paid API calls)

The existing `.env` must contain a working `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
Never paste API keys into the terminal output or a research artifact.

```bash
.venv/bin/python phase2f_generate_development_v1.py --task-id HumanEval/69 --method direct --candidates 1 --max-calls 1 --dry-run
.venv/bin/python phase2f_generate_development_v1.py --task-id HumanEval/69 --method direct --candidates 1 --max-calls 1
```

Model/generated-code files are saved under `generated/phase2f/HumanEval_69/`.
They are **never executed during generation**. Capture model identifiers,
method, raw source hash, provider token counts and API call costs. Run more
methods/seeds/tasks as appropriate, always using predeclared budgets.

## 5. Test genuine generated candidates ONLY inside the established Docker

```bash
.venv/bin/python phase2f_guarded_candidate_eval_v1.py --run --task-id HumanEval/69
```

This rechecks the owner scope and original V3 source evidence before execution,
then runs generated code using `phase2a_validator.docker_execute()` in the
original pinned, restricted Docker sandbox. It preserves syntax failures and
marks code-hash duplicates separately. An observed failure is re-run once.
Report generation-level success, observed development failures, and infrastructure
failures separately.

## 6. Actual completion requirements for Phase 2

The following are NOT completed merely by installing this package:

1. Generate a sizable, diverse sample of real LLM programs across the eight tasks,
   with model/method/seed provenance and predeclared budgets.
2. Verify actual, reproducible counterexamples inside pinned Docker and distinguish
   wrong-answer/exception/timeouts from infrastructure failures.
3. Run fixed property, mutation, differential, and metamorphic baselines under
   clearly defined comparable costs, with multiple independent candidates/tasks.
4. Freeze, audit and report costs, unique failures, success denominators, failures
   of oracles, and confidence/variation by task.
5. Decide whether the resulting real-failure corpus is sufficient for training a
   controller; otherwise extend authorized development scope with a new version.

No generalization claim is permitted from these development-only experiments.
The whole 3,333-task draft dataset is not considered frozen by this package.

## Research methodology references

- Chen et al. (2021), Evaluating Large Language Models Trained on Code (HumanEval).
- Liu et al. (2023), EvalPlus.
- Chen et al. (2023), CodeT.
- Claessen and Hughes (2000), QuickCheck.
- Klees et al. (2018), Evaluating Fuzz Testing.
- Zeller et al., The Fuzzing Book.

