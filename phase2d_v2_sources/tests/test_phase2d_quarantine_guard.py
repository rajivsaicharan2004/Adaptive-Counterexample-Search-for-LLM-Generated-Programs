"""Offline synthetic regression tests; never run generated candidates or models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phase2d_quarantine_guard import (
    KNOWN_PAIRS, KNOWN_QUARANTINE, PILOT_TASKS, REPORT_REL, REVIEW_REL,
    TaskPolicyError, require_task_permission,
)
from phase2d_global_overlap_audit import DATASETS, normalized_prompt, sha256_file


def dump_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# v2 fixture preserves the six-pair audit and adds the eight-pair batch2 evidence.
from phase2d_quarantine_v2_fixture import make_fixture


class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.manifest, cls.review, cls.report = make_fixture(cls.root)
        cls.original_manifest = cls.manifest.read_bytes()
        cls.original_review = cls.review.read_bytes()
        cls.original_report = cls.report.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def tearDown(self):
        self.manifest.write_bytes(self.original_manifest)
        self.review.write_bytes(self.original_review)
        self.report.write_bytes(self.original_report)

    def test_all_six_quarantined_even_as_development(self):
        for task in KNOWN_QUARANTINE:
            for intent in ("generate", "evaluate"):
                with self.subTest(task=task, intent=intent):
                    with self.assertRaisesRegex(TaskPolicyError, "QUARANTINED"):
                        require_task_permission(self.root, task, intent)

    def test_three_existing_draft_pilots_remain_eligible(self):
        for task in PILOT_TASKS:
            self.assertIn("Allowed", require_task_permission(self.root, task, "evaluate"))
            self.assertIn("Allowed", require_task_permission(self.root, task, "generate"))

    def test_unapproved_draft_task_blocked(self):
        for intent in ("generate", "evaluate"):
            with self.assertRaisesRegex(TaskPolicyError, "still draft"):
                require_task_permission(self.root, "BigCodeBench/854", intent)

    def test_heldout_rejected(self):
        with self.assertRaisesRegex(TaskPolicyError, "not assigned to development"):
            require_task_permission(self.root, "HumanEval/10", "evaluate")

    def test_unknown_task_rejected(self):
        with self.assertRaisesRegex(TaskPolicyError, "not assigned"):
            require_task_permission(self.root, "MBPP/MISSING", "generate")

    def test_report_tampering_fails_closed(self):
        payload = json.loads(self.report.read_text())
        payload["test_tamper"] = True
        dump_json(self.report, payload)
        with self.assertRaisesRegex(TaskPolicyError, "lexical report hash changed"):
            require_task_permission(self.root, "HumanEval/0", "evaluate")

    def test_review_quarantine_removal_fails_closed(self):
        payload = json.loads(self.review.read_text())
        payload["quarantine"]["development_task_ids"].pop()
        dump_json(self.review, payload)
        with self.assertRaisesRegex(TaskPolicyError, "Quarantine task IDs"):
            require_task_permission(self.root, "HumanEval/0", "evaluate")

    def test_review_pair_removal_fails_closed(self):
        payload = json.loads(self.review.read_text())
        payload["pairs"].pop()
        dump_json(self.review, payload)
        with self.assertRaisesRegex(TaskPolicyError, "Missing or incomplete"):
            require_task_permission(self.root, "HumanEval/0", "evaluate")

    def test_manifest_status_change_invalidates_review(self):
        payload = json.loads(self.manifest.read_text())
        payload["status"] = "frozen"
        dump_json(self.manifest, payload)
        with self.assertRaisesRegex(TaskPolicyError, "STALE REVIEW"):
            require_task_permission(self.root, "HumanEval/0", "evaluate")

    def test_missing_review_fails_closed(self):
        self.review.unlink()
        try:
            with self.assertRaisesRegex(TaskPolicyError, "Missing or unreadable"):
                require_task_permission(self.root, "HumanEval/0", "evaluate")
        finally:
            self.review.write_bytes(self.original_review)

    def test_bad_intent_fails(self):
        with self.assertRaisesRegex(TaskPolicyError, "Unknown task intent"):
            require_task_permission(self.root, "HumanEval/0", "train")


if __name__ == "__main__":
    unittest.main()
