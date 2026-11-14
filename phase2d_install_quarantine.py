#!/usr/bin/env python3
"""Conservative installer for the Phase 1 / Phase 2D quarantine guard.

--check: inspect exact insertion points without changing files (default)
--apply: make timestamped backups, then install checked one-line guard calls
Never changes the dataset files, manual review, or split manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
MARKER = "# phase2d_quarantine_guard:v1"

# Exact anchors based on the observed CLI source locations. All modifications
# are preflight-checked before any file is written.
EDITS = {
    "phase1_generator.py": (
        "    if n_calls > args.max_calls:\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, problem['task_id'], 'generate')\n",
    ),
    "phase1_advanced.py": (
        "    key = os.getenv(\"GEMINI_API_KEY\") or os.getenv(\"GOOGLE_API_KEY\")\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, problem['task_id'], 'generate')\n",
    ),
    "phase2d_cli.py": (
        "    split_file = (ROOT / args.splits_file).resolve()\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, args.task_id, 'evaluate')\n",
    ),
    "phase2d_bcb854_cli.py": (
        "    status, partition, fingerprint = manifest_state()\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, TASK_ID, 'evaluate')\n",
    ),
    "phase2d/engine.py": (
        "    if not 1 <= batch_size <= MAX_CASES_PER_BATCH:\n",
        "    " + MARKER + "\n"
        "    if execute:\n"
        "        from phase2d_quarantine_guard import require_task_permission\n"
        "        require_task_permission(root, task_id, 'evaluate')\n",
    ),
    "phase2d_strategy_cli.py": (
        "    args = p.parse_args()\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, args.task_id, 'evaluate')\n",
    ),
    "phase2d_replay.py": (
        '    dataset="mbpp" if task.startswith("MBPP/") else "humaneval"\n',
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, task, 'evaluate')\n",
    ),
    "phase2d_shrink_cli.py": (
        "    spec=public_task(ROOT,args.dataset,args.task_id)\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, args.task_id, 'evaluate')\n",
    ),
}
OPTIONAL_EDITS = {
    "phase2d_bcb146_mock.py": (
        "    if not allowed:\n",
        "    " + MARKER + "\n"
        "    from phase2d_quarantine_guard import require_task_permission\n"
        "    require_task_permission(ROOT, TASK_ID, 'evaluate')\n",
    ),
}


def prepare(root: Path) -> tuple[dict[Path, tuple[str, str]], list[str]]:
    work = {}
    report = []
    all_edits = {**EDITS, **OPTIONAL_EDITS}
    for name, (anchor, insertion) in all_edits.items():
        target = root / name
        if name in OPTIONAL_EDITS and not target.is_file():
            report.append(f"OPTIONAL ABSENT {name}")
            continue
        if not target.is_file() or target.is_symlink():
            raise ValueError(f"Required source file missing or is a symlink: {name}")
        original = target.read_text(encoding="utf-8")
        if MARKER in original:
            if insertion not in original:
                raise ValueError(f"Incomplete/unrecognized prior patch: {name}")
            report.append(f"ALREADY PATCHED {name}")
            continue
        if original.count(anchor) != 1:
            raise ValueError(f"Expected exactly one insertion anchor in {name}; found {original.count(anchor)}")
        changed = original.replace(anchor, insertion + anchor, 1)
        compile(changed, str(target), "exec")
        work[target] = (original, changed)
        report.append(f"READY TO PATCH {name}")
    return work, report


def write_atomic(target: Path, text: str) -> None:
    temporary = target.with_name(target.name + ".quarantine-tmp")
    if temporary.exists():
        raise FileExistsError(f"Temporary path already exists: {temporary}")
    try:
        with temporary.open("x", encoding="utf-8", newline="") as file:
            file.write(text)
        temporary.chmod(target.stat().st_mode)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--check", action="store_true", help="Inspect source anchors, no changes (default)")
    options.add_argument("--apply", action="store_true", help="Back up existing files and install guard calls")
    args = parser.parse_args(argv)

    try:
        if not (ROOT / "phase2d_quarantine_guard.py").is_file():
            raise ValueError("Install phase2d_quarantine_guard.py alongside this script")
        from phase2d_quarantine_guard import load_verified_policy
        manifest, ids = load_verified_policy(ROOT)
        print("REVIEW VERIFIED: manifest", manifest["status"], "| excluded tasks", len(ids))
        patchable, descriptions = prepare(ROOT)
        print("\n".join(descriptions))
        if not args.apply:
            print("CHECK COMPLETE. No files modified. Use --apply after reviewing the list.")
            return 0
        if not patchable:
            print("NO CHANGES: all supported entry points already patched.")
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_root = ROOT / "results" / "phase2d" / "patch_backups" / ("quarantine_v1_" + stamp)
        if backup_root.exists():
            raise FileExistsError(f"Refusing to reuse backup directory: {backup_root}")
        backup_root.mkdir(parents=True, exist_ok=False)
        for path, (original, _) in patchable.items():
            destination = backup_root / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            if destination.read_bytes() != path.read_bytes():
                raise ValueError(f"Backup verification failed: {path}")
        applied = []
        try:
            for path, (_, changed) in patchable.items():
                write_atomic(path, changed)
                applied.append(path)
            for path, (_, changed) in patchable.items():
                if path.read_text(encoding="utf-8") != changed:
                    raise ValueError(f"Patch verification failed: {path}")
        except Exception:
            for path in reversed(applied):
                shutil.copy2(backup_root / path.relative_to(ROOT), path)
            raise
        print(f"PATCHED {len(applied)} entry points. Verified backups: {backup_root.relative_to(ROOT)}")
        print("Partition manifest and review record unchanged. No model calls or candidate execution.")
        return 0
    except (ValueError, OSError, RuntimeError, SyntaxError) as exc:
        print("INSTALL BLOCKED:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
