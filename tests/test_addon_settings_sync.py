"""Synced settings: the shared key list, the shared merge cases and the add-on's sync runs."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_deck_completion as addon_fixture
from addon_loader import ADDON, FakeApi, load_in_package

settings_sync = load_in_package("aq_settings_sync", "settings_sync")
FIXTURE = json.loads((ADDON.parent / "tests/fixtures/synced_settings.json").read_text("utf-8"))
DEFAULTS = json.loads((ADDON / "config.json").read_text("utf-8"))
NOW_MS = 1793183400000


class SettingsServer(FakeApi):
    """A server that keeps settings as the real one does: the newer change wins, ties keep it."""

    def __init__(self, features=(settings_sync.FEATURE,), stored=None):
        super().__init__(features=features)
        self.stored = dict(stored or {})

    def _request(self, path, body=None, method=None):
        self.sent.append((path, body, method))
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
        api = SettingsServer(features=())
        self.assertIsNone(settings_sync.run(api, {"notify_rank": False}))
        self.assertEqual([], api.sent)

    def test_newer_remote_values_apply_and_newer_local_ones_are_sent(self):
        api = SettingsServer(stored={
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
            [("/api/settings/hill", None, None),
             ("/api/settings/hill", {"settings": {
                 "deck_status": {"value": False, "updated_at": NOW_MS - 5},
                 "streak_warning_hours": {"value": 0, "updated_at": 0},
             }}, "PUT")],
            api.sent,
        )

    def test_the_server_time_replaces_a_time_ahead_of_it(self):
        api = SettingsServer()
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
        server = SettingsServer(stored=stored)
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
        self.assertEqual([], server.sent)

    def test_with_the_switch_off_nothing_is_sent_or_applied(self):
        server = self.use_server(notify_rank={"value": False, "updated_at": NOW_MS})
        self.settings[settings_sync.SWITCH] = False
        self.addon.save_config({"deck_status": False})
        self.addon.sync_settings()
        self.assertEqual([], server.sent)
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

    def test_the_regular_poll_syncs_at_most_once_a_minute(self):
        server = self.use_server(review_heatmap={"value": False, "updated_at": NOW_MS})
        self.addon.copies_ui.poll = Mock()
        self.mw.pm.profile = None
        with patch.object(self.addon.time, "time", return_value=1000.0):
            self.addon.poll()
            self.assertFalse(self.settings["review_heatmap"])
            self.addon.poll()
        self.assertEqual(1, len(server.sent))
        with patch.object(self.addon.time, "time", return_value=1000.0 + self.addon.SETTINGS_POLL_GAP_S):
            self.addon.poll()
        self.assertEqual(2, len(server.sent))

    def test_the_poll_leaves_a_sync_in_flight_alone(self):
        self.use_server()
        self.addon.copies_ui.poll = Mock()
        self.mw.pm.profile = None
        self.addon.state["settings_sync"] = self.addon._SettingsSync.RUNNING
        self.addon.poll()
        self.assertIs(self.addon._SettingsSync.RUNNING, self.addon.state["settings_sync"])

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


class SignedOutCountdowns(unittest.TestCase):
    """Countdowns made while signed out are offered to the account once its settings have synced."""

    setUp_addon = addon_fixture.RefreshTests.setUp
    read_rows = addon_fixture.RefreshTests.read_rows
    write_config = addon_fixture.RefreshTests.write_config
    run_task = addon_fixture.RefreshTests.run_task

    EXAM = {"name": "Spanish exam", "date": "2026-12-01", "deck": None}
    DRIVING = {"name": "Driving test", "date": "2027-01-10", "deck": None}

    def setUp(self):
        self.setUp_addon()
        self.server = SettingsServer(features=(settings_sync.FEATURE, "countdowns"),
                                     stored={"countdowns": {"value": [self.EXAM], "updated_at": NOW_MS - 5}})
        self.server.user = self.api.user
        self.api.capabilities = self.server.capabilities
        self.api._request = self.server._request
        self.addon.redraw = Mock()
        self.addon.tooltip = Mock()
        self.ask = Mock(return_value=True)
        self.addon.countdowns_ui.ask_import = self.ask
        self.settings[settings_sync.DEVICE_KEY] = {"countdowns": {"value": [self.DRIVING], "changed_at": 3}}
        self.addon.state["countdown_offer"] = self.addon._CountdownOffer.AFTER_SYNC

    def device(self):
        return settings_sync.signed_out(self.settings, "countdowns")

    def test_accepting_adds_them_to_the_synced_list(self):
        with patch.object(self.addon.time, "time", return_value=NOW_MS / 1000):
            self.addon.sync_settings()

        self.assertEqual(1, self.ask.call_count)
        self.assertIn(self.api.user, self.ask.call_args.args[1])
        self.assertEqual([self.EXAM, self.DRIVING], self.settings["countdowns"])
        self.assertEqual({"value": [self.EXAM, self.DRIVING], "updated_at": NOW_MS}, self.server.stored["countdowns"])
        self.assertEqual([], self.device())
        self.assertIs(self.addon._CountdownOffer.NONE, self.addon.state["countdown_offer"])

    def test_declining_keeps_them_on_this_device(self):
        self.ask.return_value = False
        self.addon.sync_settings()
        self.addon.sync_settings()

        self.assertEqual(1, self.ask.call_count)
        self.assertEqual([self.EXAM], self.settings["countdowns"])
        self.assertEqual([self.DRIVING], self.device())
        self.assertIs(self.addon._CountdownOffer.NONE, self.addon.state["countdown_offer"])

    def test_a_failed_sync_offers_nothing_yet(self):
        # The account's list is not known, so adding to it could replace the server's list.
        self.api.capabilities = Mock(side_effect=OSError("offline"))
        with patch("builtins.print"):
            self.addon.sync_settings()

        self.ask.assert_not_called()
        self.assertIs(self.addon._CountdownOffer.AFTER_SYNC, self.addon.state["countdown_offer"])

    def test_the_offer_waits_until_countdowns_can_sync(self):
        self.api.capabilities = Mock(return_value={settings_sync.FEATURE})
        self.addon.sync_settings()

        self.ask.assert_not_called()
        self.assertEqual([self.DRIVING], self.device())
        self.assertIs(self.addon._CountdownOffer.AFTER_SYNC, self.addon.state["countdown_offer"])

    def test_nothing_to_add_offers_nothing(self):
        self.settings[settings_sync.DEVICE_KEY] = {"countdowns": {"value": [self.EXAM], "changed_at": 3}}
        self.addon.sync_settings()

        self.ask.assert_not_called()
        self.assertIs(self.addon._CountdownOffer.NONE, self.addon.state["countdown_offer"])

    def test_with_the_switch_off_the_offer_comes_at_once(self):
        self.settings[settings_sync.SWITCH] = False
        self.settings["countdowns"] = [self.EXAM]
        self.addon.sync_settings()

        self.assertEqual([], self.server.sent)
        self.assertEqual([self.EXAM, self.DRIVING], self.settings["countdowns"])

    def test_what_does_not_fit_stays_on_this_device(self):
        full = [{"name": "Quiz %d" % day, "date": "2026-12-%02d" % day, "deck": None} for day in range(1, 21)]
        self.server.stored["countdowns"] = {"value": full[:19], "updated_at": NOW_MS - 5}
        self.settings[settings_sync.DEVICE_KEY] = {"countdowns": {"value": [self.DRIVING, self.EXAM], "changed_at": 3}}
        self.addon.sync_settings()

        self.assertEqual(full[:19] + [self.DRIVING], self.settings["countdowns"])
        self.assertEqual([self.EXAM], self.device())
        self.assertIn("1 countdown did not fit", self.addon.tooltip.call_args.args[0])

    def test_an_old_sync_does_not_offer_for_a_new_account(self):
        original = self.server._request

        def finish_old_request(*args, **kwargs):
            result = original(*args, **kwargs)
            # Real clients are captured objects; switching does not mutate the old one.
            self.api = SimpleNamespace(**dict(vars(self.api), user="other", token="other-token"))
            self.settings.update(user="other", token="other-token", countdowns=[])
            return result

        self.api._request = finish_old_request
        self.addon.sync_settings()

        self.ask.assert_not_called()
        self.assertEqual([], self.settings["countdowns"])
        self.assertEqual([self.DRIVING], self.device())
        self.assertIs(self.addon._CountdownOffer.AFTER_SYNC, self.addon.state["countdown_offer"])

    def test_an_import_answer_does_not_restore_the_previous_account(self):
        def switch_while_asking(*_):
            self.api = SimpleNamespace(**dict(vars(self.api), user="other", token="other-token"))
            self.settings.update(user="other", token="other-token", countdowns=[])
            self.addon.state["countdown_offer"] = self.addon._CountdownOffer.AFTER_SYNC
            return True

        self.ask.side_effect = switch_while_asking
        self.addon.sync_settings()

        self.assertEqual("other", self.settings["user"])
        self.assertEqual("other-token", self.settings["token"])
        self.assertEqual([], self.settings["countdowns"])
        self.assertEqual([self.DRIVING], self.device())

    def test_import_keeps_other_preferences_changed_while_asking(self):
        def change_while_asking(*_):
            self.settings["goal_celebrations"] = False
            return True

        self.ask.side_effect = change_while_asking
        self.addon.sync_settings()

        self.assertFalse(self.settings.get("goal_celebrations", True))
        self.assertEqual([self.EXAM, self.DRIVING], self.settings["countdowns"])

    def test_a_changed_list_keeps_both_lists_until_a_fresh_offer(self):
        changed = [self.EXAM, {"name": "New event", "date": "2027-02-01", "deck": None}]

        def change_while_asking(*_):
            self.settings["countdowns"] = changed
            return True

        self.ask.side_effect = change_while_asking
        self.addon.sync_settings()

        self.assertEqual(changed, self.settings["countdowns"])
        self.assertEqual([self.DRIVING], self.device())
        self.assertIs(self.addon._CountdownOffer.AFTER_SYNC, self.addon.state["countdown_offer"])


class SettingsDialogValues(unittest.TestCase):
    def test_the_switch_reads_as_on_unless_turned_off(self):
        self.assertTrue(settings_sync.enabled({}))
        self.assertTrue(settings_sync.enabled({settings_sync.SWITCH: True}))
        self.assertFalse(settings_sync.enabled({settings_sync.SWITCH: False}))


if __name__ == "__main__":
    unittest.main()
