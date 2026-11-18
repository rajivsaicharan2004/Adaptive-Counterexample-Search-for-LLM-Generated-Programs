#!/usr/bin/env python3
"""Trusted synthetic-mutant controls; NOT real LLM failures or a strategy comparison."""
import argparse
import hashlib
import json
from pathlib import Path

import phase2f_oracles_v1 as O

ROOT = Path(__file__).resolve().parent


def mutant(task, args):
    # Trusted, deliberately faulty implementations; never model-generated code.
    if task == 'HumanEval/129':
        grid, k = args
        result = O.minpath_greedy(grid, min(k, len(grid)**2))
        return result  # incorrectly caps path length, prohibiting revisits
    if task == 'HumanEval/69':
        nums, = args
        count = {v: nums.count(v) for v in set(nums)}
        return min((v for v, n in count.items() if n >= v), default=-1)  # selects min, not max
    if task == 'HumanEval/112':
        s, c = args
        reduced = ''.join(ch for ch in s if ch not in c)
        return reduced, False  # incorrectly rejects all palindromes
    if task == 'HumanEval/90':
        nums, = args
        return sorted(nums)[1] if len(nums) >= 2 else None  # duplicate-min bug
    if task == 'HumanEval/111':
        s, = args
        counts = {}
        for token in s.split():
            counts[token] = counts.get(token, 0) + 1
        if not counts:
            return {}
        maximum = max(counts.values())
        first = next(word for word, val in counts.items() if val == maximum)
        return {first: maximum}  # erroneously discards ties
    if task == 'HumanEval/74':
        a, b = args
        return a if sum(map(len, a)) < sum(map(len, b)) else b  # tie bug
    if task == 'HumanEval/148':
        a, b = args
        if a not in O.PLANETS or b not in O.PLANETS:
            return ()
        ai, bi = O.PLANETS.index(a), O.PLANETS.index(b)
        return O.PLANETS[ai+1:bi]  # wrong when reversed
    if task == 'HumanEval/150':
        n, x, y = args
        return x if n == 1 or O.prime_trial(n) else y  # 1 is wrongly prime
    raise KeyError(task)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-frozen', action='store_true', help='Use project frozen challenge inputs and verify labels')
    args = parser.parse_args()
    from phase2f_prepare_dev_suite_v1 import INPUTS_REL, LABELS_REL
    if args.from_frozen:
        inputs = json.loads((ROOT / INPUTS_REL).read_text(encoding='utf-8'))
        labels = json.loads((ROOT / LABELS_REL).read_text(encoding='utf-8'))
        if hashlib.sha256((ROOT / INPUTS_REL).read_bytes()).hexdigest() != labels['test_inputs_sha256']:
            raise RuntimeError('Frozen challenge hash mismatch')
    else:
        inputs = {'tasks': {t: {'cases': O.make_cases(t)} for t in O.ORDER}}
    results = {}
    for task in O.ORDER:
        cases = inputs['tasks'][task]['cases']
        failures = []
        for item in cases:
            ref = O.oracle_pair(task, item['args'])
            bad = mutant(task, item['args'])
            if type(ref) is not type(bad) or ref != bad:
                failures.append(item['name'])
        if not failures:
            raise AssertionError(f'Fault sensitivity failure: {task} mutant survived entire suite')
        results[task] = {'test_cases': len(cases), 'mutant_detected': True,
                         'failing_cases': len(failures), 'first_failing_case': failures[0]}
        print(f'{task}: synthetic mutant detected on {len(failures)}/{len(cases)} cases')
    print('ALL 8 HANDWRITTEN SYNTHETIC MUTANTS DETECTED')
    print('Not an LLM correctness result, coverage proof, or fair baseline comparison.')
    print('No candidate code, Docker, model, policy modification, or file writes.')


if __name__ == '__main__':
    main()
