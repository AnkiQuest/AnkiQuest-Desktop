"""Run the password form checks with real Qt in an isolated process."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class PasswordWindow(unittest.TestCase):
    def test_validation_refusal_retry_and_cancel(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("qt_password.py"))],
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                capture_output=True, text=True, timeout=90)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
