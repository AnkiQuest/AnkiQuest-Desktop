"""Recipient parity and receipt-scoped Undo through the desktop API boundary."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from addon_loader import load_in_package

model = load_in_package("moment_share_test", "moment_share")
CASES = json.loads((Path(__file__).parent / "fixtures/share_targets.json").read_text("utf-8"))


class Choices(unittest.TestCase):
    def test_place_reference_and_send(self):
        for rank in (1, 2, 3):
            self.assertEqual({"place": rank}, model._moment({"place": rank}))
        for rank in (True, 0, 4, "2", None):
            self.assertIsNone(model._moment({"place": rank}))
        self.assertEqual({"win": 17}, model._moment({"win": 17, "place": 2}))
        api = SimpleNamespace(user="hill", _request=Mock(return_value={
            "recipients": 1, "win": 17, "undo_until": 1900000000000}))
        chosen = model._Picked((model._Target(model._Kind.FRIEND, "cerro", "Cerro"),))
        sent = model._send(api, {"place": 2}, chosen, " A good study week ")
        api._request.assert_called_once_with("/api/share/hill", {
            "moment": {"place": 2}, "to": {"friends": ["cerro"], "groups": []},
            "note": "A good study week"})
        self.assertEqual(model._Sent(1, 17, 1900000000000), sent)

    def test_place_needs_capability(self):
        features = {"share_moments"}
        api = SimpleNamespace(user="hill", capabilities=lambda: features,
                              _request=Mock(return_value={"friends": [], "groups": []}))
        self.assertIsNone(model._load(api, {"place": 2}, []))
        api._request.assert_not_called()
        features.add("share_place")
        self.assertEqual((), model._load(api, {"place": 2}, []))
        api._request.assert_called_once()
        features.remove("share_moments")
        self.assertIsNone(model._load(api, {"place": 2}, []))

    def test_shared_order_and_group_membership(self):
        for case in CASES["order"]:
            with self.subTest(case=case["name"]):
                targets = model._targets(case["social"], case["me"], case["recent"])
                self.assertEqual(case["keys"], [row._key for row in targets])

    def test_shared_exclusive_circle_and_multiple_targets(self):
        first = CASES["order"][0]
        targets = {row._key: row for row in model._targets(first["social"], first["me"], [])}
        targets["circle"] = model._Choice.CIRCLE
        for case in CASES["selection"]:
            choice = model._Choice.NOBODY
            for key in case["taps"]:
                choice = model._toggle(choice, targets[key])
            self.assertEqual(case["to"], model._audience(choice))

    def test_shared_note_limits_count_unicode_characters(self):
        for case in CASES["notes"]:
            text = case.get("text", case.get("unit", "") * case.get("repeat", 0))
            expected = case.get("expected", case.get("unit", "") * case.get("expected_repeat", 0))
            self.assertEqual(expected, model._note(text))

    def test_every_undo_uses_a_valid_send_receipt(self):
        sent = model._Sent(1, 17, 1900000000000)
        api = SimpleNamespace(user="hill", _request=Mock(return_value={"retracted": 1}))
        self.assertEqual(1, model._retract(api, sent))
        api._request.assert_called_once_with("/api/share/hill/17?until=1900000000000", method="DELETE")
        api._request.reset_mock()
        with self.assertRaises(ValueError):
            model._retract(api, model._Sent(1, 17, None))
        api._request.assert_not_called()

    def test_recents_stay_with_the_account_and_exclude_circle(self):
        profile = {}
        api = SimpleNamespace(base="https://quest.test", user="hill")
        other = SimpleNamespace(base=api.base, user="ana")
        choice = model._Picked((model._Target(model._Kind.FRIEND, "cerro", "Cerro"),))
        model._remember(profile, api, choice)
        model._remember(profile, api, model._Choice.CIRCLE)
        self.assertEqual(["user:cerro"], model._recent(profile, api))
        self.assertEqual([], model._recent(profile, other))


if __name__ == "__main__":
    unittest.main()
