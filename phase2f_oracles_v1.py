#!/usr/bin/env python3
"""Trusted, handwritten, DEVELOPMENT-only dual-oracle implementations.

NEVER import or execute model-generated code in this module. This is not a
proof of correctness; agreement is triangulated with bounded exhaustive checks.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from itertools import permutations, product
import math
import random
import string

# Exact public prompt digests from the reviewed Phase-2D source packet.
TASKS = {
    'HumanEval/129': ('minPath', 'list', '670be092d953b4e25085e2d70bff872c2a78ad2bc3818d5de2842e79f95b1eb3', '417c9ed701884d14aff5ce42047f77711731af279eeeba3d3b685b92a8f29adb'),
    'HumanEval/69': ('search', 'int', '16ac640af04cdc0c32c1800501d5eacb7f04046f25aff2b9e4b33ddaa8578870', '62a5a2d0332d73a27da26ab1a46a7302d27bff719d9d354887d0a27a7cdc776a'),
    'HumanEval/112': ('reverse_delete', 'tuple', 'a363c6ac3bf8f70c9df33afa96bb8f9103f101726333206530602e165498d2bc', '1a0e5435912522547470d17b91604c47dbff24e81d145a7f2b79c281eef6b033'),
    'HumanEval/90': ('next_smallest', 'int_or_none', '134b146d85ca1bac613d96c5e419eec6097cd5076901416d24c4e99400fdc891', 'c411484e97c83ae8e5869ae414e5687f429deda4f5fb49e367e60c85635fed1e'),
    'HumanEval/111': ('histogram', 'dict', '03f92926d51519bbd8b443298f0cec9ce3557c9590073fd5d33ecc662bb55c75', 'c30d14cdaa12a3c8fd5b0cf5ce64622c84276ea5f9709d0494b836617938da59'),
    'HumanEval/74': ('total_match', 'list', 'db4f95f4b8c1d5a6f56380aa0401f3859befa6769726c83c7a01dc032083ac5d', '9662ed6743a83d0c34963151a98c5cdc9d33053cf3b26212adb7ff8abf9e3617'),
    'HumanEval/148': ('bf', 'tuple', 'e91f3cdaf02eb6f474d3a3abb103cd83f6e20412e60eb5ca4d7b7ce5252baa6c', '6cc1444376f53913622a070cd5c475b9cc33b4e199573da8e2b9051d689a314d'),
    'HumanEval/150': ('x_or_y', 'int', '9e4b1ac062dc2e140764496243c618bd82dc1975f67e6c65aca0e8779d795b1c', 'd3c5a3ef8fbe608f4c6ddb2b0209fe20ac537b827fb3252e805681c6c92c3a14'),
}

ORDER = tuple(TASKS)
PLANETS = ('Mercury', 'Venus', 'Earth', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune')
ALPHABET = string.ascii_letters + string.digits + " .,!?_-:;"


def ensure(condition, detail):
    if not condition:
        raise ValueError(detail)


def check_args(task, args):
    """Documented bounded initial DEVELOPMENT domain, not official benchmark domain."""
    ensure(task in TASKS and isinstance(args, list), 'task/args invalid')
    if task == 'HumanEval/129':
        ensure(len(args) == 2, 'minPath arity')
        grid, k = args
        ensure(isinstance(grid, list) and 2 <= len(grid) <= 4 and type(k) is int and 1 <= k <= 8, 'grid N/k bounds')
        n = len(grid)
        ensure(all(isinstance(row, list) and len(row) == n for row in grid), 'not square')
        items = [v for row in grid for v in row]
        ensure(all(type(v) is int for v in items) and sorted(items) == list(range(1, n*n+1)), 'not a permutation grid')
    elif task == 'HumanEval/69':
        ensure(len(args) == 1 and isinstance(args[0], list) and 1 <= len(args[0]) <= 60 and all(type(n) is int and 1 <= n <= 100 for n in args[0]), 'positive list bounds')
    elif task == 'HumanEval/112':
        ensure(len(args) == 2 and all(isinstance(v, str) and len(v) <= 80 and all(c in ALPHABET for c in v) for v in args), 'ASCII strings bounds')
    elif task == 'HumanEval/90':
        ensure(len(args) == 1 and isinstance(args[0], list) and len(args[0]) <= 80 and all(type(n) is int and -100 <= n <= 100 for n in args[0]), 'integer list bounds')
    elif task == 'HumanEval/111':
        ensure(len(args) == 1 and isinstance(args[0], str), 'histogram text required')
        s = args[0]
        ensure(s == '' or (len(s.split(' ')) <= 80 and all(len(t) == 1 and t in string.ascii_lowercase for t in s.split(' '))), 'single-space lower-case character tokens only')
    elif task == 'HumanEval/74':
        ensure(len(args) == 2 and all(isinstance(ls, list) and len(ls) <= 20 and all(isinstance(s, str) and len(s) <= 40 and all(c in ALPHABET for c in s) for s in ls) for ls in args), 'string-list bounds')
    elif task == 'HumanEval/148':
        ensure(len(args) == 2 and all(isinstance(v, str) and len(v) <= 30 for v in args), 'planet name strings required')
    elif task == 'HumanEval/150':
        ensure(len(args) == 3 and all(type(v) is int for v in args) and 0 <= args[0] <= 10000 and all(-1000 <= v <= 1000 for v in args[1:]), 'prime/branch bounds')


def neighbors(r, c, n):
    for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
        rr, cc = r + dr, c + dc
        if 0 <= rr < n and 0 <= cc < n:
            yield rr, cc


def minpath_greedy(grid, k):
    n = len(grid)
    row, col = next((r, c) for r in range(n) for c in range(n) if grid[r][c] == 1)
    result = [1]
    for _ in range(k - 1):
        row, col = min(neighbors(row, col, n), key=lambda pos: grid[pos[0]][pos[1]])
        result.append(grid[row][col])
    return result


def minpath_dp(grid, k):
    n = len(grid)
    @lru_cache(maxsize=None)
    def tail(r, c, steps):
        if steps == 1:
            return (grid[r][c],)
        return (grid[r][c],) + min(tail(nr, nc, steps - 1) for nr, nc in neighbors(r, c, n))
    return list(min(tail(r, c, k) for r in range(n) for c in range(n)))


def minpath_exhaustive(grid, k):
    n = len(grid)
    def paths(r, c, left):
        if left == 1:
            yield (grid[r][c],)
        else:
            for nr, nc in neighbors(r, c, n):
                for suffix in paths(nr, nc, left - 1):
                    yield (grid[r][c],) + suffix
    return list(min(path for r in range(n) for c in range(n) for path in paths(r, c, k)))


def frequency_counter(nums):
    counts = Counter(nums)
    return max((x for x, count in counts.items() if count >= x), default=-1)


def frequency_scan(nums):
    best = -1
    for candidate in nums:
        occurrences = 0
        for item in nums:
            if item == candidate:
                occurrences += 1
        if occurrences >= candidate and candidate > best:
            best = candidate
    return best


def delete_palindrome_filter(s, c):
    exclusions = set(c)
    text = ''.join(ch for ch in s if ch not in exclusions)
    return text, text == text[::-1]


def delete_palindrome_replace(s, c):
    text = s
    for ch in c:
        text = text.replace(ch, '')
    pal = True
    left, right = 0, len(text) - 1
    while left < right:
        if text[left] != text[right]:
            pal = False
            break
        left += 1
        right -= 1
    return text, pal


def second_sorted(nums):
    distinct = sorted(set(nums))
    return distinct[1] if len(distinct) > 1 else None


def second_scan(nums):
    first = second = None
    for x in nums:
        if first is None or x < first:
            second, first = first, x
        elif x != first and (second is None or x < second):
            second = x
    return second


def histogram_counter(s):
    if not s:
        return {}
    counts = Counter(s.split(' '))
    largest = max(counts.values())
    return {key: value for key, value in counts.items() if value == largest}


def histogram_scan(s):
    if s == '':
        return {}
    tokens = s.split(' ')
    counts = {}
    for token in tokens:
        if token not in counts:
            occurrences = 0
            for sample in tokens:
                occurrences += sample == token
            counts[token] = occurrences
    max_count = max(counts.values())
    return {key: value for key, value in counts.items() if value == max_count}


def total_match_sum(a, b):
    return a if sum(map(len, a)) <= sum(map(len, b)) else b


def total_match_iter(a, b):
    sizes = []
    for collection in (a, b):
        count = 0
        for word in collection:
            for _ in word:
                count += 1
        sizes.append(count)
    return a if sizes[0] <= sizes[1] else b


def planets_index(a, b):
    if a not in PLANETS or b not in PLANETS:
        return ()
    ai, bi = PLANETS.index(a), PLANETS.index(b)
    return PLANETS[min(ai, bi) + 1:max(ai, bi)]


def planets_filter(a, b):
    positions = {name: index for index, name in enumerate(PLANETS)}
    if a not in positions or b not in positions:
        return tuple()
    low, high = sorted((positions[a], positions[b]))
    return tuple(name for index, name in enumerate(PLANETS) if low < index < high)


def prime_trial(n):
    if n < 2:
        return False
    factor = 2
    while factor * factor <= n:
        if n % factor == 0:
            return False
        factor += 1
    return True


@lru_cache(maxsize=1)
def sieve_table():
    primes = bytearray([1]) * 10001
    primes[0] = primes[1] = 0
    for divisor in range(2, math.isqrt(10000) + 1):
        if primes[divisor]:
            for multiple in range(divisor * divisor, 10001, divisor):
                primes[multiple] = 0
    return primes


def select_trial(n, x, y):
    return x if prime_trial(n) else y


def select_sieve(n, x, y):
    return x if sieve_table()[n] else y


ORACLES = {
    'HumanEval/129': (minpath_greedy, minpath_dp),
    'HumanEval/69': (frequency_counter, frequency_scan),
    'HumanEval/112': (delete_palindrome_filter, delete_palindrome_replace),
    'HumanEval/90': (second_sorted, second_scan),
    'HumanEval/111': (histogram_counter, histogram_scan),
    'HumanEval/74': (total_match_sum, total_match_iter),
    'HumanEval/148': (planets_index, planets_filter),
    'HumanEval/150': (select_trial, select_sieve),
}


def oracle_pair(task, args):
    check_args(task, args)
    left, right = (fn(*args) for fn in ORACLES[task])
    if type(left) is not type(right) or left != right:
        raise AssertionError(f'ORACLE DISAGREEMENT: {task}: {args!r}; {left!r} vs {right!r}')
    return left


def exhaustively_selfcheck():
    """Small-domain exhaustive triangulation; trusted handwritten code only."""
    counts = Counter()
    def verify(task, args):
        oracle_pair(task, args)
        counts[task] += 1
    # Every 2x2 permutation and k=1..8. Triangulate against brute paths k<=6.
    for values in permutations(range(1, 5)):
        grid = [list(values[:2]), list(values[2:])]
        for k in range(1, 9):
            expected = oracle_pair('HumanEval/129', [grid, k])
            counts['HumanEval/129'] += 1
            if k <= 6 and expected != minpath_exhaustive(grid, k):
                raise AssertionError('Exhaustive minPath oracle disagrees')
    for length in range(1, 7):
        for values in product((1, 2, 3, 4), repeat=length):
            verify('HumanEval/69', [list(values)])
    for n in range(0, 7):
        for letters in product('aB', repeat=n):
            s = ''.join(letters)
            for c in ('', 'a', 'B', 'aB', 'BBa'):
                verify('HumanEval/112', [s, c])
    for n in range(0, 6):
        for values in product((-2, -1, 0, 1, 2), repeat=n):
            verify('HumanEval/90', [list(values)])
    for n in range(0, 7):
        for values in product(('a', 'b', 'c'), repeat=n):
            verify('HumanEval/111', [' '.join(values)])
    choices = ([], [''], ['a'], ['BB'], ['', 'a'])
    for a in choices:
        for b in choices:
            verify('HumanEval/74', [a, b])
    for a in PLANETS + ('Pluto', 'earth', ''):
        for b in PLANETS + ('Pluto', 'earth', ''):
            verify('HumanEval/148', [a, b])
    for n in range(10001):
        verify('HumanEval/150', [n, 42, -19])
    examples = [
        ('HumanEval/129', [[[1, 2, 3], [4, 5, 6], [7, 8, 9]], 3], [1, 2, 1]),
        ('HumanEval/69', [[4, 1, 2, 2, 3, 1]], 2),
        ('HumanEval/112', ['abcdedcba', 'ab'], ('cdedc', True)),
        ('HumanEval/90', [[1, 1]], None),
        ('HumanEval/111', ['a b a b'], {'a': 2, 'b': 2}),
        ('HumanEval/74', [['hi', 'admin'], ['hI', 'Hi']], ['hI', 'Hi']),
        ('HumanEval/148', ['Earth', 'Mercury'], ('Venus',)),
        ('HumanEval/150', [7, 34, 12], 34),
    ]
    for task, args, expected in examples:
        actual = oracle_pair(task, args)
        if type(actual) is not type(expected) or actual != expected:
            raise AssertionError(f'Public example mismatch for {task}: {actual!r} != {expected!r}')
        counts[task] += 1
    # Verify fail-closed input-domain handling.
    for task, args in [
        ('HumanEval/129', [[[1, 2], [3, 3]], 2]),
        ('HumanEval/69', [[0]]),
        ('HumanEval/112', ['é', 'a']),
        ('HumanEval/90', [[True]]),
        ('HumanEval/111', ['a  b']),
        ('HumanEval/74', [['é'], []]),
        ('HumanEval/148', [3, 'Mars']),
        ('HumanEval/150', [False, 1, 2]),
    ]:
        try:
            oracle_pair(task, args)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid domain accepted: {task} {args!r}')
    return dict(sorted(counts.items()))


def seed_cases(task):
    return {
        'HumanEval/129': [
            [[[1, 2], [3, 4]], 1], [[[1, 2], [3, 4]], 8],
            [[[4, 2], [3, 1]], 4],
            [[[1, 2, 3], [4, 5, 6], [7, 8, 9]], 3],
            [[[5, 9, 3], [4, 1, 6], [7, 8, 2]], 1],
        ],
        'HumanEval/69': [
            [[1]], [[2]], [[2, 2]], [[1, 1, 1]],
            [[4, 1, 2, 2, 3, 1]], [[1, 2, 2, 3, 3, 3, 4, 4, 4]],
            [[5, 5, 4, 4, 4]],
        ],
        'HumanEval/112': [
            ['', ''], ['a', 'a'], ['abba', ''],
            ['abcde', 'ae'], ['abcdef', 'b'], ['abcdedcba', 'ab'],
            ['aAa', 'A'], ['aabb', 'ab'], ['', 'abc'],
        ],
        'HumanEval/90': [
            [[]], [[1]], [[1, 1]], [[1, 2]], [[2, 1]],
            [[-2, -2, -1, -1]], [[5, 1, 4, 3, 2]], [[1, 2, 3, 4, 5]],
        ],
        'HumanEval/111': [
            [''], ['a'], ['a b c'], ['a b b a'], ['a b c a b'],
            ['b b b b a'], ['a a a b b'],
        ],
        'HumanEval/74': [
            [[], []], [['hi', 'admin'], ['hI', 'Hi']],
            [['4'], ['1', '2', '3', '4', '5']], [[], ['']],
            [['a'], ['b']], [['abc'], []],
        ],
        'HumanEval/148': [
            ['Jupiter', 'Neptune'], ['Earth', 'Mercury'],
            ['Mercury', 'Uranus'], ['Neptune', 'Mercury'],
            ['Mercury', 'Mercury'], ['Earth', 'Pluto'],
        ],
        'HumanEval/150': [
            [0, 34, 12], [1, 34, 12], [2, 34, 12], [7, 34, 12],
            [15, 8, 5], [97, 7, -2], [10000, -1, 3], [9991, 100, 200],
        ],
    }[task]


def random_case(task, rng):
    if task == 'HumanEval/129':
        n = rng.choice([2, 3, 4])
        values = list(range(1, n*n+1))
        rng.shuffle(values)
        return [[values[i*n:(i+1)*n] for i in range(n)], rng.randint(1, 8)]
    if task == 'HumanEval/69':
        length = rng.randint(1, 60)
        return [[rng.choice((rng.randint(1, 8), rng.randint(1, 100), 1, 2, 3)) for _ in range(length)]]
    if task == 'HumanEval/112':
        def word(n):
            return ''.join(rng.choice('abABcCdDeE') for _ in range(n))
        s = word(rng.randint(0, 80))
        c = word(rng.randint(0, 25))
        if rng.random() < 0.2:
            s = s[:40] + s[:40][::-1]
        return [s, c]
    if task == 'HumanEval/90':
        if rng.random() < 0.25:
            minimum = rng.randint(-100, 20)
            return [[minimum, minimum] + [rng.randint(minimum + 1, 100)
                                           for _ in range(rng.randint(0, 20))]]
        return [[rng.randint(-100, 100) if rng.random() < 0.3 else rng.randint(-5, 5)
                 for _ in range(rng.randint(0, 80))]]
    if task == 'HumanEval/111':
        return [' '.join(rng.choice('aaabbbcccde') for _ in range(rng.randint(0, 80)))]
    if task == 'HumanEval/74':
        def words():
            return [''.join(rng.choice('abABC') for _ in range(rng.randint(0, 40)))
                    for _ in range(rng.randint(0, 20))]
        if rng.random() < 0.3:
            # Guaranteed equal total character counts but distinguishable lists.
            a = [''.join(rng.choice('abABC') for _ in range(rng.randint(1, 40)))
                 for _ in range(rng.randint(2, 12))]
            b = list(reversed(a))
            if b == a:
                b = [s[::-1] for s in a]
            return [a, b]
        return [words(), words()]
    if task == 'HumanEval/148':
        options = PLANETS + ('Pluto', 'earth', 'MERCURY', '')
        return [rng.choice(options), rng.choice(options)]
    if task == 'HumanEval/150':
        return [rng.randint(0, 10000), rng.randint(-1000, 1000), rng.randint(-1000, 1000)]
    raise KeyError(task)


def make_cases(task, count=128, seed=270219):
    import json
    if task not in TASKS or count < 1 or count > 2048:
        raise ValueError('Unexpected task/count')
    rng = random.Random(seed + sum(ord(c) for c in task))
    raw = seed_cases(task)
    seen, cases = set(), []
    attempts = 0
    while len(cases) < count:
        args = raw.pop(0) if raw else random_case(task, rng)
        check_args(task, args)
        key = json.dumps(args, sort_keys=True, separators=(',', ':'), allow_nan=False)
        attempts += 1
        if attempts > 20000:
            raise AssertionError('Input generator failed uniqueness budget')
        if key in seen:
            continue
        seen.add(key)
        cases.append({'name': f'dev2f_{task.split("/")[-1]}_{len(cases)+1:03}', 'args': args,
                      'expected_type': TASKS[task][1]})
    return cases
