BigCodeBench/854 independent development-case review

1. Place review_bcb854_suite.py in /Users/jo/projects/Research.
2. From the VS Code terminal:

   cd /Users/jo/projects/Research
   .venv/bin/python review_bcb854_suite.py

   Read the printed policies and inspect proposals/bcb854_review.json.
   This first command ONLY reads files, never executes generated candidates.

3. If you accept the bounded test policies, approve the suite independently of
   the still-DRAFT dataset split manifest:

   .venv/bin/python review_bcb854_suite.py --approve

   This creates, without overwriting preexisting files:
     data/development/bigcodebench/BigCodeBench_854.json
     results/phase2d/reviews/BigCodeBench_854_review.json

4. Check the CLI remains blocked while the manifest is draft:

   .venv/bin/python phase2d_bcb854_cli.py --review

This script does NOT change the split manifest, execute generated candidates,
call models, run Docker, access private tests, or make network calls. It does
not claim the official BigCodeBench evaluator uses the same policy.

Reviewed policies:
- 9 valid, 7 invalid inputs (16 total).
- Empty input => two empty lists.
- Every position-based permutation retained, including repeated values.
- No requirement on permutation enumeration order.
- Root and inner tuple types reported separately as exploratory strict mode;
  semantic mode accepts tuple/list permutation rows via JSON serialization.
- Non-list/non-int => TypeError; negative ints => ValueError.
- Boolean inputs, tuple inputs, and mixed-invalid precedence excluded as
  specification/transport ambiguities.
- Inputs are small (n<=4); development-only, not official evaluation.

The independent checker uses unique-value Cartesian enumeration and explicit
factorial-by-loop to verify each proposed case. The 16 cases passed; a
separate exhaustive cross-check confirmed 341 bounded sequences from 0..3
also agree with the current development adapter, with no candidate execution.
