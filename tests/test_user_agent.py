"""Every request to the server names the add-on, because ankiquest.org refuses urllib's default agent."""
import unittest
import urllib.request
from unittest.mock import patch

from addon_loader import load_in_package

client = load_in_package("aq_user_agent", "client")
share = load_in_package("aq_user_agent", "share")
PNG = b"\x89PNG\r\n\x1a\npicture"


class Response:
    def __init__(self, body=b"{}"):
        self.body = body

    def read(self, limit=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class UserAgent(unittest.TestCase):
    def sent(self, call):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return Response(PNG)

        with patch.object(urllib.request, "urlopen", side_effect=opener):
            call()
        return requests[0]

    def test_server_requests_name_the_add_on(self):
        request = self.sent(lambda: client.open_url("https://quest.test/api/capabilities"))
        self.assertEqual("AnkiQuest-Desktop", request.get_header("User-agent"))

    def test_a_caller_agent_is_kept(self):
        request = self.sent(lambda: client.open_url("https://api.github.test/", headers={"User-Agent": "ankiquest-addon"}))
        self.assertEqual("ankiquest-addon", request.get_header("User-agent"))

    def test_card_pictures_name_the_add_on(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return Response(PNG)

        share.download_image("https://quest.test/w/t.png", opener=opener)
        self.assertEqual("AnkiQuest-Desktop", requests[0].get_header("User-agent"))


if __name__ == "__main__":
    unittest.main()
