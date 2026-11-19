"""Runs each real-Qt check (qt_*.py) in its own process.

The other tests replace aqt and anki in sys.modules with stand-ins, so the checks that need the
real modules and a QApplication cannot share their process."""

import os
from pathlib import Path
import subprocess
import sys
import unittest

TESTS = Path(__file__).resolve().parent

# The shared setup the checks import; it holds no tests.
SUPPORT = "qt_support.py"

# Seconds one check may take; it only stops a hung window.
TIMEOUT = 180

# The real-Anki smoke compiles the add-on packager (tools/package-addon) first.
SLOW = {"qt_addon_smoke.py": 1800 + TIMEOUT}


def _run(script):
    result = subprocess.run(
        [sys.executable, str(TESTS / script)],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=SLOW.get(script, TIMEOUT),
    )
    return result.returncode, result.stdout + result.stderr


def _case(script):
    def test(self):
        code, output = _run(script)
        self.assertEqual(0, code, script + "\n" + output)

    return test


class QtWindows(unittest.TestCase):
    """One test per qt_*.py, named after it: test_activity runs qt_activity.py."""


for _script in sorted(path.name for path in TESTS.glob("qt_*.py") if path.name != SUPPORT):
    setattr(QtWindows, "test_" + _script[len("qt_"):-len(".py")], _case(_script))


if __name__ == "__main__":
    unittest.main()
