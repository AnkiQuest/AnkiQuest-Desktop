"""The leaderboard avatars: cached, ownership-checked, and never following a redirect."""

import unittest
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import Mock, patch

from addon_loader import fake_anki, load_in_package

PNG = b"\x89PNG fake bytes"


def api(user="hill", token="t"):
    return SimpleNamespace(base="https://ankiquest.example", user=user, token=token)


class PicturesTests(unittest.TestCase):
    def setUp(self):
        fake_anki(self, SimpleNamespace())
        self.pictures = load_in_package("ankiquest_pictures_test", "board_pictures")

    def test_an_avatar_url_quotes_the_player_s_name(self):
        downloads = []
        with patch.object(self.pictures.share, "download_image", side_effect=lambda url, **kw: downloads.append(url) or PNG):
            data = self.pictures._avatar(api(token="secret"), "AldanaBRZ")
        self.assertEqual(PNG, data)
        self.assertEqual("https://ankiquest.example/api/avatar/AldanaBRZ", downloads[0])

    def test_the_picture_endpoint_may_not_redirect(self):
        request = SimpleNamespace(full_url="https://ankiquest.example/avatar")
        with self.assertRaises(HTTPError):
            self.pictures._NoRedirect().redirect_request(request, None, 302, "Found", {}, "https://elsewhere.example/avatar")

    def test_a_picture_is_loaded_once_and_shown_to_every_waiting_redraw(self):
        self.tasks = []
        shown = []
        self.stub()

        with patch.object(self.pictures.share, "download_image", return_value=PNG):
            for _ in range(2):
                self.cache._load(["hill"], lambda: shown.append(True))
            self.run_tasks()
        encoded = "data:image/png;base64," + self.pictures.base64.b64encode(PNG).decode("ascii")
        self.assertEqual(encoded, self.cache._get("hill"))
        self.assertEqual([True, True], shown)

    def test_a_failed_picture_waits_for_its_retry_period_and_notifies_the_next_redraw(self):
        self.tasks = []
        notices = []
        self.stub()

        with patch.object(self.pictures.share, "download_image", side_effect=ValueError("offline")), \
                patch.object(self.pictures.time, "monotonic", return_value=0) as now:
            self.cache._load(["gone"], lambda: notices.append("first"))
            self.run_tasks()
        self.assertIsNone(self.cache._get("gone"), "no placeholder is handed out")
        self.assertEqual(["first"], notices, "the waiting redraw is still told the answer")

        now.return_value = self.pictures._RETRY + 1
        notices.clear()
        with patch.object(self.pictures.share, "download_image", return_value=PNG):
            self.cache._load(["gone"], lambda: notices.append("second"))
            self.run_tasks()
        self.assertIsNotNone(self.cache._get("gone"))
        self.assertEqual(["second"], notices)

    def test_work_of_a_closed_or_superseded_window_is_dropped(self):
        self.tasks = []
        self.stub()

        with patch.object(self.pictures.share, "download_image", return_value=PNG):
            self.cache._load(["hill"], lambda: None)
            self.cache._close()
            self.run_tasks()
            self.assertEqual({}, self.cache._cache)

            # Answers asked for under another account are never handed to this window.
            self.cache._phase = self.pictures._Phase.OPEN
            self.cache._load(["hill"], lambda: None)
            self.addon.client = Mock(return_value=api(user="other"))
            self.run_tasks()
            self.assertEqual({}, self.cache._cache)

    def stub(self):
        self.api = api()
        self.addon = SimpleNamespace(
            client=Mock(return_value=self.api),
            time=SimpleNamespace(monotonic=self.pictures.time.monotonic),
            mw=SimpleNamespace(
                pm=SimpleNamespace(profile={}),
                taskman=SimpleNamespace(run_in_background=lambda work, done: self.tasks.append((work, done))),
            ),
        )
        self.cache = self.pictures._Pictures(self.addon)

    def run_tasks(self):
        while self.tasks:
            work, done = self.tasks.pop(0)
            done(SimpleNamespace(result=lambda: work()))


if __name__ == "__main__":
    unittest.main()
