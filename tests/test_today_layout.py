"""Run the Today panel layout check in Qt WebEngine, separately from Anki stand-ins."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class TodayLayout(unittest.TestCase):
    def test_the_study_button_stays_inside_its_card(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("qt_today_layout.py"))],
                                env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
