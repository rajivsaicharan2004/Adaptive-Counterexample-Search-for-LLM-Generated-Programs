#!/usr/bin/env python3
"""Read-only structural provenance gate for the versioned Phase 2B fairness pilot."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import sys

EXPECTED_HISTORICAL_SHA256 = '951bf1b9b898a81bf5f1ca18918a0a60155fcdacf0bb46b66075c441532a5aca'
EXPECTED_FAIR_CLONE_SHA256 = 'e3af520339a6c1fbd0fd9ac8e845e5d68b7bc7a416c5b6a039188a34a544368c'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(project: Path, *, check_installed_hypothesis: bool = True) -> dict:
    original = project / 'phase2b5_fault_benchmark.py'
    clone = project / 'phase2b5_fault_benchmark_fair_v1.py'
    strategy = project / 'phase2d' / 'strategies.py'
    for p in (original, clone, strategy):
        if not p.is_file():
            raise RuntimeError(f'Missing required source: {p}')
    if digest(original) != EXPECTED_HISTORICAL_SHA256:
        raise RuntimeError('Historical benchmark source differs from reviewed 951bf1b9... snapshot; do not proceed')
    if digest(clone) != EXPECTED_FAIR_CLONE_SHA256:
        raise RuntimeError('Fairness benchmark clone differs from verified package bytes; do not proceed')
    strategy_source = strategy.read_text(encoding='utf-8')
    if 'def property_inputs(' not in strategy_source:
        raise RuntimeError('Missing Phase 2D property_inputs strategy')
    if '@hypothesis_seed(seed_value)' not in strategy_source or 'derandomize=False' not in strategy_source:
        raise RuntimeError('Phase 2D seeded Hypothesis behavior not verified; do not proceed')
    if check_installed_hypothesis:
        if importlib.util.find_spec('hypothesis') is None:
            raise RuntimeError("Hypothesis not installed in active interpreter; install into your .venv")
    return {
        'status': 'PREFLIGHT PASSED -- READ-ONLY',
        'historical_benchmark_sha256': digest(original),
        'fairness_benchmark_sha256': digest(clone),
        'phase2d_strategies_sha256': digest(strategy),
        'hypothesis_importable': bool(importlib.util.find_spec('hypothesis')) if check_installed_hypothesis else 'not_checked',
        'historical_benchmark_modified': False,
        'manifest_modified': False,
        'docker_executed': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        report = check(args.project_root.resolve())
    except (OSError, RuntimeError) as e:
        print(f'PREFLIGHT FAILED CLOSED: {e}', file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
