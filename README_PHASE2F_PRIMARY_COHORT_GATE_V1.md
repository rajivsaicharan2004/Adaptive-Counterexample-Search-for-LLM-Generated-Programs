# Phase 2F: manifest-selected, development-only candidate evaluator

This new script **does not modify** the original V3 guard, the existing V4
researcher attestation, the original Phase 2F evaluator, candidate source, or
the frozen development inputs. It is an independent selection layer that
calls the original evaluator's hardened Docker execution path only for members
of the predeclared 24-candidate **primary** cohort.

## Install into the existing Research directory

1. Download `phase2f_primary_cohort_gate_v1.zip`.
2. Place the ZIP in `/Users/jo/projects/Research` and in a terminal run:

```bash
cd /Users/jo/projects/Research
unzip -n phase2f_primary_cohort_gate_v1.zip
shasum -a 256 -c SHA256SUMS_COHORT_GATE_V1.txt
```

Do not overwrite existing files if `unzip -n` reports a name collision.

## First: tests and read-only preflight

```bash
.venv/bin/python test_phase2f_primary_cohort_eval_v1.py
.venv/bin/python phase2f_primary_cohort_eval_v1.py --preflight
```

The offline unit tests do not import or execute generated candidates, access
Docker, or call model APIs. They use mocks to check duplicate/source-selection
accounting and one-time-run protections. These tests are not a substitute for
running the actual preflight in your project.

Preflight verifies the exact frozen primary manifest SHA-256
`7ee24e3e21158355aa96d0ea9c9162a81fd6502af9cbe86451862ee5ed9e93cb`,
all 147 artifact hashes, original baseline, protocol, recorded deviation,
original evaluator integrity, candidate identities and generation provenance,
original pinned Docker image identity, dual-oracle frozen inputs, the sandbox
contract, and V4 development-only scope. It does not execute candidate code or
write files.

## Then: one task at a time, only after preflight passes

For example:

```bash
.venv/bin/python phase2f_primary_cohort_eval_v1.py --run --task-id HumanEval/129
```

Running is **not** part of preflight. The `--run` mode checks authorization and
Docker readiness and creates an exclusive task-specific *run-intent* JSON
before executing any candidate. It evaluates three primary candidates for
that one task, with the original frozen 128-case development suite and
existing hardened, offline Docker executor. The unplanned second
HumanEval/112 `diverse` candidate is never selected for execution. Every
candidate is reported, including duplicate source code and static-invalid
candidates; duplicates are **not** retested and must not be counted as new
passes. Full evaluation reports go to:

`results/phase2f/primary_cohort_reports/`

A second invocation for an already-attempted task fails closed because an
intent or report exists. If a task is interrupted, **do not delete the intent
or blindly rerun it**. Review what happened and create a separately justified
recovery protocol if necessary.

## Limitations

- These are development-suite results only, **not** independent validation or
  held-out evaluation.
- The original baseline already passed its 128 frozen development cases for
  each task. A duplicate generated source is linked to that baseline, rather
  than retested; it is still a separate *generation attempt*.
- The 24 acquisition attempts include exactly two source duplicates and one
  extra documented attempt excluded from primary evaluation.
- This script has been syntax-checked and its narrow offline unit tests passed
  in the authoring environment. It has **not** been end-to-end executed against
  the user's private Mac research project or Docker image. Stop if preflight
  finds any mismatch.
- The new script is an evaluation-selection gate, not yet the adaptive
  counterexample-search controller or an independent expert review.
