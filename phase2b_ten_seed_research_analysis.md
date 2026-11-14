# Phase 2B Fairness V1 — Ten-seed Synthetic Fault Detection Analysis

**Scope:** Development-only diagnostics on HumanEval/0 and HumanEval/1; 10 intentionally faulty synthetic programs, each repeated under seeds 2026–2035 at nominal budget B=40 per method and mutant.

## Provenance and verification

- Audited all **22 uploaded JSON files** (11 reports and 11 input corpora) against the 22 SHA-256 digests in `evidence_manifest.json`: **22/22 match**.
- Checked unique mutant–task–seed records, full ten-seed coverage, task-to-corpus associations, per-method corpus lengths, candidate budgets, and the consistency of execution ledgers.
- All reports use `phase2b_fairness_v1` and the same benchmark source SHA-256 (`e3af520339a6c1fbd0fd9ac8e845e5d68b7bc7a416c5b6a039188a34a544368c`).
- This analysis reads historical files. It does **not** rerun Docker, execute code candidates, or call an LLM. The user-reported ZIP SHA-256 is not independently verified because the ZIP itself was not uploaded; its unpacked files were verified.

## 1. Detection observations

| Method | Detected / 100 observations | Mean per seed, of 10 | SD across ten seed totals | Seed total range |
|---|---:|---:|---:|---:|
| Property-based | 96/100 | 9.6 | 0.70 | 8–10 |
| Input mutation | 97/100 | 9.7 | 0.48 | 9–10 |
| Differential | 79/100 | 7.9 | 1.60 | 6–10 |
| Metamorphic | 57/100 | 5.7 | 0.95 | 5–8 |

**Unit:** One observation = one fixed synthetic mutant evaluated using one seed. These are only ten distinct mutant programs (two tasks), *not* 100 independent real programs. Mean/SD describe these trials only; no population inference or method-rank significance is warranted.

## 2. Task separation

| Task | Property | Input mutation | Differential | Metamorphic |
|---|---:|---:|---:|---:|
| HumanEval/0 | 46/50 | 47/50 | 29/50 | 7/50 |
| HumanEval/1 | 50/50 | 50/50 | 50/50 | 50/50 |

The task difference is substantial: HumanEval/1 is detected 50/50 for every strategy, while the difficult cases concentrate in HumanEval/0. The two task samples are not representative of a broader program population. HumanEval/1 also has a known cross-partition semantic-overlap warning with HumanEval/6, so these data must never be labeled held-out generalization.

## 3. Individual mutant detection frequencies across ten seeds

| Task / synthetic fault | Property | Input mutation | Differential | Metamorphic |
|---|---:|---:|---:|---:|
| HumanEval/0 / `adjacent_only` | 8/10 | 8/10 | 5/10 | 2/10 |
| HumanEval/0 / `boundary_le` | 10/10 | 9/10 | 9/10 | 0/10 |
| HumanEval/0 / `first_two_only` | 9/10 | 10/10 | 6/10 | 2/10 |
| HumanEval/0 / `ignore_negatives` | 10/10 | 10/10 | 6/10 | 3/10 |
| HumanEval/0 / `no_duplicates` | 9/10 | 10/10 | 3/10 | 0/10 |
| HumanEval/1 / `flatten_nesting` | 10/10 | 10/10 | 10/10 | 10/10 |
| HumanEval/1 / `merge_groups` | 10/10 | 10/10 | 10/10 | 10/10 |
| HumanEval/1 / `omit_last` | 10/10 | 10/10 | 10/10 | 10/10 |
| HumanEval/1 / `retain_spaces` | 10/10 | 10/10 | 10/10 | 10/10 |
| HumanEval/1 / `reverse_groups` | 10/10 | 10/10 | 10/10 | 10/10 |

## 4. Seed-to-seed variation

| Seed | Property | Mutation | Differential | Metamorphic |
|---:|---:|---:|---:|---:|
| 2026 | 10/10 | 10/10 | 9/10 | 5/10 |
| 2027 | 10/10 | 10/10 | 8/10 | 6/10 |
| 2028 | 9/10 | 10/10 | 6/10 | 5/10 |
| 2029 | 10/10 | 10/10 | 10/10 | 8/10 |
| 2030 | 10/10 | 10/10 | 10/10 | 6/10 |
| 2031 | 10/10 | 10/10 | 9/10 | 6/10 |
| 2032 | 9/10 | 9/10 | 6/10 | 5/10 |
| 2033 | 10/10 | 10/10 | 8/10 | 5/10 |
| 2034 | 10/10 | 9/10 | 6/10 | 5/10 |
| 2035 | 8/10 | 9/10 | 7/10 | 6/10 |

## 5. Pairwise complementarity

A “win” means a strategy detected a mutant–seed observation that the compared strategy missed. This is a *descriptive paired table*, not an independently sampled statistical test.

| A | B | Both detect | A only | B only | Neither |
|---|---|---:|---:|---:|---:|
| Property-based | Input mutation | 94 | 2 | 3 | 1 |
| Property-based | Differential | 79 | 17 | 0 | 4 |
| Property-based | Metamorphic | 57 | 39 | 0 | 4 |
| Input mutation | Differential | 78 | 19 | 1 | 2 |
| Input mutation | Metamorphic | 57 | 40 | 0 | 3 |
| Differential | Metamorphic | 57 | 22 | 0 | 21 |

- Union of property + input mutation: **99/100**. Union of *all four* strategies: **99/100**.
- Every verified differential and metamorphic hit in the evaluated mutant–seed records was already covered by property testing or input mutation. This is specific to this pilot at B=40 and does not establish lack of value at different budget allocations or on real-model faults.
- The single case missed by all methods: **HumanEval/0 / `adjacent_only` / seed 2032**.

## 6. Metamorphic failure analysis

In HumanEval/0, metamorphic relations detected **7/50** mutant–seed cases, versus **50/50** in HumanEval/1. The diagnostics distinguish wrong outputs reached from relation violations recognized:

| HumanEval/0 synthetic fault | Metamorphic detected seeds | Wrong target executions (sum over seeds) | Relation-violation signals |
|---|---:|---:|---:|
| `adjacent_only` | 2/10 | 25 | 2 |
| `boundary_le` | 0/10 | 82 | 0 |
| `first_two_only` | 2/10 | 60 | 3 |
| `ignore_negatives` | 3/10 | 47 | 4 |
| `no_duplicates` | 0/10 | 38 | 0 |

Across the 200 HumanEval/0 metamorphic pairs, **74** base inputs contain fewer than two numbers and **112** use threshold zero. These categories overlap. Their prevalence restricts opportunity to detect pairwise-distance faults. Operation counts: reflect=41, reverse=23, rotate=20, scale_two=38, threshold_up=41, translate=37.

**Interpretation:** For `boundary_le`, metamorphic testing encountered 82 incorrect executions but never violated the selected relations. For `no_duplicates`, it encountered 38 incorrect executions but likewise recorded zero relation violations. This is a limitation of relation observability, not proof that the buggy code behaved correctly. H1 relations involving group addition, spacing and output shape were more discriminative against these particular synthetic faults.

## 7. Cost ledger and timing

| Method | Target executions | Probe executions | Shared reference-oracle calls | Mutant candidate wall time (s) | Median posthoc first signal cost among detections |
|---|---:|---:|---:|---:|---:|
| Property-based | 4000 | 0 | 800 | 552.76 | 5 |
| Input mutation | 4000 | 0 | 800 | 548.81 | 2 |
| Differential | 2000 | 2000 | 400 | 627.70 | 8 |
| Metamorphic | 4000 | 0 | 800 | 550.84 | 6 |

- Total target/probe sandbox calls: **16,000** across all methods (including 2,000 probe calls in differential).
- Shared reference calls across all task/method/seed contexts: **2,800**, plus **100** recorded mutant-witness reference calls. Reference costs are *not* matched across methods.
- Timing is candidate wall-clock time as reported, not end-to-end cost; generation and oracle overhead cannot be assumed matched.
- First-signal indices were calculated posthoc from full B=40 executions. They do not demonstrate saved compute under early stopping; the per-method medians condition on detection and are not causally comparable.

## 8. Posthoc prefix diagnostic (not new executions)

The following counts are obtained by applying candidate-call cutoffs to the recorded first-signal positions within B=40 corpora. **Not equivalent to re-running independent B=4/8/16 studies**, because corpus generation and strategies can depend on budget.

| Max candidate-call index | Property | Mutation | Differential | Metamorphic |
|---:|---:|---:|---:|---:|
| 4 | 43/100 | 65/100 | 20/100 | 20/100 |
| 8 | 58/100 | 77/100 | 43/100 | 51/100 |
| 16 | 77/100 | 87/100 | 58/100 | 57/100 |
| 40 | 96/100 | 97/100 | 79/100 | 57/100 |

## 9. Scientific limitations and next research tasks

1. **Synthetic and tiny:** Two hand-selected development tasks and five designed mutants per task, not a sample of real LLM mistakes. HumanEval/1 has known semantic overlap with held-out HumanEval/6.
2. **Non-equivalent cost models:** Equal B=40 total target+probe calls; differential spends half its budget on probe calls. Reference calls and generation effort differ. Strategy priors may favor specific mutant constructions. No causal method-ranking claim is supported.
3. **Repeated measurements:** Seed changes produce distinct reproducible corpora, but are not additional independent tasks or programs. Avoid naive binomial confidence intervals, independence-based p-values and held-out claims.
4. **Preserve this evidence:** Freeze Fairness V1. Do not replace or pool historical results with changes to metamorphic generators.
5. **Next experiments:** Pre-register a Fairness V2 metamorphic adequacy study using development-only cases; evaluate genuine LLM-generated programs across more audited development tasks; instrument per-call oracle, probe, test-generation, and model cost; then prepare fixed-budget controller baselines.
6. **Dataset gate:** Independent overlap adjudication, split-manifest freeze, and LiveCodeBench timestamp provenance are prerequisites to a trustworthy held-out/temporal evaluation.

**Conclusion:** Fairness V1 passed a reproducibility/integrity milestone. It exposes a pronounced task-specific metamorphic observability gap but does not yet demonstrate that an adaptive controller or any method generalizes to real LLM-generated programs.
