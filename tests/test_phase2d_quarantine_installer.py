"""Synthetic installer preflight tests. Does not patch the user's project."""
from pathlib import Path
import tempfile
import unittest

from phase2d_install_quarantine import EDITS, OPTIONAL_EDITS, MARKER, prepare


class InstallerTests(unittest.TestCase):
    def test_preflight_and_idempotent_marker_detection(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename, (anchor, insertion) in {**EDITS, **OPTIONAL_EDITS}.items():
                target = root / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                code = "def main():\n" + anchor
                if anchor.strip().startswith(("if ", "if not ")):
                    code += "        pass\n"
                target.write_text(code, encoding="utf-8")
            patches, statuses = prepare(root)
            self.assertEqual(len(patches), len(EDITS)+len(OPTIONAL_EDITS))
            self.assertTrue(all("READY TO PATCH" in status for status in statuses))
            # Writing the expected patched content is safe within this temp dir.
            for target, (_, patched) in patches.items():
                target.write_text(patched, encoding="utf-8")
            patches, statuses = prepare(root)
            self.assertFalse(patches)
            self.assertTrue(all("ALREADY PATCHED" in status for status in statuses))

    def test_missing_anchor_fails_closed(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename, (anchor, _) in EDITS.items():
                target = root / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("def main():\n" + anchor + "    pass\n", encoding="utf-8")
            (root / "phase1_generator.py").write_text("def main():\n    pass\n")
            with self.assertRaisesRegex(ValueError, "insertion anchor"):
                prepare(root)


if __name__ == "__main__":
    unittest.main()
