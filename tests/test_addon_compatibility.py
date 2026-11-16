"""The full Anki smoke runs separately from tests that replace aqt with stand-ins."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class Compatibility(unittest.TestCase):
    def test_the_addon_loads_into_real_anki(self):
        # The smoke installs archives from the Rust packager; compile it outside the smoke's time limit.
        subprocess.run(["cargo", "build", "--quiet", "-p", "ankiquest-xtask"], cwd=ROOT, check=True, timeout=1800)
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("qt_addon_smoke.py"))],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
