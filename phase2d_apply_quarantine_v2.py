#!/usr/bin/env python3
"""Atomic, inspect-first upgrade of shared task guard from audited v1 to v2.

--check is strictly read-only. --apply backs up and replaces ONLY the two
shared guard/checker Python files plus the v1 regression test (to preserve compatibility).
No manifest, datasets, reviews, candidates, or installed entry-point hooks change.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent
STAGING = ROOT / 'phase2d_v2_sources'
TARGETS = ('phase2d_quarantine_guard.py', 'phase2d_quarantine_check.py', 'tests/test_phase2d_quarantine_guard.py')
# SHA256 of the verified v1 files from the original guard package.
ALLOWED_V1_SHA256 = {
    'phase2d_quarantine_guard.py': '7884337ae95c6315d4a1ba4e3420879703f825035645855a9f974d5656ae460d',
    'phase2d_quarantine_check.py': 'a29aa038ba7033c1a13fc176a4088f7fc7b1a9682b2210d937d774ed91b4f2d4',
    'tests/test_phase2d_quarantine_guard.py': 'f25506e40cb49e66460675acd4604150b223ecc292310d678a93218475932282',
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check(root: Path):
    root = Path(root).resolve()
    # Make a failed or missing second review block upgrades, not bypass them.
    from phase2d_record_manual_overlap_batch2 import BATCH2_REL
    review_path = root / BATCH2_REL
    if not review_path.is_file():
        raise ValueError(f'Second review missing: {review_path}. Create with recorder --write first.')
    import phase2d_install_quarantine as old_installer
    needed, statuses = old_installer.prepare(root)
    if needed:
        raise ValueError('v1 entry-point hooks not fully installed; abort upgrade')
    print('EXISTING HOOKS:', len(statuses), 'previously patched entry points verified')
    stage = STAGING / TARGETS[0]
    spec = importlib.util.spec_from_file_location('_bcb_q_policy_v2_preflight', stage)
    if not spec or not spec.loader:
        raise ValueError('Unable to load staged v2 policy')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest, actual_exclusions = module.load_verified_policy(root)
    if manifest.get('status') != 'draft_requires_review_and_freeze':
        raise ValueError('Split manifest is not draft')
    if len(actual_exclusions) != 13:
        raise ValueError('Unexpected number of quarantined tasks')
    for task_id in sorted(actual_exclusions):
        for intent in ('generate','evaluate'):
            try:
                module.require_task_permission(root,task_id,intent)
            except module.TaskPolicyError as exc:
                if not str(exc).startswith('QUARANTINED:'):
                    raise ValueError(f'Incorrect policy rejection: {task_id}: {exc}') from exc
            else:
                raise ValueError(f'Quarantined task accidentally allowed: {task_id}')
    for task_id in sorted(module.PILOT_TASKS):
        module.require_task_permission(root,task_id,'evaluate')
    try:
        module.require_task_permission(root,'BigCodeBench/854','evaluate')
    except module.TaskPolicyError:
        pass
    else:
        raise ValueError('BCB/854 unexpectedly permitted')
    modified = []
    for name in TARGETS:
        src = STAGING / name
        dst = root / name
        if not src.is_file() or not dst.is_file() or dst.is_symlink():
            raise ValueError(f'Missing staged/installed regular file: {name}')
        updated = src.read_bytes()
        existing = dst.read_bytes()
        compile(updated, str(dst), 'exec')
        if existing == updated:
            print('ALREADY V2:', name)
            continue
        if digest(existing) != ALLOWED_V1_SHA256[name]:
            raise ValueError(f'Installed {name} differs from verified v1; refusing overwrite')
        print('READY TO UPGRADE:',name)
        modified.append((dst, updated))
    print('POLICY VERIFIED: 13 quarantined tasks * 2 intents = 26 blocks; 3 pilot permissions remain')
    return modified


def atomic_replace(path: Path, content: bytes):
    tmp = path.with_name(path.name + '.v2-upgrade-tmp')
    if tmp.exists():
        raise FileExistsError(f'Stale temporary file: {tmp}')
    try:
        with tmp.open('xb') as fh:
            fh.write(content)
        tmp.chmod(path.stat().st_mode)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--check',action='store_true',help='Read-only check (default)')
    group.add_argument('--apply',action='store_true',help='Backup and upgrade shared files')
    args=parser.parse_args(argv)
    try:
        changes=check(ROOT)
        if not args.apply:
            print('READ-ONLY COMPLETE. No files changed.')
            return 0
        if not changes:
            print('NO OP: already upgraded to the exact verified v2 sources.')
            return 0
        timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder=ROOT/'results'/'phase2d'/'patch_backups'/('quarantine_v2_'+timestamp)
        folder.mkdir(parents=True,exist_ok=False)
        for dest,_ in changes:
            back=folder/dest.relative_to(ROOT)
            back.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dest,back)
            if back.read_bytes() != dest.read_bytes():
                raise ValueError('Backup validation failed; nothing changed')
        completed=[]
        try:
            for dest,source in changes:
                atomic_replace(dest,source)
                completed.append(dest)
            for dest,source in changes:
                if dest.read_bytes()!=source:
                    raise ValueError(f'After-write verification failed: {dest}')
        except Exception:
            for dest in reversed(completed):
                shutil.copy2(folder/dest.relative_to(ROOT),dest)
            raise
        print('UPGRADED:',len(completed),'shared files')
        print('BACKUPS:',folder)
        print('No manifest, original review, dataset or candidate changed.')
        return 0
    except (ValueError, OSError, SyntaxError, ImportError, KeyError, TypeError) as exc:
        print('UPGRADE BLOCKED:',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
