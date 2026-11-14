#!/usr/bin/env python3
"""Read-only verification of installed v2 quarantine guard and task permissions."""
from __future__ import annotations

from pathlib import Path

from phase2d_quarantine_guard import (
    KNOWN_QUARANTINE, PILOT_TASKS, TaskPolicyError, require_task_permission,
)
from phase2d_install_quarantine import EDITS, OPTIONAL_EDITS, MARKER, prepare

ROOT = Path(__file__).resolve().parent


def main() -> int:
    print("QUARANTINE POLICY V2 SELF-CHECK -- READ-ONLY")
    missing = []
    for name in list(EDITS) + list(OPTIONAL_EDITS):
        path = ROOT / name
        if not path.exists() and name in OPTIONAL_EDITS:
            continue
        if not path.is_file() or MARKER not in path.read_text(encoding="utf-8"):
            missing.append(name)
    if missing:
        print("UNGUARDED ENTRY POINTS:", ", ".join(missing))
        return 2
    try:
        unpatched, _ = prepare(ROOT)
    except (ValueError, OSError) as exc:
        print("INCOMPLETE PATCH:", exc)
        return 2
    if unpatched:
        print("UNGUARDED ENTRY POINTS:", ", ".join(str(x.relative_to(ROOT)) for x in unpatched))
        return 2
    print("All known installed entry points have exact guard patch snippets (v1 hooks use v2 shared policy).")

    blocked = []
    for task_id in sorted(KNOWN_QUARANTINE):
        for intent in ("generate", "evaluate"):
            try:
                require_task_permission(ROOT, task_id, intent)
            except TaskPolicyError as exc:
                if not str(exc).startswith("QUARANTINED:"):
                    print("POLICY ERROR:", str(exc))
                    return 2
                blocked.append((task_id, intent))
            else:
                print("POLICY FAILURE: unexpectedly permitted", task_id, intent)
                return 2
    print("QUARANTINE BLOCKS:", len(blocked), "of", len(KNOWN_QUARANTINE)*2)

    allowed = []
    for task_id in sorted(PILOT_TASKS):
        try:
            require_task_permission(ROOT, task_id, "evaluate")
            allowed.append(task_id)
        except TaskPolicyError as exc:
            print("PILOT POLICY ERROR:", str(exc))
            return 2
    print("EXISTING PILOT PERMISSIONS:", len(allowed), "of", len(PILOT_TASKS))
    try:
        require_task_permission(ROOT, "BigCodeBench/854", "evaluate")
    except TaskPolicyError as exc:
        print("BCB/854 CURRENT POLICY:", str(exc))
    else:
        print("BCB/854 permission requires separate suite/evaluator approval")
    print("GUARD SELF-CHECK PASSED. No models, candidates, Docker or private tests accessed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
