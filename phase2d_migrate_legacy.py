#!/usr/bin/env python3
"""Non-destructive provenance migration for the previously reviewed HumanEval/1 suite."""
from pathlib import Path
import json
import shutil
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
path=ROOT/"data"/"development"/"humaneval"/"HumanEval_1.json"
if not path.is_file():
    raise SystemExit("No existing HumanEval/1 development suite found; nothing to migrate")
data=json.loads(path.read_text(encoding="utf-8"))
if data.get("task_id")!="HumanEval/1" or not isinstance(data.get("cases"),list) or len(data["cases"])!=15:
    raise SystemExit("Existing suite does not match expected 15-case HumanEval/1 pilot; review manually")
if data.get("provenance")=="independently_reviewed_development":
    print("Already labeled; no changes made")
else:
    backup=path.with_suffix(".legacy_backup.json")
    if backup.exists():
        raise SystemExit("Backup already exists; refusing to overwrite it")
    shutil.copy2(path,backup)
    data["provenance"]="independently_reviewed_development"
    data["provenance_note"]="Existing 15 development cases previously manually reviewed in Phase 2A; not copied from official held-out assertions"
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    print("Preserved backup:",backup)
    print("Updated development provenance:",path)
