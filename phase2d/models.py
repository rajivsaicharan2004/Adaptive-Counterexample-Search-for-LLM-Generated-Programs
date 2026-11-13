"""Schemas, safe comparisons, and explicit execution accounting."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import hashlib
import json
import math
import time

METHODS = ("direct", "sampling", "diverse", "plan", "mcts", "evolution", "beam", "adaptive")
DATASETS = ("humaneval", "mbpp", "bigcodebench", "livecodebench")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskSpec:
    dataset: str
    task_id: str
    prompt: str
    entry_point: str | None
    interface: str  # callable | leetcode_method | stdin_stdout (not executable yet)
    starter_code: str = ""
    comparison: str = "exact"  # exact | numeric | unordered_list
    abs_tol: float = 0.0
    rel_tol: float = 0.0
    image: str | None = None
    requires_dependencies: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Case:
    name: str
    args: list
    expected: Any
    expected_type: str | None = None


@dataclass
class CostLedger:
    candidate_executions: int = 0
    reference_executions: int = 0
    probe_executions: int = 0
    generated_inputs: int = 0
    accepted_inputs: int = 0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_latency_seconds: float = 0.0
    execution_seconds: float = 0.0
    total_usd: float | None = None
    started: float = field(default_factory=time.perf_counter, repr=False)

    def record_executions(self, role: str, count: int, elapsed: float) -> None:
        if role not in ("candidate", "reference", "probe"):
            raise ValueError(f"Unknown execution role: {role}")
        if count < 0 or elapsed < 0:
            raise ValueError("Counts and time cannot be negative")
        setattr(self, role + "_executions", getattr(self, role + "_executions") + count)
        self.execution_seconds += elapsed

    def snapshot(self) -> dict:
        return {**{k: v for k, v in asdict(self).items() if k != "started"},
                "elapsed_seconds": round(time.perf_counter() - self.started, 3)}


def value_equal(actual: Any, expected: Any, mode: str, abs_tol: float, rel_tol: float) -> bool:
    """Type-safe recursive comparison; booleans are NOT equal to 0/1."""
    if mode == "unordered_list":
        if type(actual) is not list or type(expected) is not list:
            return False
        try:
            return sorted(canonical(x) for x in actual) == sorted(canonical(x) for x in expected)
        except (TypeError, ValueError):
            return False
    if mode not in ("exact", "numeric"):
        raise ValueError(f"Unknown comparison mode: {mode}")
    if mode == "numeric" and type(actual) in (int, float) and type(expected) in (int, float):
        return math.isfinite(actual) and math.isfinite(expected) and math.isclose(
            actual, expected, abs_tol=abs_tol, rel_tol=rel_tol)
    if type(actual) is not type(expected):
        return False
    if type(actual) is list:
        return len(actual) == len(expected) and all(
            value_equal(x, y, mode, abs_tol, rel_tol) for x, y in zip(actual, expected))
    if type(actual) is dict:
        return actual.keys() == expected.keys() and all(
            value_equal(actual[k], expected[k], mode, abs_tol, rel_tol) for k in actual)
    if type(actual) is float and not math.isfinite(actual):
        return False
    return actual == expected


def result_matches(result: dict, case: Case, spec: TaskSpec) -> bool:
    if result.get("status") != "ok":
        return False
    if case.expected_type and result.get("type") != case.expected_type:
        return False
    if spec.comparison == "exact":
        # JSON preserves root types for all supported cases except tuples,
        # which must be represented with an explicit task-specific adapter.
        expected_type = case.expected_type or type(case.expected).__name__
        if result.get("type") != expected_type:
            return False
    return value_equal(result.get("value"), case.expected, spec.comparison,
                       spec.abs_tol, spec.rel_tol)
