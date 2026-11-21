"""An unlock moment for a companion the add-on cannot draw waits for its art, as on the app
(AnkiQuest-Android#331); run with python -m unittest discover -s tests."""

import time
import unittest
from unittest.mock import patch

import test_desktop_today as fixture


class CompanionMomentWait(unittest.TestCase):
    run_task = fixture.HomeTests.run_task
    write_config = fixture.HomeTests.write_config

    def setUp(self):
        fixture.HomeTests.setUp(self)
        # During a review moments only queue, so the queue is what these cases read.
        self.mw.state = "review"

    def row(self, id, moment=None, read=False):
        """A notification row from the poll: a plain message, or the unlock `moment`."""
        entry = {"id": id, "kind": "message", "sender": "", "title": "Hello", "body": "",
                 "created_at": int(time.time()), "read_at": int(time.time()) if read else None}
        if moment is not None:
            entry.update(kind="celebration", topic="companion", moment=moment, title="Joined", win=7)
        return entry

    def poll(self, *rows):
        self.addon.announce({}, self.addon.state["profile"], list(rows), False)

    def pending(self):
        moments = self.addon.moments
        return [item["key"] for item in moments._pending(self.mw.pm.profile, (self.api.base, self.api.user))]

    def acknowledge(self):
        moments = self.addon.moments
        moments._acknowledge(self.mw.pm.profile, (self.api.base, self.api.user), self.pending())

    def test_an_unknown_companion_from_an_older_server_waits_for_its_art(self):
        self.poll(self.row(2, "companion:quest_chan"))
        self.assertEqual([], self.pending(), "no card shows another companion's art")

        # An update adds the art: the moment shows once, then never again.
        with patch.dict(self.addon.moods.NAMES, quest_chan="Quest-chan"):
            self.assertEqual(["companion:quest_chan"], self.pending())
            self.acknowledge()
            self.poll(self.row(2, "companion:quest_chan"))
            self.assertEqual([], self.pending())

    def test_an_unlock_the_server_held_back_shows_after_the_update(self):
        # Server#16 leaves the unlock out until the header names its companion, while a later
        # message moves the cursor past it.
        self.poll(self.row(2))
        self.assertEqual(2, self.mw.pm.profile[self.addon.INBOX_KEY])

        self.poll(self.row(2), self.row(1, "companion:cow"))
        self.assertEqual(["companion:cow"], self.pending())

        # Shown once: the next poll does not offer it again, read on the server or not yet.
        self.acknowledge()
        self.poll(self.row(2), self.row(1, "companion:cow"))
        self.assertEqual([], self.pending())

    def test_an_unlock_read_on_another_device_is_not_replayed(self):
        self.poll(self.row(2))
        self.poll(self.row(2), self.row(1, "companion:cow", read=True))
        self.assertEqual([], self.pending())


if __name__ == "__main__":
    unittest.main()
