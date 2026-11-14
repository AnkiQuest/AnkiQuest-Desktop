"""Synced settings: the shared key list, the shared merge cases and the add-on's sync runs."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_deck_completion as addon_fixture
from addon_loader import ADDON, load_in_package

settings_sync = load_in_package("aq_settings_sync", "settings_sync")
FIXTURE = json.loads((ADDON.parent / "tests/fixtures/synced_settings.json").read_text("utf-8"))
DEFAULTS = json.loads((ADDON / "config.json").read_text("utf-8"))
NOW_MS = 1793183400000


class FakeApi:
    """A server that keeps settings as the real one does: the newer change wins, ties keep it."""

    def __init__(self, features=("settings_sync",), stored=None):
        self.user = "hill"
        self.features = frozenset(features)
        self.stored = dict(stored or {})
        self.calls = []

    def capabilities(self):
        return self.features

    def _request(self, path, body=None, method=None):
        self.calls.append((method or ("POST" if body else "GET"), path, body))
        for key, entry in (body or {}).get("settings", {}).items():
            old = self.stored.get(key)
            if old is None or entry["updated_at"] > old["updated_at"]:
                self.stored[key] = dict(entry, updated_at=min(entry["updated_at"], NOW_MS))
        return {"settings": dict(self.stored)}


class SharedDefinition(unittest.TestCase):
    def test_keys_match_the_desktop_rows_of_the_shared_fixture(self):
        desktop = {row["key"]: (row["desktop"], row["default"]) for row in FIXTURE["keys"] if row["desktop"]}
        self.assertEqual(desktop, {key: (name, default) for key, (name, default, _) in settings_sync.KEYS.items()})

    def test_ranges_and_defaults_agree_with_the_fixture_and_config(self):
        for row in FIXTURE["keys"]:
            if not row["desktop"]:
                continue
            with self.subTest(key=row["key"]):
                bounds = settings_sync.KEYS[row["key"]][2]
                self.assertEqual((row["min"], row["max"]) if row["type"] == "int" else None, bounds)
                self.assertEqual(row["default"], DEFAULTS[row["desktop"]])
        switch = FIXTURE["switch"]
        self.assertEqual(switch["desktop"], settings_sync.SWITCH)
        self.assertEqual(switch["default"], DEFAULTS[settings_sync.SWITCH])

    def test_client_merges_follow_the_shared_cases(self):
        for case in FIXTURE["client_merge"]:
            with self.subTest(case["name"]):
                local = case["local"]
                value, changed_at, push = settings_sync.merge(case["key"], local["value"], local["changed_at"], case["remote"])
                self.assertEqual(case["expected"], {"value": value, "changed_at": changed_at, "push": push})


class LocalChanges(unittest.TestCase):
    def test_changed_synced_values_get_the_save_time(self):
        config = {"notify_rank": True, "streak_hours": 2, settings_sync.CHANGED_KEY: {"deck_status": 5}}
        self.assertEqual(
            {"deck_status": 5, "streak_warning_hours": NOW_MS},
            settings_sync.stamped(config, {"notify_rank": True, "streak_hours": 4, "url": "x"}, NOW_MS),
        )
        self.assertIsNone(settings_sync.stamped(config, {"notify_rank": True, "url": "x"}, NOW_MS))

    def test_only_turning_the_switch_on_asks_for_a_sync(self):
        self.assertTrue(settings_sync.turned_on({settings_sync.SWITCH: False}, {settings_sync.SWITCH: True}))
        self.assertFalse(settings_sync.turned_on({}, {settings_sync.SWITCH: True}))
        self.assertFalse(settings_sync.turned_on({settings_sync.SWITCH: False}, {settings_sync.SWITCH: False}))

    def test_an_unusable_local_value_counts_as_the_default(self):
        self.assertEqual((2, 0), settings_sync.local({"streak_hours": "2"}, "streak_warning_hours"))
        self.assertEqual((True, 0), settings_sync.local({settings_sync.CHANGED_KEY: {"notify_rank": -3}}, "notify_rank"))


class Runs(unittest.TestCase):
    def test_a_server_without_the_feature_is_left_alone(self):
        api = FakeApi(features=())
        self.assertIsNone(settings_sync.run(api, {"notify_rank": False}))
        self.assertEqual([], api.calls)

    def test_newer_remote_values_apply_and_newer_local_ones_are_sent(self):
        api = FakeApi(stored={
            "notify_rank": {"value": False, "updated_at": NOW_MS - 10},
            "deck_status": {"value": True, "updated_at": NOW_MS - 50},
            "mood_icon": {"value": False, "updated_at": NOW_MS - 10},
        })
        config = {
            "notify_rank": True, "deck_status": False, "streak_hours": 0,
            settings_sync.CHANGED_KEY: {"notify_rank": NOW_MS - 20, "deck_status": NOW_MS - 5},
        }
        updates, changed = settings_sync.run(api, config)
        self.assertEqual({"notify_rank": False}, updates)
        self.assertEqual(NOW_MS - 10, changed["notify_rank"])
        self.assertEqual(NOW_MS - 5, changed["deck_status"])
        self.assertEqual(0, changed["streak_warning_hours"])
        self.assertEqual(
            [("GET", "/api/settings/hill", None),
             ("PUT", "/api/settings/hill", {"settings": {
                 "deck_status": {"value": False, "updated_at": NOW_MS - 5},
                 "streak_warning_hours": {"value": 0, "updated_at": 0},
             }})],
            api.calls,
        )

    def test_the_server_time_replaces_a_time_ahead_of_it(self):
        api = FakeApi()
        config = {"notify_rank": False, settings_sync.CHANGED_KEY: {"notify_rank": NOW_MS + 60_000}}
        _, changed = settings_sync.run(api, config)
        self.assertEqual(NOW_MS, changed["notify_rank"])

    def test_a_change_made_during_a_run_is_kept(self):
        snapshot = {"notify_rank": True, settings_sync.CHANGED_KEY: {"notify_rank": 1}}
        current = {"notify_rank": False, "deck_status": True, settings_sync.CHANGED_KEY: {"notify_rank": 2}}
        updates = {"notify_rank": True, "deck_status": False}
        changed = dict.fromkeys(settings_sync.KEYS, 9)
        settled, applied = settings_sync.settle(snapshot, current, updates, changed)
        self.assertTrue(applied)
        self.assertFalse(settled["notify_rank"])
        self.assertFalse(settled["deck_status"])
        self.assertEqual(2, settled[settings_sync.CHANGED_KEY]["notify_rank"])
        self.assertEqual(9, settled[settings_sync.CHANGED_KEY]["deck_status"])


class AddonSync(unittest.TestCase):
    setUp = addon_fixture.RefreshTests.setUp
    read_rows = addon_fixture.RefreshTests.read_rows
    write_config = addon_fixture.RefreshTests.write_config
    run_task = addon_fixture.RefreshTests.run_task

    def use_server(self, **stored):
        server = FakeApi(stored=stored)
        server.user = self.api.user
        self.api.capabilities = server.capabilities
        self.api._request = server._request
        self.addon.redraw = Mock()
        return server

    def test_saving_a_synced_setting_sends_it_with_the_save_time(self):
        server = self.use_server()
        with patch.object(self.addon.time, "time", return_value=NOW_MS / 1000):
            self.addon.save_config({"deck_status": False})
        self.assertEqual({"value": False, "updated_at": NOW_MS}, server.stored["deck_status"])
        self.assertEqual(NOW_MS, self.settings[settings_sync.CHANGED_KEY]["deck_status"])

    def test_other_saves_do_not_sync(self):
        server = self.use_server()
        self.addon.save_config({"update_channel": "nightly"})
        self.assertEqual([], server.calls)

    def test_with_the_switch_off_nothing_is_sent_or_applied(self):
        server = self.use_server(notify_rank={"value": False, "updated_at": NOW_MS})
        self.settings[settings_sync.SWITCH] = False
        self.addon.save_config({"deck_status": False})
        self.addon.sync_settings()
        self.assertEqual([], server.calls)
        self.assertNotIn("notify_rank", self.settings)
        self.assertIn("deck_status", self.settings[settings_sync.CHANGED_KEY])

    def test_turning_the_switch_on_merges_both_ways(self):
        server = self.use_server(notify_rank={"value": False, "updated_at": NOW_MS})
        self.settings.update({settings_sync.SWITCH: False, "deck_status": False,
                              settings_sync.CHANGED_KEY: {"deck_status": NOW_MS - 1}})
        self.addon.save_config({settings_sync.SWITCH: True})
        self.assertFalse(self.settings["notify_rank"])
        self.assertEqual({"value": False, "updated_at": NOW_MS - 1}, server.stored["deck_status"])
        self.addon.redraw.assert_called_once_with()

    def test_opening_the_profile_applies_remote_settings(self):
        self.use_server(review_heatmap={"value": False, "updated_at": NOW_MS})
        self.addon.QTimer = SimpleNamespace(singleShot=Mock())
        for name in ("refresh_shared_decks", "_request_upload", "poll", "maybe_check_updates"):
            setattr(self.addon, name, Mock())
        self.addon.on_profile_open()
        self.assertFalse(self.settings["review_heatmap"])
        self.assertEqual(NOW_MS, self.settings[settings_sync.CHANGED_KEY]["review_heatmap"])
        self.addon.redraw.assert_called_once_with()

    def test_a_reply_for_another_account_is_dropped(self):
        server = self.use_server(review_heatmap={"value": False, "updated_at": NOW_MS})
        original = server._request

        def switch_account(*args, **kwargs):
            answer = original(*args, **kwargs)
            self.api.token = "other"
            return answer

        self.api._request = switch_account
        self.addon.sync_settings()
        self.assertNotIn("review_heatmap", self.settings)

    def test_a_failed_sync_leaves_settings_alone(self):
        self.api.capabilities = Mock(side_effect=OSError("offline"))
        self.addon.redraw = Mock()
        with patch("builtins.print"):
            self.addon.sync_settings()
        self.assertNotIn(settings_sync.CHANGED_KEY, self.settings)
        self.assertIs(self.addon._SettingsSync.IDLE, self.addon.state["settings_sync"])


class SettingsDialogValues(unittest.TestCase):
    def test_the_switch_reads_as_on_unless_turned_off(self):
        self.assertTrue(settings_sync.enabled({}))
        self.assertTrue(settings_sync.enabled({settings_sync.SWITCH: True}))
        self.assertFalse(settings_sync.enabled({settings_sync.SWITCH: False}))


if __name__ == "__main__":
    unittest.main()
