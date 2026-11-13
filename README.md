# Adaptive Counterexample Search for LLM-Generated Programs

Research code for preparing programming benchmarks, generating candidate
Python solutions with language models, and running an initial Docker-isolated
development validation pilot. The current validation is limited to curated
HumanEval/0 development cases; it is not an official benchmark evaluation or
an adaptive counterexample search.

GitHub repository:
[rajivsaicharan2004/Adaptive-Counterexample-Search-for-LLM-Generated-Programs](https://github.com/rajivsaicharan2004/Adaptive-Counterexample-Search-for-LLM-Generated-Programs)

## Current status

- Four benchmark datasets are prepared: HumanEval, MBPP, BigCodeBench, and
  LiveCodeBench release v6.
- The combined public problem file contains 3,333 records.
- `scripts/` contains the original multi-provider sample generator and the
  benchmark-preparation scripts.
- [`phase1_generator.py`](./phase1_generator.py) generates Gemini candidates
  using direct, sampling, diverse, or plan-then-code prompting.
- The Phase 1 generator records prompts, candidate code, request metadata,
  token usage when returned by the API, and static syntax/interface checks.
- [`phase2a_validator.py`](./phase2a_validator.py) can execute selected
  HumanEval/0 candidates inside a resource-limited Docker container against
  manually curated development cases.
- Full benchmark evaluation and adaptive counterexample search remain future
  work.

### Initial Phase 1 experiment: HumanEval/0

Local run manifests currently record the following results:

| Method | Candidates generated | Static checks passed |
| --- | ---: | --- |
| Direct | 1 | 1 |
| Sampling | 5 | 5 |
| Diverse | 5 | 5 |
| Plan-then-code | 6 across two runs | 6 |
| **Total** | **17** | **17** |

An earlier direct request returned a temporary Gemini `503 UNAVAILABLE`;
another direct request succeeded. Four initial sampling requests also returned
503 errors, and were later resumed successfully. These counts describe
generation and static checks only—not functional correctness. Experiment
artifacts are in the local, Git-ignored `generated/` directory and are not
published in this repository.

## Repository layout

```text
.
├── data/
│   ├── development/           # Reviewed, non-held-out development cases
│   └── public/
│       ├── humaneval.jsonl
│       ├── mbpp.jsonl
│       ├── bigcodebench.jsonl
│       ├── livecodebench.jsonl
│       └── problems.jsonl
├── scripts/
│   ├── prepare_problems.py
│   ├── add_bigcodebench.py
│   ├── add_livecodebench.py
│   └── model_generator.py
├── phase1_generator.py
├── phase2a_validator.py
├── phase2b1_validator.py
├── phase2b2_mutation.py
├── phase2b3_differential.py
├── phase2b4_metamorphic.py
├── phase2b5_fault_benchmark.py
├── requirements.txt
└── .env.example
```

Local-only paths are excluded from Git:

- `.env` stores API credentials.
- `.venv/` stores the Python environment.
- `data/raw/` stores original benchmark downloads.
- `data/private/` stores reference solutions and evaluation tests.
- `data/development/` stores reviewed development cases used by the validator.
- `generated/` stores generated candidates, prompts, and run metadata.
- `results/` stores local Phase 2A development reports.

The public benchmark JSONL files are tracked in this repository. Check each
benchmark's license and terms before redistributing or using it outside this
research project.

## Setup

Use Python 3.11 or newer. From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Add credentials for the providers you intend to use to `.env`:

```dotenv
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
```

The Phase 1 Gemini generator accepts `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
You may optionally set `GEMINI_MODEL`; otherwise it defaults to
`gemini-3.8-flash`. Never commit `.env`, put credentials in source code, or
paste credentials into chat.

Always use the project environment for commands, for example:

```bash
.venv/bin/python phase1_generator.py --help
```

An unactivated system `python3` may not have the packages installed.

## Benchmark datasets

| Dataset | Records | Source / version |
| --- | ---: | --- |
| HumanEval | 164 | [openai/human-eval](https://github.com/openai/human-eval) |
| MBPP | 974 | [google-research/MBPP](https://github.com/google-research/google-research/tree/master/mbpp) |
| BigCodeBench | 1,140 | Hugging Face `bigcode/bigcodebench`, config `v0.1.4` |
| LiveCodeBench | 1,055 | [livecodebench/code_generation_lite](https://huggingface.co/datasets/livecodebench/code_generation_lite), release v6 |
| **Combined** | **3,333** | `data/public/problems.jsonl` |

Each public record has a dataset and task identifier, a prompt, and available
interface or metadata fields. The per-dataset files and combined file use
JSON Lines: one JSON object per line.

### Prepare or rebuild the data

Run these commands from the repository root, in order:

```bash
.venv/bin/python scripts/prepare_problems.py
.venv/bin/python scripts/add_bigcodebench.py
.venv/bin/python scripts/add_livecodebench.py
```

`prepare_problems.py` downloads HumanEval and MBPP raw files as needed,
verifies their SHA-256 digests and record counts, then writes public records
and evaluation-only records separately.

`add_bigcodebench.py` loads the `v0.1.4` dataset through Hugging Face
`datasets`, writes public prompts and a private evaluation file, and appends
new tasks to the combined public file.

`add_livecodebench.py` reads the official v6 JSONL source files, exports
public task fields and adds them to the combined file. LiveCodeBench's source
records also contain private tests. The script does not copy those test values
to its outputs, but the complete source files are downloaded into the local
Hugging Face cache (about 4.49 GB at the time this workflow was run).

**Important:** Re-running `prepare_problems.py` rebuilds the combined file
from only HumanEval and MBPP. Run the BigCodeBench and LiveCodeBench scripts
after it to restore all four datasets. Never give `data/private/`, raw source
files, or hidden tests to a model.

## Phase 1 candidate generation

The Phase 1 generator selects a problem from `data/public/<dataset>.jsonl`,
falling back to `data/public/problems.jsonl` when that per-dataset file is
missing. It supports the four datasets listed above.

### Methods

| Method | Behavior | Requested temperature |
| --- | --- | ---: |
| `direct` | One code-generation request using the base prompt. | 0.2 |
| `sampling` | Repeated independent requests using the same prompt. | 1.0 |
| `diverse` | Requests add different algorithmic priorities, cycling through five strategy statements. | 0.85 |
| `plan` | Requests a high-level plan, then asks for code following it. | 0.7 for the plan; 0.3 for code |

These settings are experimental controls, not claims that one temperature is
optimal. The low-temperature direct setting provides a relatively
conservative baseline; the higher sampling setting encourages variation;
diverse runs vary the explicit algorithmic goal; and plan runs test whether an
intermediate plan changes the generated candidate. Sampling and diverse
candidates each use one API request. Each plan candidate uses two. Provider
behavior can still vary between requests.

The base prompt asks for Python 3 code only, requests the task's named callable
when an entry point is available, otherwise asks for the specified input/output
interface, and tells the model not to access files, the network, or install
packages. Starter code is included when available.

### Run a no-cost dry run

```bash
.venv/bin/python phase1_generator.py \
  --dataset humaneval \
  --task-id HumanEval/0 \
  --method all \
  --candidates 1 \
  --dry-run
```

A dry run validates and displays the selected task, model, method list, and
planned request count. It makes no API calls and does not require an API key.

### Generate candidates

Run one candidate:

```bash
.venv/bin/python phase1_generator.py \
  --dataset humaneval \
  --task-id HumanEval/0 \
  --method direct \
  --max-calls 1
```

Generate five independent samples:

```bash
.venv/bin/python phase1_generator.py \
  --dataset humaneval \
  --task-id HumanEval/0 \
  --method sampling \
  --candidates 5 \
  --max-calls 5
```

`--task-id` is optional; when omitted, the first matching record in the
selected dataset file is used. Other options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--dataset` | `humaneval` | Select `humaneval`, `mbpp`, `bigcodebench`, or `livecodebench`. |
| `--task-id` | First task | Select a full task ID, such as `HumanEval/0`. |
| `--method` | `all` | Select `direct`, `sampling`, `diverse`, `plan`, or `all`. |
| `--candidates` | `1` | Number per non-direct method; allowed range is 1–20. |
| `--max-calls` | `5` | Reject a run whose planned API requests exceed this cap. |
| `--model` | `GEMINI_MODEL` or `gemini-3.8-flash` | Override the Gemini model ID. |
| `--max-output-tokens` | `4096` | Maximum output-token setting for each Gemini request. |
| `--dry-run` | Off | Validate the selection and planned call count without making requests. |
| `--resume` | None | Retry failed candidates from a matching prior run folder. |

Gemini requests use `thinking_level="LOW"` and record the response finish
reason. A candidate is marked `generated` only when the response finished with
`STOP` and the returned code passes Python syntax and required entry-point
checks; incomplete or invalid responses remain recorded with their status.
For a subsequent generation experiment that needs more room for code output,
use `--max-output-tokens 8192`.

With `--method all`, one candidate each means five planned API calls: one each
for direct, sampling, and diverse, plus two for plan-then-code. The call cap is
a guard against accidental request volume and cost; raise it deliberately if
the requested experiment needs more calls.

### Resume failed candidates

Each run gets a unique directory under `generated/phase1/` and a `manifest.json`.
To retry only failed candidates from the sampling run, keep the same dataset,
task, method, and model, and pass that run directory:

```bash
.venv/bin/python phase1_generator.py \
  --dataset humaneval \
  --task-id HumanEval/0 \
  --method sampling \
  --resume generated/phase1/<run-folder> \
  --max-calls 4
```

The script checks the run's task, dataset, model, and problem hash before
resuming. Successful candidates are retained; only failed candidates for the
selected method are retried. Start with `--dry-run` to see how many requests
will be made.

### Output and validation

Generated artifacts are saved under:

```text
generated/phase1/<run-id>_<task-id>/
├── <method>_<index>.prompt.txt
├── <method>_<index>.py
├── <method>_<index>.json
└── manifest.json
```

Plan runs also save plan prompt and response files. Per-candidate metadata
records the model, task and dataset, method, requested temperature, timing,
API usage metadata when available, and SHA-256 fingerprints of the problem and
generated code.

The only candidate checks currently performed are Python syntax parsing and,
when a task has a named entry point, checking whether that function is present
at module top level. These checks do **not** prove correctness, safety,
constraint compliance, or passing benchmark tests. Phase 1 generation itself
does not execute code. The optional Phase 2A pilot below executes candidates
only inside a constrained container.

## Phase 2A: isolated HumanEval development validation

The validator supports `HumanEval/0` through `HumanEval/163`. `HumanEval/0`
(`has_close_elements`) uses eight hand-selected development cases for empty
and singleton inputs, separated and close values, unsorted pairs,
exact-threshold behavior, duplicates, and negative values. These are
development tests, not official HumanEval hidden tests or a held-out test set.

Other tasks require an explicitly reviewed test file at
`data/development/humaneval/HumanEval_<index>.json`. For example:

```json
{
  "task_id": "HumanEval/1",
  "cases": [
    {
      "name": "ordinary_case",
      "args": ["input value"],
      "expected": "expected value"
    }
  ]
}
```

Each file must contain 1–30 uniquely named cases. Each case must have a string
`name`, a JSON list of positional `args`, and an `expected` value. An optional
`expected_type` string can explicitly specify the expected Python type. Add
only independently reviewed development cases; never copy official
held-out tests. The validator executes the canonical reference from
`data/private/humaneval_evaluation.jsonl` in Docker as an oracle and requires
it to agree with every expected value before candidate evaluation.
The current `HumanEval_1.json` suite contains 15 reviewed examples for
`separate_paren_groups`; it is included in the repository so the validation
setup can be reproduced.

Docker must be installed and running. The validator uses a pinned, locally
available `python:3.11-slim` image and will not pull an image automatically.
From the project root, first list candidates without executing them:

```bash
.venv/bin/python phase2a_validator.py \
  --task-id HumanEval/0 \
  --runs generated/phase1/<run-folder> \
  --dry-run
```

Then run the development checks:

```bash
.venv/bin/python phase2a_validator.py \
  --task-id HumanEval/0 \
  --runs generated/phase1/<run-folder>
```

`--task-id` defaults to `HumanEval/0`. Multiple run folders can be passed
after `--runs`. Only files named `direct_###.py`, `sampling_###.py`,
`diverse_###.py`, or `plan_###.py` are considered. Every candidate must have
metadata identifying the selected task.

The Docker invocation has no network, no host filesystem mounts, a read-only
container root, a small non-executable temporary filesystem, dropped
capabilities, `no-new-privileges`, Docker's default seccomp profile, a
non-root user, and limits on memory, CPU, processes, open files, per-case
runtime, and total batch runtime. It runs a fresh Python process for each
case. The validator never evaluates LiveCodeBench private tests or any
official hidden test suite. Reports are written to `results/phase2a/` and are
ignored by Git. Existing HumanEval/0 reports from the original eight-case
suite remain unchanged when using the updated validator.

These controls reduce risk but do not make execution of untrusted code
perfectly safe: container isolation still depends on the host kernel, Docker,
and the configured runtime. Use a disposable machine or stronger VM boundary
for higher-risk code. Results from this small curated suite must not be
presented as official benchmark scores.

## Phase 2B-1: Hypothesis-generated development inputs

`phase2b1_validator.py` generates additional valid inputs with Hypothesis for
HumanEval/0 (`has_close_elements`) and HumanEval/1 (`separate_paren_groups`).
It uses the Phase 2A reference loader and Docker executor. The reference
oracle runs on each generated input first; candidates are scored against the
reference output. It does not read official hidden tests or execute candidate
code on the host. This is development testing, not official benchmark
evaluation.

Run a dry run first:

```bash
.venv/bin/python phase2b1_validator.py \
  --task-id HumanEval/1 \
  --runs generated/phase1/<run-folder> \
  --dry-run
```

By default, Hypothesis requests 40 examples, Docker execution batches 10
inputs at a time, and the script records the actual number of unique generated
inputs. These are bounded by `--cases` (1–500) and `--batch-size` (1–20).
Input generation is deterministic and disables the Hypothesis example
database for reproducibility. Generated input corpora and reports are written
under the ignored `results/phase2b/` directory.

To run the reference and candidate checks, omit `--dry-run`:

```bash
.venv/bin/python phase2b1_validator.py \
  --task-id HumanEval/1 \
  --runs generated/phase1/<run-folder>
```

Synthetic diagnostic or fault-injection candidates are excluded unless
`--include-diagnostics` is explicitly supplied. Hypothesis generation and
oracle checking do not guarantee exhaustive coverage or correctness beyond
the generated inputs. Shrinking and metamorphic testing are not implemented
in this phase.

## Phase 2B-2: Reference-validated mutation testing

`phase2b2_mutation.py` mutates reviewed HumanEval/0 or HumanEval/1 development
inputs, verifies the reviewed seeds against the canonical reference, then
labels each mutated input using that reference in the Phase 2A Docker
environment. Candidates are evaluated against the same generated corpus.
This is specification-aware development testing, not coverage-guided fuzzing
or official benchmark evaluation; it does not call an LLM or use held-out
tests.

Start with a dry run:

```bash
.venv/bin/python phase2b2_mutation.py \
  --task-id HumanEval/0 \
  --runs generated/phase1/<run-folder> \
  --mutations 40 \
  --batch-size 10 \
  --dry-run
```

Omit `--dry-run` to run the reference and candidate executions in Docker.
Mutation generation is deterministic for a given `--seed` (default: 2026).
The requested unique mutations are bounded by `--mutations` (1–500), and
Docker batches by `--batch-size` (1–30). Input corpora and reports are saved
under the ignored `results/phase2b/` directory. Synthetic diagnostic
candidates are excluded unless `--include-diagnostics` is explicitly used.

## Phase 2B-3: Oracle-checked differential testing

`phase2b3_differential.py` runs multiple saved candidates against the same
reviewed development inputs or a saved Phase 2B corpus. An independent
canonical-reference run labels the inputs, so candidate disagreements can be
distinguished from reference-verified candidate failures. Differences in
exceptions and other execution statuses are also reported as behavioral
disagreements. At least two eligible candidates are required; synthetic
diagnostic candidates are excluded unless explicitly enabled.

Run a dry-run first:

```bash
.venv/bin/python phase2b3_differential.py \
  --task-id HumanEval/0 \
  --runs generated/phase1/<run-folder-1> generated/phase1/<run-folder-2> \
  --dry-run
```

Omit `--dry-run` to run the reference and candidates in Docker. By default,
the validator uses the reviewed cases for the selected task. Optionally pass
`--inputs results/phase2b/<corpus>_inputs.json` to compare candidates on a
saved Phase 2B development corpus. Candidate outputs are always recomputed;
any expected values in an input corpus are not trusted. `--max-cases` is
bounded to 1–500 and `--batch-size` to 1–30. Reports are written under
`results/phase2b/`. This is development testing only, not an official or
held-out benchmark evaluation.

## Phase 2B-4: Metamorphic development testing

`phase2b4_metamorphic.py` creates related input pairs for HumanEval/0 or
HumanEval/1 and checks candidate behavior against the task's metamorphic
relations. It independently runs the canonical reference so relation
violations can be reported separately from reference-confirmed candidate
failures. An optional Phase 2B input corpus can be supplied with `--inputs`;
otherwise it uses the reviewed development cases.

```bash
.venv/bin/python phase2b4_metamorphic.py \
  --task-id HumanEval/1 \
  --runs generated/phase1/<run-folder> \
  --pairs 40 \
  --batch-size 10 \
  --seed 2026 \
  --dry-run
```

Omit `--dry-run` to execute the reference and candidate in Docker.
Diagnostic candidates require `--include-diagnostics`. Results are saved under
`results/phase2b/`. These are development checks only, not official or
held-out benchmark results.

## Phase 2B-5: Controlled synthetic fault benchmark

`phase2b5_fault_benchmark.py` compares property, mutation, differential, and
metamorphic input methods on known synthetic mutants for HumanEval/0 and
HumanEval/1. Declared witnesses are checked against the reference before
scoring. This measures detection of the included synthetic faults, not real
LLM accuracy, real-world bug prevalence, or held-out benchmark performance.

```bash
.venv/bin/python phase2b5_fault_benchmark.py \
  --task-id all \
  --budget 40 \
  --seed 2026 \
  --batch-size 10 \
  --dry-run
```

Omit `--dry-run` to execute the benchmark in Docker. `--budget` must be an
even number from 4 to 200; it controls candidate-plus-probe executions per
mutant and method. Optional genuine Phase 1 candidate runs can be supplied
with `--probe-run-0` and `--probe-run-1` for the differential probes. Input
corpora and reports are saved under `results/phase2b/`.

The original multi-provider example remains available at
[`scripts/model_generator.py`](./scripts/model_generator.py). It uses the
provider IDs in that file and generates a sample `two_sum` program; it is
separate from the dataset-driven Phase 1 generator.
