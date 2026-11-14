# Phase 2D Batch 4 — Provisional sampled-overlap review

The source was a user-pasted 81-pair CSV export. Reviews are based only on public prompts. No execution, network, model call, private tests, or source dataset mutation.

- Input SHA256: `48a98d45721a40f9da34b31572dbc82cd3e22b2e21d59ef9cba807669d3c5462`
- Sample size: **81**, strata: **34**, lexical candidate strata population: **4607**
- Verdict counts: **equivalent=2, near_equivalent=33, needs_contract_review=1, related_distinct=22, unrelated=23**
- Descriptive stratum-weighted share equivalent/near among candidate strata: **8.4%**. This is **not** corpus-wide semantic leakage probability.

## High-priority findings

- HumanEval/1 ↔ HumanEval/6: near-equivalent nested-parentheses parser; the existing pilot exception for HumanEval/1 deserves policy review.
- HumanEval/59 ↔ MBPP/32: equivalent largest-prime-factor task on the shared input domain, validation vs held-out.
- MBPP/263 ↔ MBPP/821: equivalent dictionary merge operation (held-out vs validation).
- BigCodeBench/423 ↔ BigCodeBench/426: closely related thresholded image processing with extra file write; side effects matter.
- MBPP/707 ↔ MBPP/903: related set/unset bit counts but unspecified bit width; contract review needed.

## Proposed development-task review holds (not applied)

`BigCodeBench/288`, `BigCodeBench/3`, `BigCodeBench/417`, `BigCodeBench/426`, `BigCodeBench/506`, `BigCodeBench/608`, `BigCodeBench/730`, `BigCodeBench/753`, `BigCodeBench/812`, `HumanEval/1`, `HumanEval/85`, `MBPP/25`, `MBPP/287`, `MBPP/436`, `MBPP/457`, `MBPP/497`, `MBPP/503`, `MBPP/66`, `MBPP/696`, `MBPP/784`, `MBPP/79`

## Review protocol and limitations

- Do **not** automatically quarantine all near-equivalent pairs without a second-review policy decision; the CSV provides suggested risk actions.
- Keep the 14 deterministic priority-pair audit distinct from this stratified sample; do not combine naive percentages.
- The V3 guard and draft split remain unchanged. Confirm changes against local hashes before incorporating any review into policy.
- Holdout–validation near matches still matter for threshold tuning even if no development task is directly involved.
- Report only screening-population descriptive rates; unscreened near duplicates and pretraining contamination are unmeasured.

## Pair-by-pair judgments

| # | Pair | Verdict | Rationale |
|---:|---|---|---|
| 1 | `BigCodeBench/204` ↔ `BigCodeBench/409` | related_distinct | Both use descriptive statistics, but one analyzes a supplied list and returns a histogram; the other reads an Excel column and returns three statistics. |
| 2 | `BigCodeBench/506` ↔ `BigCodeBench/507` | near_equivalent | Same column-based sum/mean/min/max aggregation; the weather task additionally plots a histogram and differs in empty-data conventions. |
| 3 | `BigCodeBench/696` ↔ `BigCodeBench/753` | near_equivalent | Both sample random points uniformly within a circle; one returns points while the other summarizes mean radial distance. |
| 4 | `BigCodeBench/3` ↔ `BigCodeBench/5` | near_equivalent | Both build letter-keyed random-integer lists using the same ranges; mean versus population standard deviation differs. |
| 5 | `BigCodeBench/403` ↔ `BigCodeBench/423` | related_distinct | Image loading and grayscale conversion overlap, but blur/display and thresholded binarization are different processing contracts. |
| 6 | `BigCodeBench/608` ↔ `BigCodeBench/611` | near_equivalent | Both remove rows using column conditions and sample column pairs; pairplots versus line-plots and outputs differ. |
| 7 | `BigCodeBench/968` ↔ `BigCodeBench/980` | related_distinct | Both process numeric tabular data and heatmaps, but cumulative sums versus correlations and standardization are materially different. |
| 8 | `BigCodeBench/423` ↔ `BigCodeBench/426` | near_equivalent | Same grayscale thresholding interface, output arrays, and exceptions; development task additionally saves a binary image to disk. |
| 9 | `BigCodeBench/301` ↔ `BigCodeBench/303` | related_distinct | Time-zone/date parsing is shared, but solar-cycle versus lunar-phase calculations use distinct models, constants and objectives. |
| 10 | `BigCodeBench/688` ↔ `BigCodeBench/690` | related_distinct | Both accept DataFrames and scikit-learn, but StandardScaler and LinearRegression solve different tasks. |
| 11 | `BigCodeBench/803` ↔ `BigCodeBench/889` | related_distinct | CSV processing is shared, but numeric MinMax scaling versus missing-value mean imputation differ. |
| 12 | `BigCodeBench/283` ↔ `BigCodeBench/288` | near_equivalent | Both traverse JSON files and count occurrences; one counts values under a specified key, the other counts all key names. |
| 13 | `BigCodeBench/417` ↔ `BigCodeBench/418` | near_equivalent | Substantial shared Keras train/validation pipeline; differences include split ratio, loss plot versus ROC/AUC, and result visualization. |
| 14 | `BigCodeBench/730` ↔ `BigCodeBench/731` | near_equivalent | Same pickle save/load/round-trip structure and fixed filename; serialized object and return interface differ. |
| 15 | `BigCodeBench/812` ↔ `BigCodeBench/814` | near_equivalent | Same specific directory-and-regex file search; one archives matching files, the other writes matching paths to a config file. |
| 16 | `BigCodeBench/136` ↔ `BigCodeBench/304` | related_distinct | Both use PCA, but component-coordinate scatter versus explained-variance bar plot have different outputs and preprocessing. |
| 17 | `BigCodeBench/282` ↔ `BigCodeBench/404` | related_distinct | Both read image files, but 3D color histograms with pick callbacks differ substantially from grayscale contour extraction. |
| 18 | `BigCodeBench/645` ↔ `BigCodeBench/724` | unrelated | CSV read-and-delete and JSON configuration loading have different data and effects; shared file I/O is insufficient for task overlap. |
| 19 | `BigCodeBench/245` ↔ `BigCodeBench/249` | related_distinct | Random float generation/truncation is shared; statistics versus train/test splitting differ in core result. |
| 20 | `BigCodeBench/317` ↔ `BigCodeBench/319` | near_equivalent | Both remove square-bracketed segments then process words; TF-IDF dictionary versus frequency plot/top-n requires different aggregation. |
| 21 | `BigCodeBench/72` ↔ `BigCodeBench/73` | related_distinct | Both aggregate email-associated lists but data sources (CSV directory vs SQLite) and outputs (median histogram vs variance bar plot) differ. |
| 22 | `BigCodeBench/170` ↔ `BigCodeBench/390` | near_equivalent | Same URL CSV fetching, DataFrame sorting, and output; held-out task takes a URL while validation wraps it in a dictionary. |
| 23 | `BigCodeBench/616` ↔ `BigCodeBench/618` | near_equivalent | Same football results table, goals/penalties and fine conversion; one plot versus two and parameterization differ. |
| 24 | `BigCodeBench/349` ↔ `BigCodeBench/353` | near_equivalent | Same random sales-report pipeline; one version includes additional total-revenue field and configurable ranges. |
| 25 | `BigCodeBench/599` ↔ `BigCodeBench/600` | near_equivalent | Same Word-column prefix filtering and word-length derivation; histogram versus mean/median/mode output differ. |
| 26 | `BigCodeBench/666` ↔ `LiveCodeBench/leetcode/3106` | unrelated | String subsequence maximum weighted value versus longest integer subsequence of a target sum have different objectives. |
| 27 | `BigCodeBench/666` ↔ `LiveCodeBench/leetcode/3490` | unrelated | String subsequence maximum weights and integer longest parity-constrained subsequence solve different problems. |
| 28 | `MBPP/298` ↔ `BigCodeBench/736` | unrelated | Nested-list membership versus mode of flattened nested-list elements are different tasks. |
| 29 | `MBPP/298` ↔ `BigCodeBench/737` | unrelated | Nested-list membership versus median of flattened nested-list elements are different tasks. |
| 30 | `MBPP/238` ↔ `BigCodeBench/332` | unrelated | Counting nonempty substrings versus tokenizing/filtering stopwords and counting words are distinct. |
| 31 | `MBPP/862` ↔ `BigCodeBench/332` | related_distinct | Both count word occurrences, but top-n frequent words versus all non-stopwords with stopword filtering differ in output policy. |
| 32 | `MBPP/833` ↔ `BigCodeBench/902` | unrelated | Listing dictionary keys and counting x/y/z values across dictionaries have different inputs and outcomes. |
| 33 | `HumanEval/0` ↔ `HumanEval/21` | related_distinct | Both inspect lists of numbers, but pairwise distance threshold test and min/max rescaling are different computations. |
| 34 | `HumanEval/1` ↔ `HumanEval/6` | near_equivalent | Both parse balanced groups of nested parentheses; one returns extracted group strings, the other maximum nesting depth per group. Existing HumanEval/1 pilot overlaps held-out HumanEval/6. |
| 35 | `HumanEval/34` ↔ `HumanEval/58` | related_distinct | Deduplicating and sorting a list versus taking sorted unique intersection of two lists overlap in set operations but differ in inputs. |
| 36 | `HumanEval/85` ↔ `HumanEval/121` | near_equivalent | Both filter/sum list entries by index and value parity; swapping even/odd conditions changes the selected elements. |
| 37 | `HumanEval/14` ↔ `HumanEval/29` | related_distinct | Constructing all prefixes of one string versus filtering a list by a supplied prefix are different output contracts. |
| 38 | `HumanEval/4` ↔ `HumanEval/21` | related_distinct | Mean absolute deviation around mean and min-max normalization share numeric-array traversal but differ in formula. |
| 39 | `HumanEval/7` ↔ `HumanEval/28` | unrelated | Selecting strings containing a substring versus concatenating all strings are different operations. |
| 40 | `HumanEval/33` ↔ `HumanEval/37` | near_equivalent | Same selective-index sorting template with modulo-3 versus even-index selection. |
| 41 | `HumanEval/7` ↔ `HumanEval/29` | near_equivalent | Both filter input strings by pattern membership; substring containment versus startswith prefix changes the predicate. |
| 42 | `HumanEval/30` ↔ `MBPP/66` | near_equivalent | Same positive-number predicate over a list; one returns matching values while the other returns their count. |
| 43 | `HumanEval/23` ↔ `MBPP/772` | unrelated | String length versus removing words of a specified length differ in task and output. |
| 44 | `HumanEval/59` ↔ `MBPP/32` | equivalent | Both compute largest prime factor of an integer; HumanEval explicitly restricts n to composite n>1, while MBPP leaves preconditions unspecified. |
| 45 | `MBPP/60` ↔ `LiveCodeBench/leetcode/3747` | unrelated | Longest subsequence under adjacent-difference constraints and maximum circular adjacent absolute difference differ. |
| 46 | `MBPP/107` ↔ `MBPP/764` | unrelated | Counting hexadecimal numbers in a range and counting numeric values in a string differ. |
| 47 | `MBPP/338` ↔ `MBPP/801` | unrelated | Counting substrings with identical first/last characters and counting equal numbers among three integers differ. |
| 48 | `MBPP/359` ↔ `MBPP/887` | unrelated | Quadratic-root ratio test and testing number oddness with bitwise operator differ. |
| 49 | `MBPP/197` ↔ `MBPP/429` | related_distinct | Elementwise tuple exponentiation versus elementwise AND of tuples have different operations despite tuple traversal. |
| 50 | `MBPP/197` ↔ `MBPP/484` | unrelated | Elementwise exponentiation and removal of matching tuples are different operations. |
| 51 | `MBPP/337` ↔ `MBPP/454` | related_distinct | Both regex-style word matching, but end-of-string word/punctuation versus words containing z differ in predicate. |
| 52 | `MBPP/164` ↔ `MBPP/201` | unrelated | Comparing divisor sums of numbers and checking equality of all list elements differ. |
| 53 | `MBPP/85` ↔ `MBPP/497` | related_distinct | Sphere total area and cone total area use different geometric parameters and formulae. |
| 54 | `MBPP/81` ↔ `MBPP/696` | near_equivalent | Both zip two sequences; tuple inputs versus lists-of-lists and expected return shape need contract confirmation. |
| 55 | `MBPP/72` ↔ `MBPP/188` | related_distinct | Representation as difference of two squares versus product of two squares require different mathematical criteria. |
| 56 | `MBPP/503` ↔ `MBPP/690` | near_equivalent | Same adjacent-item traversal; addition versus multiplication changes the aggregation operator. |
| 57 | `MBPP/594` ↔ `MBPP/784` | near_equivalent | Same first-even/first-odd selection; difference versus product changes the final arithmetic operator. |
| 58 | `MBPP/11` ↔ `MBPP/591` | unrelated | Deleting first/last character occurrences from a string and swapping list boundary elements are not equivalent. |
| 59 | `MBPP/247` ↔ `MBPP/601` | unrelated | Longest palindromic subsequence and longest chain of pairs require different algorithms and inputs. |
| 60 | `MBPP/405` ↔ `MBPP/567` | unrelated | Tuple membership versus sortedness of a list are distinct Boolean predicates. |
| 61 | `MBPP/140` ↔ `MBPP/490` | related_distinct | Singleton occurrence extraction and finding symmetric tuple-pairs share tuple-list processing but have distinct predicates. |
| 62 | `MBPP/212` ↔ `MBPP/287` | near_equivalent | Both evaluate power sums over first n integers; exponent four over naturals versus squares over evens changes parameters. |
| 63 | `MBPP/309` ↔ `MBPP/501` | unrelated | Maximum of two numbers versus common-divisor calculation are distinct arithmetic functions. |
| 64 | `MBPP/436` ↔ `MBPP/852` | near_equivalent | Both identify negative values in a list; printing negatives versus removing negatives differs in output and filter polarity. |
| 65 | `MBPP/95` ↔ `MBPP/457` | near_equivalent | Same minimum-length sublist scan; one returns minimum length, the other returns the minimizing sublist. |
| 66 | `MBPP/707` ↔ `MBPP/903` | needs_contract_review | Total set bits versus total unset bits are complementary only given an explicit bit-width policy, which the prompts omit. |
| 67 | `MBPP/25` ↔ `MBPP/777` | near_equivalent | Same detection of non-repeated elements; product versus sum changes the aggregation operator. |
| 68 | `MBPP/497` ↔ `MBPP/731` | near_equivalent | Same cone geometry; total surface area adds base area to lateral area. |
| 69 | `MBPP/79` ↔ `MBPP/964` | near_equivalent | Odd versus even word-length predicates are complements on the same input domain. |
| 70 | `MBPP/106` ↔ `MBPP/413` | unrelated | Adding list elements to tuples and extracting the nth entry of each tuple solve different problems. |
| 71 | `MBPP/56` ↔ `MBPP/283` | unrelated | Digit reversal arithmetic relation and per-digit frequency bound are different number properties. |
| 72 | `MBPP/304` ↔ `MBPP/686` | unrelated | Element lookup after rotations versus counting list element frequencies are different algorithms. |
| 73 | `MBPP/422` ↔ `MBPP/634` | related_distinct | Average of cubes of naturals and sum of fourth powers of even naturals differ in exponent, sequence and aggregation. |
| 74 | `MBPP/472` ↔ `MBPP/683` | unrelated | Checking whether a list consists of consecutive integers and whether a number is sum of two squares differ. |
| 75 | `MBPP/527` ↔ `MBPP/767` | near_equivalent | Same target-sum pair enumeration; one returns all matching pairs and the other counts them. |
| 76 | `MBPP/319` ↔ `MBPP/330` | near_equivalent | Both regex word-length extraction; exactly five characters versus three/four/five characters differ in quantifier. |
| 77 | `MBPP/384` ↔ `MBPP/476` | related_distinct | Frequency of the minimum and sum of min and max differ in resulting statistic. |
| 78 | `MBPP/87` ↔ `MBPP/821` | near_equivalent | Same dictionary merge operation; two versus three input dictionaries changes arity only. |
| 79 | `MBPP/212` ↔ `MBPP/634` | near_equivalent | Same fourth-power sums; all naturals versus first n even naturals changes the sequence. |
| 80 | `MBPP/263` ↔ `MBPP/821` | equivalent | Both merge two dictionaries into one; the phrase "single expression" suggests an implementation preference, not a different result. |
| 81 | `MBPP/476` ↔ `MBPP/588` | near_equivalent | Both use maximum and minimum in an array; sum versus difference changes one arithmetic operator. |
