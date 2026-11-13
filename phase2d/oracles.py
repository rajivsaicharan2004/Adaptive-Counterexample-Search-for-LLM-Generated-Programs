"""Explicitly authored DEVELOPMENT reference behavior for three PILOT tasks.

NOT official HumanEval/MBPP evaluation tests. These reference rules must not
be used as hidden held-out judging or generalize silently to other tasks.
"""
from __future__ import annotations


def development_oracle(task_id: str, args: list):
    if task_id == "HumanEval/0":
        nums, threshold = args
        return any(abs(nums[i] - nums[j]) < threshold
                   for i in range(len(nums)) for j in range(i+1, len(nums)))
    if task_id == "HumanEval/1":
        raw = args[0].replace(" ", "")
        groups, depth, start = [], 0, 0
        for i, ch in enumerate(raw):
            if ch == "(": depth += 1
            else: depth -= 1
            if depth == 0:
                groups.append(raw[start:i+1])
                start = i + 1
        return groups
    if task_id == "MBPP/545":
        n = args[0]
        return n ^ (1 | (1 << (n.bit_length()-1)))
    raise ValueError("A reviewed development oracle is not implemented for this task")
