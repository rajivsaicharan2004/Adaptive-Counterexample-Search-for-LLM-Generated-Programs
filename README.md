# Adaptive Counterexample Search for LLM-Generated Programs

Research workspace for generating Python programs with language models and
preparing programming benchmarks for later evaluation.

## Project layout

```text
.
├── data/
│   └── public/                 # Benchmark prompts and combined public index
├── generated/                  # Local model outputs (not tracked by Git)
├── scripts/
│   ├── model_generator.py      # Generate a sample program with an LLM
│   ├── prepare_problems.py     # Prepare HumanEval and MBPP
│   ├── add_bigcodebench.py     # Add BigCodeBench
│   └── add_livecodebench.py    # Add LiveCodeBench
├── .env.example
└── requirements.txt
```

Raw downloads, evaluation/reference data, virtual environments, API keys, and
generated outputs are kept out of Git. The benchmark sources have their own
terms; consult each source before redistributing its data.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Add the API keys you plan to use to `.env`:

```dotenv
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
```

Never commit `.env` or paste API keys into source files.

## Prepare benchmarks

Run these commands from the project root:

```bash
python scripts/prepare_problems.py
python scripts/add_bigcodebench.py
python scripts/add_livecodebench.py
```

The scripts create per-dataset public JSONL files and combine them in
`data/public/problems.jsonl`. The current combined dataset contains 3,333
problems:

| Dataset | Problems |
| --- | ---: |
| HumanEval | 164 |
| MBPP | 974 |
| BigCodeBench | 1,140 |
| LiveCodeBench | 1,055 |
| **Total** | **3,333** |

Evaluation/reference data is written under `data/private/` and is ignored by
Git. LiveCodeBench's source files include hidden tests; the preparation script
exports only public fields, but downloads the source files to the local
Hugging Face cache. Do not send evaluation data to a model.

## Generate a sample program

```bash
python scripts/model_generator.py --model gemini
```

Available providers are `gpt`, `claude`, and `gemini`. Results are saved under
`generated/`. This command uses the sample problem in the script; it does not
run benchmark evaluation.
