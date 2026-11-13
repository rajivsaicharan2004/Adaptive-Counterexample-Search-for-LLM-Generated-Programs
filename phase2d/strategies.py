"""Common testing strategies. Task-specific contracts are deliberate and explicit.

Strategies return inputs or investigation signals; only a vetted oracle may
provide correctness labels. This is NOT a universal generator for 3,333 tasks.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Callable
import json
import random
import time
from .models import canonical, TaskSpec, CostLedger

SUPPORTED = ("HumanEval/0", "HumanEval/1", "MBPP/545")


def valid_args(task_id: str, args: list) -> bool:
    import math
    if task_id == "HumanEval/0":
        if not isinstance(args, list) or len(args) != 2:
            return False
        nums, t = args
        return (type(nums) is list and len(nums) <= 20 and
                all(type(x) in (int, float) and math.isfinite(x) and abs(x) <= 300 for x in nums)
                and type(t) in (int, float) and math.isfinite(t) and 0 <= t <= 300)
    if task_id == "HumanEval/1":
        if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
            return False
        s = args[0]
        if not 0 < len(s) <= 240 or any(c not in "() " for c in s):
            return False
        depth, groups = 0, 0
        for ch in s:
            if ch == "(": depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0: return False
                if depth == 0: groups += 1
        return depth == 0 and 1 <= groups <= 12
    if task_id == "MBPP/545":
        return isinstance(args, list) and len(args) == 1 and type(args[0]) is int and 1 <= args[0] <= 2**24
    raise ValueError(f"No reviewed input contract implemented for {task_id}")


def unique_args(items: list[list], limit: int, task_id: str) -> list[list]:
    seen, results = set(), []
    for item in items:
        if not valid_args(task_id, item):
            continue
        key = canonical(item)
        if key in seen:
            continue
        results.append(item)
        seen.add(key)
        if len(results) == limit:
            break
    return results


def property_inputs(task_id: str, count: int, seed_value: int) -> list[list]:
    """Fresh seeded Hypothesis examples, unlike legacy derandomize=True behavior."""
    try:
        from hypothesis import seed as hypothesis_seed, given, settings, strategies as st
    except ImportError as exc:
        raise RuntimeError("Install Hypothesis: .venv/bin/python -m pip install 'hypothesis>=6,<7'") from exc
    if not 1 <= count <= 500:
        raise ValueError("count must be 1..500")
    if task_id == "HumanEval/0":
        @st.composite
        def close_elements(draw):
            nums = [x/4.0 for x in draw(st.lists(st.integers(-120,120),min_size=0,max_size=12))]
            mode = draw(st.sampled_from(("regular","zero","pair_boundary","near_pair")))
            if mode == "zero":
                threshold = 0.0
            elif mode in ("pair_boundary","near_pair") and len(nums) >= 2:
                i = draw(st.integers(0,len(nums)-1))
                j = draw(st.integers(0,len(nums)-2))
                if j >= i: j += 1
                distance = abs(nums[i]-nums[j])
                delta = draw(st.sampled_from((-0.25,0,0.25))) if mode == "near_pair" else 0
                threshold = max(0.0,distance + delta)
            else:
                threshold = draw(st.integers(0,120))/4.0
            return [nums,float(threshold)]
        strategy = close_elements()
    elif task_id == "HumanEval/1":
        groups = st.recursive(st.just("()"),
                 lambda children: st.lists(children,min_size=1,max_size=3).map(
                     lambda parts: "("+"".join(parts)+")"),max_leaves=12)
        @st.composite
        def parentheses(draw):
            elements = draw(st.lists(groups,min_size=1,max_size=4))
            text = "".join(elements)
            spaces = draw(st.lists(st.integers(0,2),min_size=len(text)+1,max_size=len(text)+1))
            return ["".join(" "*spaces[i] + char for i,char in enumerate(text)) + " "*spaces[-1]]
        strategy = parentheses()
    elif task_id == "MBPP/545":
        strategy = st.tuples(st.integers(min_value=1, max_value=2**24)).map(list)
    else:
        raise ValueError("No Hypothesis strategy for this task yet")
    unique = []
    seen = set()
    @hypothesis_seed(seed_value)
    @settings(max_examples=min(2500, max(count * 5, 60)), deadline=None,
              derandomize=False, database=None)
    @given(args=strategy)
    def collect(args):
        if not valid_args(task_id, args):
            return
        key = canonical(args)
        if key not in seen:
            seen.add(key)
            unique.append(args)
    collect()
    if len(unique) < count:
        raise RuntimeError(f"Only {len(unique)} unique inputs generated out of {count} requested")
    return unique[:count]


def mutation_inputs(task_id: str, seeds: list[list], count: int, seed_value: int) -> list[list]:
    if not 1 <= count <= 500:
        raise ValueError("count must be 1..500")
    if not seeds or any(not valid_args(task_id, x) for x in seeds):
        raise ValueError("Need task-valid mutation seeds")
    rng = random.Random(seed_value)
    known = {canonical(x) for x in seeds}
    out = []
    if task_id in ("HumanEval/0", "HumanEval/1"):
        import phase2b2_mutation as legacy
        mutate = legacy.mutate_numbers if task_id == "HumanEval/0" else legacy.mutate_parens
    else:
        mutate = None
    attempts = 0
    while len(out) < count and attempts < count*150 + 500:
        attempts += 1
        original = rng.choice(seeds)
        if mutate:
            proposed = mutate(original, rng)
            args = proposed[0] if proposed else None
        else:
            n = original[0]
            bit = rng.randrange(0, max(1, n.bit_length()+2))
            op = rng.choice(("toggle", "increase", "decrease", "shift"))
            changed = ((n ^ (1 << bit)) if op == "toggle" else
                       n + (1 << bit) if op == "increase" else
                       max(1, n - (1 << bit)) if op == "decrease" else
                       n << rng.randint(1, 4))
            args = [changed]
        if args is not None and valid_args(task_id, args):
            key = canonical(args)
            if key not in known:
                out.append(args)
                known.add(key)
    if len(out) < count:
        raise RuntimeError(f"Could not generate {count} unique valid mutations")
    return out


def metamorphic_pairs(task_id: str, inputs: list[list], count: int, seed_value: int) -> list[dict]:
    if task_id not in ("HumanEval/0", "HumanEval/1"):
        raise ValueError("Metamorphic relations have not been reviewed for this task")
    import phase2b4_metamorphic as legacy
    sources = [{"name": f"seed_{i}", "args": x} for i, x in enumerate(inputs)]
    pairs, _ = legacy.generate_pairs(task_id, sources, count, seed_value)
    return pairs


def coverage_guided_inputs(task_id: str, candidate_code: str, entry: str, interface: str,
                           seeds: list[list], sandbox, ledger: CostLedger,
                           *, budget: int = 20, seed_value: int = 2026) -> dict:
    """Adaptive LINE-coverage-guided input mutation for the three pilot tasks.

    Inputs discovering new candidate lines join the future mutation frontier.
    This is a simple coverage-guided prototype, NOT Atheris/libFuzzer or full
    branch-coverage instrumentation. Every tested input uses one Docker call.
    """
    if budget < 1 or budget > 500:
        raise ValueError("Budget must be 1..500")
    if not seeds or any(not valid_args(task_id, seed) for seed in seeds):
        raise ValueError("Need reviewed valid seeds")
    rng = random.Random(seed_value)
    frontier = list(seeds)
    seed_pool = list(seeds)
    covered, discovered, trials, seen = set(), [], [], set()
    for step in range(budget):
        choice = None
        # Deliberate exploration, plus exploitation of coverage-producing inputs.
        for _ in range(40):
            parent = rng.choice(frontier if rng.random() < 0.8 else seed_pool)
            try:
                proposed = mutation_inputs(task_id, [parent], 1, rng.randrange(2**31))
            except RuntimeError:
                continue
            key = canonical(proposed[0])
            if key not in seen:
                choice = proposed[0]
                seen.add(key)
                break
        if choice is None:
            break
        got, elapsed = sandbox.run(candidate_code, entry, interface, [{"args": choice}], coverage=True)
        ledger.record_executions("candidate", 1, elapsed)
        lines = set(got[0].get("line_coverage", []))
        gained = sorted(lines - covered)
        if gained:
            covered.update(lines)
            discovered.append(choice)
            frontier.append(choice)
            if len(frontier) > 150:
                frontier = seed_pool + frontier[-100:]
        trials.append({"args": choice, "parent_frontier_size": len(frontier),
                       "new_covered_lines": gained, "status": got[0].get("status")})
    return {"selected": discovered, "unique_lines": len(covered), "trials": trials,
            "attempted_executions": len(trials),
            "note": "feedback-guided line novelty; not independent branch coverage or full fuzzing"}


def disagreement_rank(candidate_code: str, probe_code: str, entry: str,
                     interface: str, inputs: list[list], sandbox,
                     ledger: CostLedger, *, max_executions: int = 40) -> dict:
    """Compare same inputs, prioritize disagreements; no oracle, not correctness proof."""
    if max_executions < 2:
        raise ValueError("Requires at least two executions")
    disagreements = []
    examined = 0
    for args in inputs[:max_executions//2]:
        left, lt = sandbox.run(candidate_code, entry, interface, [{"args": args}])
        right, rt = sandbox.run(probe_code, entry, interface, [{"args": args}])
        ledger.record_executions("candidate", 1, lt)
        ledger.record_executions("probe", 1, rt)
        examined += 1
        signature_a = canonical([left[0].get("status"), left[0].get("type"), left[0].get("value"), left[0].get("error_type")])
        signature_b = canonical([right[0].get("status"), right[0].get("type"), right[0].get("value"), right[0].get("error_type")])
        if signature_a != signature_b:
            disagreements.append({"args": args, "candidate": left[0], "probe": right[0]})
    return {"inputs_examined": examined, "candidate_and_probe_executions": 2*examined,
            "disagreements": disagreements, "oracle_verified": False}


def shrink_failure(task_id: str, input_args: list,
                   still_fails: Callable[[list], bool], *, max_checks: int = 100) -> dict:
    """Greedy failure-preserving minimizer. Caller must check failure in Docker;
    labels must come from a vetted development oracle.
    """
    if not valid_args(task_id, input_args):
        raise ValueError("Invalid initial input")
    current = input_args
    checks = 0
    if not still_fails(current):
        raise ValueError("Initial input does not reproduce failure")
    checks += 1
    while checks < max_checks:
        options = []
        if task_id == "HumanEval/0":
            nums, threshold = current
            options.extend([[nums[:i]+nums[i+1:], threshold] for i in range(len(nums))])
            options.extend([[nums, t] for t in (0.0, threshold/2) if t != threshold])
        elif task_id == "HumanEval/1":
            text = current[0]
            options.extend([[text[:i]+text[i+1:]] for i,c in enumerate(text) if c == " "])
            options.extend([[text[:i]+text[i+2:]] for i in range(len(text)-1) if text[i:i+2] == "()"])
        elif task_id == "MBPP/545":
            n = current[0]
            options.extend([[max(1,n//2)], [1], [max(1,n-1)]])
        old_weight = len(canonical(current))
        improved = False
        for proposal in options:
            if not valid_args(task_id, proposal) or len(canonical(proposal)) >= old_weight:
                continue
            checks += 1
            if still_fails(proposal):
                current = proposal
                improved = True
                break
            if checks >= max_checks: break
        if not improved:
            break
    return {"original": input_args, "minimized": current, "predicate_checks": checks,
            "note": "greedy minimization; no guarantee of globally smallest counterexample"}


def llm_test_inputs(spec: TaskSpec, count: int, client, model: str,
                    ledger: CostLedger, *, max_output_tokens: int = 2048) -> dict:
    """Opt-in LLM test suggestions from PUBLIC specification only.

    Returns valid JSON-compatible input candidates, never expected outputs.
    """
    import phase1_generator as generator
    if spec.task_id not in SUPPORTED:
        raise ValueError("Pilot task input contract is not registered")
    prompt = ("Create difficult valid test inputs for this Python task. "
              "Return ONLY a JSON array of arrays, each inner array being positional function args. "
              "No expected answers, markdown, or Python code. Generate boundary and structural cases. "
              f"At most {count*2} examples. Task: {spec.prompt[:12000]}")
    started = time.perf_counter()
    ledger.model_calls += 1  # Count attempted API calls, including errors.
    try:
        response = generator.call_gemini(client, model, prompt, 0.9, max_output_tokens)
    finally:
        ledger.model_latency_seconds += time.perf_counter()-started
    if response.get("finish_reason") != "STOP":
        raise ValueError(
            "Gemini test-input response did not finish normally: "
            f"{response.get('finish_reason')!r}"
        )
    usage = response.get("usage", {})
    ledger.input_tokens += usage.get("prompt_token_count") or 0
    ledger.output_tokens += usage.get("candidates_token_count") or 0
    text = generator.strip_fence(response.get("text", ""))
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("Model did not produce array of argument arrays")
    ledger.generated_inputs += len(parsed)
    values = unique_args(parsed, count, spec.task_id)
    ledger.accepted_inputs += len(values)
    return {"inputs": values, "requested": count, "parsed": len(parsed),
            "accepted": len(values), "oracle_labels": None,
            "model": model, "prompt_sha256": __import__("hashlib").sha256(prompt.encode()).hexdigest(),
            "warning": "LLM-produced tests remain unverified until compared with a reviewed oracle"}
