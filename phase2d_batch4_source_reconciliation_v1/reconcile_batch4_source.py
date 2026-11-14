#!/usr/bin/env python3
"""Fail-closed Batch 4 CSV source reconciliation. Python stdlib only.

Read-only by default. Restore only if *all* 81 CSV rows and all fields match
exactly the reviewed uploaded snapshot; preserve the prior file in a backup.
No model calls, candidate execution, split edits or private tests.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REVIEWED_SHA256 = '48a98d45721a40f9da34b31572dbc82cd3e22b2e21d59ef9cba807669d3c5462'
REVIEW_RECORD_SHA256 = '84b0e2e541a075c151e6f742bd21267b34410f6000eb8032f9019693e570d84f'
RELATIVE_SOURCE = Path('results/phase2d/global_overlap_stratified_v1/random_stratified_review.csv')
RELATIVE_REVIEW = Path('results/phase2d/global_overlap_stratified_v1/manual_review_batch4_provisional.json')
RELATIVE_VERIFIER = Path('phase2d_stratified_review_batch4/phase2d_verify_sample_review_batch4.py')
BACKUP_BASE = Path('results/phase2d/global_overlap_stratified_v1/source_reconciliation_backups')


class ReconcileError(Exception):
    pass


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def read_table(path: Path):
    with path.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f, strict=True)
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ReconcileError(f'Missing or repeated CSV header: {path}')
        fields = reader.fieldnames
        rows = list(reader)
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ReconcileError(f'Unexpected or missing CSV fields: {path}')
    return fields, rows


def table_differences(source, snapshot, *, max_diffs=12):
    fields_current, current = read_table(source)
    fields_snapshot, expected = read_table(snapshot)
    differences = []
    if fields_current != fields_snapshot:
        differences.append(('header', '', str(fields_current), str(fields_snapshot)))
    if len(current) != len(expected):
        differences.append(('row count', '', str(len(current)), str(len(expected))))
    for i, (actual, required) in enumerate(zip(current, expected), start=1):
        if actual != required:
            for name in fields_snapshot:
                if actual.get(name) != required.get(name):
                    differences.append((str(i), name, actual.get(name), required.get(name)))
                    if len(differences) >= max_diffs:
                        return differences
    return differences


def show_diff(value):
    if value is None:
        return '[MISSING]'
    return repr(value[:120] + ('…' if len(value) > 120 else ''))


def verified_inputs(root: Path, snapshot: Path):
    source = root / RELATIVE_SOURCE
    review = root / RELATIVE_REVIEW
    verifier = root / RELATIVE_VERIFIER
    for p in (source, snapshot, review, verifier):
        if not p.is_file() or p.is_symlink():
            raise ReconcileError(f'Expected an existing regular non-symlink file: {p}')
    if digest(snapshot) != REVIEWED_SHA256:
        raise ReconcileError('Uploaded snapshot hash mismatch: do not use this package')
    if digest(review) != REVIEW_RECORD_SHA256:
        raise ReconcileError('Review record hash mismatch: preserve files and request reconciliation')
    record = json.loads(review.read_text(encoding='utf-8'))
    if record.get('source_file_sha256') != REVIEWED_SHA256:
        raise ReconcileError('Review source hash does not match uploaded evidence')
    module_spec = importlib.util.spec_from_file_location('batch4_source_verifier', verifier)
    if not module_spec or not module_spec.loader:
        raise ReconcileError('Cannot load original review verifier')
    mod = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(mod)
    result = mod.verify(snapshot, review, strict_file_hash=True)
    if result['pairs'] != 81 or result['strata'] != 34:
        raise ReconcileError('Original source verifier reports wrong pair or stratum count')
    return source, review


def analyze(root: Path, snapshot: Path):
    source, review = verified_inputs(root, snapshot)
    current_sha = digest(source)
    differences = table_differences(source, snapshot)
    print('REVIEWED UPLOAD SHA256:', REVIEWED_SHA256)
    print('LOCAL CURRENT SHA256: ', current_sha)
    print('REVIEW RECORD SHA256: ', digest(review))
    print('MATCHES REVIEWED BYTES:', current_sha == REVIEWED_SHA256)
    if differences:
        print('CSV CONTENT DIFFERS -- RESTORE FORBIDDEN')
        for row, col, actual, expected in differences:
            print('  Row', row, 'field', col)
            print('    current:', show_diff(actual))
            print('    reviewed:', show_diff(expected))
        return source, current_sha, False
    print('CSV CONTENT MATCHES: 81 records, header and every parsed field in original order')
    if current_sha != REVIEWED_SHA256:
        print('DIAGNOSIS: byte-only CSV representation difference (e.g., quoting or line endings)')
    else:
        print('DIAGNOSIS: original reviewed byte snapshot already present')
    return source, current_sha, True


def restore(root: Path, snapshot: Path, source: Path, observed_sha: str):
    # Recheck before any writes, including exact field equality.
    if digest(source) != observed_sha or table_differences(source, snapshot):
        raise ReconcileError('Source changed during reconciliation; no files changed')
    if observed_sha == REVIEWED_SHA256:
        print('NO RESTORATION REQUIRED; source already has reviewed bytes')
        return

    base = root / BACKUP_BASE
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup_dir = base / f'backup_{stamp}_{observed_sha[:12]}'
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup = backup_dir / 'original_local_csv_before_restore.csv'
    shutil.copy2(source, backup)
    if digest(backup) != observed_sha:
        raise ReconcileError('Backup failed integrity check; source unchanged')
    metadata = {
        'operation': 'CSV_BYTES_RESTORED_AFTER_EXACT_PARSED_CONTENT_MATCH',
        'original_project_file': str(RELATIVE_SOURCE),
        'original_sha256': observed_sha,
        'reviewed_sha256': REVIEWED_SHA256,
        'review_record_sha256': REVIEW_RECORD_SHA256,
        'backup_file': str(backup.relative_to(root)),
        'restored_at_utc': datetime.now(timezone.utc).isoformat(),
        'public_task_data_modified': False,
        'manifest_modified': False,
    }
    (backup_dir / 'reconciliation_manifest.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=source.parent, prefix='.batch4-reviewed-', suffix='.tmp', delete=False) as temp:
            tmp_name = temp.name
            with snapshot.open('rb') as original:
                shutil.copyfileobj(original, temp)
            temp.flush()
            os.fsync(temp.fileno())
        os.chmod(tmp_name, stat.S_IMODE(source.stat().st_mode))
        if digest(source) != observed_sha or table_differences(source, snapshot):
            raise ReconcileError('Source changed after backup, before replacement; original unchanged')
        os.replace(tmp_name, source)
        tmp_name = None
        if digest(source) != REVIEWED_SHA256:
            raise ReconcileError('Post-restore source digest mismatch: restore from backup manually')
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()
    print('RESTORE SUCCESS: reviewed source bytes restored, parsed CSV data unchanged')
    print('BACKUP DIRECTORY:', backup_dir)
    print('CURRENT SHA256:', digest(source))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root', type=Path, default=Path.cwd(), help='Project root (default: current directory)')
    cli.add_argument('--restore-reviewed-bytes', action='store_true', help='Explicitly back up and replace only an exactly content-matching CSV')
    args = cli.parse_args()
    root = args.root.resolve()
    snapshot = Path(__file__).resolve().with_name('reviewed_uploaded_snapshot.csv')
    try:
        source, current_sha, matches = analyze(root, snapshot)
        if not matches:
            print('STOP: Actual CSV field-level changes need review; no restoration allowed')
            return 3
        if args.restore_reviewed_bytes:
            restore(root, snapshot, source, current_sha)
        else:
            print('READ-ONLY CHECK PASSED; use --restore-reviewed-bytes only to restore exact reviewed bytes')
        return 0
    except (ReconcileError, ValueError, KeyError, UnicodeError, csv.Error, OSError) as exc:
        print('BATCH4 SOURCE RECONCILIATION FAILED CLOSED:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
