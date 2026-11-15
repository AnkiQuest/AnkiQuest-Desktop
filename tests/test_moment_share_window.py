"""Run the real share window outside the hook tests' Qt replacements."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


class ShareWindow(unittest.TestCase):
    def test_recipients_undo_and_delayed_replies(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("qt_share.py"))],
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
