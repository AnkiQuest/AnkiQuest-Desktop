"""Desktop add-on self-update decisions; run with python -m unittest discover -s tests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from addon_loader import load_in_package
import test_deck_completion as fixture

updates = load_in_package("ankiquest_updates", "updates")


def release(tag, prerelease=False, draft=False, package=True):
    assets = [{"name": "ankiquest.ankiaddon", "browser_download_url": "https://example.test/%s.ankiaddon" % tag}] if package else []
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": assets}


class UpdateTests(unittest.TestCase):
    def test_stable_is_the_highest_published_addon_release(self):
        listing = json.dumps([
            release("addon-9"), release("addon-10"), release("addon-11", draft=True),
            release("addon-nightly", prerelease=True), release("quest-17"), release("addon-12", package=False),
        ]).encode()
        best = updates.latest_stable(lambda url, timeout=20: listing)
        self.assertEqual((best["release"], best["nightly"]), (10, 0))
        self.assertTrue(best["url"].endswith("addon-10.ankiaddon"))

    def test_nightly_metadata_points_at_the_rolling_release(self):
        meta = json.dumps({"release": 10, "nightly": 3, "commit": "1a2b3c4d5e"}).encode()
        nightly = updates.latest_nightly(lambda url, timeout=20: meta)
        self.assertEqual((nightly["release"], nightly["nightly"]), (10, 3))
        self.assertEqual(nightly["url"], "https://github.com/AnkiQuest/AnkiQuest-Desktop/releases/download/addon-nightly/ankiquest.ankiaddon")
        self.assertIsNone(updates.latest_nightly(lambda url, timeout=20: b'{"release": 0, "nightly": 1}'))

    def test_newer_orders_release_then_nightly_and_never_updates_a_local_copy(self):
        stable10 = {"release": 10, "nightly": 0}
        nightly10 = {"release": 10, "nightly": 2}
        stable11 = {"release": 11, "nightly": 0}
        self.assertTrue(updates.newer(nightly10, stable10))
        self.assertTrue(updates.newer(stable11, nightly10))
        self.assertFalse(updates.newer(stable10, nightly10))
        self.assertFalse(updates.newer(stable10, stable10))
        self.assertFalse(updates.newer(stable11, None))

    def test_installed_reads_the_packaged_version_only(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(updates.installed(folder))
            (Path(folder) / "version.json").write_text('{"release": 10, "nightly": 2, "commit": "abcdef123"}', "utf-8")
            version = updates.installed(folder)
            self.assertEqual(updates.label(version), "addon-10 nightly 2 (abcdef1)")
            (Path(folder) / "version.json").write_text('{"release": "10"}', "utf-8")
            self.assertIsNone(updates.installed(folder))
        self.assertEqual(updates.label({"release": 10, "nightly": 0, "commit": ""}), "addon-10")

    def test_checks_at_most_daily_and_refuses_non_packages(self):
        self.assertTrue(updates.due(0, 5))
        self.assertFalse(updates.due(1_000, 1_000 + updates.DAY_MS - 1))
        self.assertTrue(updates.due(1_000, 1_000 + updates.DAY_MS))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "a.ankiaddon"
            with self.assertRaises(ValueError):
                updates.download("u", target, lambda url, timeout=20: b"<html>")
            updates.download("u", target, lambda url, timeout=20: b"PK\x03\x04data")
            self.assertEqual(target.read_bytes()[:2], b"PK")


class UpdateSourceTests(unittest.TestCase):
    def test_build_json_names_the_update_source_and_anything_else_is_none(self):
        with tempfile.TemporaryDirectory() as folder:
            build = Path(folder) / "build.json"
            self.assertIs(updates.UpdateSource.NONE, updates.source(folder))
            for text, expected in (
                ('{"updates": "github"}', updates.UpdateSource.GITHUB),
                ('{"updates": "none"}', updates.UpdateSource.NONE),
                ('{"updates": "nightly"}', updates.UpdateSource.NONE),
                ('{"updates": []}', updates.UpdateSource.NONE),
                ("[]", updates.UpdateSource.NONE),
                ("{", updates.UpdateSource.NONE),
            ):
                build.write_text(text, "utf-8")
                self.assertIs(expected, updates.source(folder), text)

    def test_ankiweb_installs_never_update_from_github(self):
        with tempfile.TemporaryDirectory() as folder:
            installed = Path(folder) / "414948448"
            installed.mkdir()
            (installed / "build.json").write_text('{"updates": "github"}', "utf-8")
            self.assertIs(updates.UpdateSource.NONE, updates.source(installed))

    def test_a_source_checkout_does_not_update_itself(self):
        self.assertIs(updates.UpdateSource.NONE, updates.SOURCE)


class UpdateOwnership(unittest.TestCase):
    setUp = fixture.RefreshTests.setUp
    run_task = fixture.RefreshTests.run_task
    read_rows = fixture.RefreshTests.read_rows
    write_config = fixture.RefreshTests.write_config

    def installed(self, folder):
        (Path(folder) / "version.json").write_text(json.dumps({"release": 11, "nightly": 0}), "utf-8")
        self.addon.ADDON_DIR = Path(folder)
        self.addon.updates.available = Mock(return_value={"release": 12, "nightly": 0, "commit": "", "url": "u"})
        self.addon.updates.download = Mock()
        self.addon.offer_update = Mock()

    def test_builds_without_updates_never_check_download_or_install(self):
        with tempfile.TemporaryDirectory() as folder:
            self.installed(folder)
            self.addon.updates.SOURCE = self.addon.updates.UpdateSource.NONE
            self.addon.check_updates(quiet=False)
            self.addon.maybe_check_updates()
            self.addon.updates.available.assert_not_called()
            self.addon.offer_update.assert_not_called()
            self.addon.updates.download.assert_not_called()
            self.addon.tooltip.assert_not_called()
            self.assertNotIn(self.addon.UPDATE_CHECK_KEY, self.mw.pm.profile)

    def test_github_builds_offer_a_newer_release(self):
        with tempfile.TemporaryDirectory() as folder:
            self.installed(folder)
            self.addon.updates.SOURCE = self.addon.updates.UpdateSource.GITHUB
            self.addon.maybe_check_updates()
            self.addon.updates.available.assert_called_once_with("stable")
            self.addon.offer_update.assert_called_once()


if __name__ == "__main__":
    unittest.main()
