"""The GitHub updater must preserve a working add-on when an archive needs newer Anki."""
import ast
import importlib.util
import sys
from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import anki.lang
anki.lang.set_lang("en")

from aqt.addons import AddonManager, InstallOk, _current_version
from aqt.profiles import ProfileManager
from aqt.forms.main import Ui_MainWindow
from aqt.main import AnkiQt
from aqt.qt import QApplication, QMainWindow

ROOT = Path(__file__).resolve().parents[1]
app = QApplication.instance() or QApplication([])

# The add-on's own update rules, imported as the add-on's package, whose neighbours
# (links.py) it imports.
spec = importlib.util.spec_from_file_location(
    "ankiquest_updates_compat",
    ROOT / "addon" / "updates.py",
    submodule_search_locations=[str(ROOT / "addon")],
)
updates = importlib.util.module_from_spec(spec)
sys.modules["ankiquest_updates_compat"] = updates
spec.loader.exec_module(updates)


def archive(minimum, source):
    data = io.BytesIO()
    with ZipFile(data, "w") as package:
        package.writestr("manifest.json", json.dumps({
            "package": "ankiquest_upgrade_test",
            "name": "AnkiQuest upgrade test",
            "min_point_version": minimum,
        }))
        package.writestr("__init__.py", source)
    data.seek(0)
    return data


class UpdateCompatibility(unittest.TestCase):
    def test_incompatible_update_preserves_installed_code(self):
        with ExitStack() as scope:
            folder = scope.enter_context(tempfile.TemporaryDirectory(prefix="ankiquest-upgrade-"))
            profiles = ProfileManager(Path(folder))
            profiles.setupMeta()
            scope.callback(profiles.db.close)
            profiles.load(profiles.profiles()[0])
            window = AnkiQt.__new__(AnkiQt)
            QMainWindow.__init__(window)
            window.pm = profiles
            window.form = Ui_MainWindow()
            window.form.setupUi(window)
            scope.callback(window.deleteLater)
            manager = AddonManager(window)
            original = "# working installation\n"
            installed = manager.install(archive(1, original))
            self.assertIsInstance(installed, InstallOk)
            self.assertTrue(installed.compatible)
            module = Path(manager.addonsFolder("ankiquest_upgrade_test")) / "__init__.py"

            # Exercise the shipped updater function with Anki's real installer.
            tree = ast.parse((ROOT / "addon/__init__.py").read_text("utf-8"))
            function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "install_update")
            profile = {}
            namespace = {
                "mw": SimpleNamespace(addonManager=manager, pm=SimpleNamespace(profile=profile)),
                "tr": lambda text: text,
                "tooltip": Mock(),
                "updates": updates,
            }
            exec(compile(ast.Module(body=[function], type_ignores=[]), "addon/__init__.py", "exec"), namespace)
            show_info = scope.enter_context(patch("aqt.utils.showInfo"))
            candidate = {"release": 99, "nightly": 0, "commit": "deadbeef"}
            incoming = Path(folder) / "update.ankiaddon"
            incoming.write_bytes(archive(max(241100, _current_version + 1), "# needs newer Anki\n").getvalue())
            namespace["install_update"](incoming, candidate, _current_version)

            self.assertEqual(original, module.read_text("utf-8"))
            self.assertTrue(manager.addon_meta("ankiquest_upgrade_test").compatible())
            self.assertTrue(
                updates.refused(profile, candidate, _current_version), "the refused build is remembered"
            )
            show_info.assert_not_called()

            # Refusing one archive must not prevent a compatible update.
            compatible = "# compatible update\n"
            incoming.write_bytes(archive(1, compatible).getvalue())
            namespace["install_update"](incoming, candidate, _current_version)
            self.assertEqual(compatible, module.read_text("utf-8"))
            self.assertTrue(manager.addon_meta("ankiquest_upgrade_test").compatible())
            show_info.assert_called_once()

            # Corrupt downloads keep Anki's existing error path and the installed files.
            incoming.write_bytes(b"PKnot-a-valid-zip")
            namespace["install_update"](incoming, candidate, _current_version)
            self.assertEqual(compatible, module.read_text("utf-8"))
            self.assertIn("could not be installed", namespace["tooltip"].call_args.args[0])
            show_info.assert_called_once()


if __name__ == "__main__":
    unittest.main()

