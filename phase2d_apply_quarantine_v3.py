#!/usr/bin/env python3
"""Fail-closed, inspect-first upgrade from the EXACT verified v2 shared guard to v3.

--check: read-only. --apply: backup then atomically replace ONLY shared guard,
checker and its one V1 test (to point to V3 fixture). No manifest/candidates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys

from phase2d_record_manual_overlap_batch3 import BATCH3_REL, build as build_review

ROOT=Path(__file__).resolve().parent
STAGING=ROOT/'phase2d_v3_sources'
TARGETS=(
    'phase2d_quarantine_guard.py',
    'phase2d_quarantine_check.py',
    'tests/test_phase2d_quarantine_guard.py',
)
# Verified original installed V2 bytes shipped in phase2d_quarantine_guard_v2.zip.
ALLOWED_V2_SHA256={
    'phase2d_quarantine_guard.py':'c2989b3e0b31773f55984f070a34bbd8a9cdccd6d4628706bbf5e3cd690348bc',
    'phase2d_quarantine_check.py':'afac80fa479f02b0a5bfd123efe13e39bbe3f18225ab5d385e868ea1037b1934',
    'tests/test_phase2d_quarantine_guard.py':'eae8cd7dd22b3512a7b27ab94e28128b7843c314a7f5ed4dfb2ed0cd6aae1022',
}


def digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def check(root:Path):
    root=Path(root).resolve()
    review_path=root/BATCH3_REL
    if not review_path.is_file() or review_path.is_symlink():
        raise ValueError(f'Missing Batch 3 review: {review_path}; create with --write first')
    from phase2d_record_manual_overlap_batch3 import _json
    saved=_json(review_path)
    expected=build_review(root)
    if saved!=expected:
        raise ValueError('STALE/ALTERED REVIEW: Batch 3 does not match current verified evidence')
    # v1 hooks, already installed by V2, continue to call the same guard method.
    from phase2d_install_quarantine import prepare
    pending,statuses=prepare(root)
    if pending:
        raise ValueError('Existing application entry point hooks are missing')
    print('EXISTING HOOKS:',len(statuses),'verified')
    staged=STAGING/'phase2d_quarantine_guard.py'
    spec=importlib.util.spec_from_file_location('_phase2d_v3_staged',staged)
    if not spec or not spec.loader:
        raise ValueError('Unable to import staged V3 policy')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest, exclusions=module.load_verified_policy(root)
    if manifest.get('status')!='draft_requires_review_and_freeze' or len(exclusions)!=21:
        raise ValueError('Unexpected manifest status or number of exclusions')
    for task in sorted(exclusions):
        for intent in ('generate','evaluate'):
            try:
                module.require_task_permission(root,task,intent)
            except module.TaskPolicyError as exc:
                if not str(exc).startswith('QUARANTINED:'):
                    raise ValueError(f'Unexpected denial for {task}: {exc}') from exc
            else:
                raise ValueError(f'Policy incorrectly allowed {task} for {intent}')
    for pilot in sorted(module.PILOT_TASKS):
        for intent in ('generate','evaluate'):
            module.require_task_permission(root,pilot,intent)
    try:
        module.require_task_permission(root,'BigCodeBench/854','evaluate')
    except module.TaskPolicyError as exc:
        if 'still draft' not in str(exc):
            raise ValueError(f'Unexpected BCB/854 reason: {exc}') from exc
    else:
        raise ValueError('BCB/854 unexpectedly authorized')
    print('POLICY VERIFIED: 42 quarantine decisions blocked, 3 existing pilots eligible, BCB/854 blocked')
    edits=[]
    for name in TARGETS:
        src=STAGING/name
        dst=root/name
        if not src.is_file() or src.is_symlink() or not dst.is_file() or dst.is_symlink():
            raise ValueError(f'Missing or unsafe file: {name}')
        new=src.read_bytes()
        old=dst.read_bytes()
        compile(new,str(dst),'exec')
        if old==new:
            print('ALREADY V3:',name)
            continue
        if digest(old)!=ALLOWED_V2_SHA256[name]:
            raise ValueError(f'Installed {name} does not match verified V2 bytes; refusing overwrite')
        print('READY TO UPGRADE:',name)
        edits.append((dst,new))
    return edits


def atomic_replace(dest:Path,data:bytes):
    temp=dest.with_name(dest.name+'.quarantine-v3-tmp')
    if temp.exists():
        raise FileExistsError(f'Stale temp file: {temp}')
    try:
        with temp.open('xb') as dst:
            dst.write(data)
        temp.chmod(dest.stat().st_mode)
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group()
    group.add_argument('--check',action='store_true')
    group.add_argument('--apply',action='store_true')
    args=ap.parse_args(argv)
    try:
        changes=check(ROOT)
        if not args.apply:
            print('READ-ONLY CHECK COMPLETE; no files modified.')
            return 0
        if not changes:
            print('Already installed exact verified V3; no changes needed.')
            return 0
        name='quarantine_v3_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder=ROOT/'results'/'phase2d'/'patch_backups'/name
        folder.mkdir(parents=True,exist_ok=False)
        for dst,_ in changes:
            backup=folder/dst.relative_to(ROOT)
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dst,backup)
            if backup.read_bytes()!=dst.read_bytes():
                raise ValueError('Backup verification failed; nothing was modified')
        completed=[]
        try:
            for dst,new in changes:
                atomic_replace(dst,new)
                completed.append(dst)
            for dst,new in changes:
                if dst.read_bytes()!=new:
                    raise ValueError('Post-install verification failed')
        except Exception:
            for dst in reversed(completed):
                shutil.copy2(folder/dst.relative_to(ROOT),dst)
            raise
        print('UPGRADED SHARED FILES:',len(changes))
        print('BACKUPS:',folder)
        print('No manifest, dataset, prior review or generated candidate modified.')
        return 0
    except (ValueError,OSError,ImportError,TypeError,KeyError,SyntaxError) as exc:
        print('UPGRADE BLOCKED:',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
