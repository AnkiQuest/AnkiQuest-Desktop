"""The Today card asking players who sign in only with a token to set a password; run with python -m unittest discover -s tests."""

import unittest
from types import SimpleNamespace

from addon_loader import load_in_package

board = load_in_package("ankiquest_password_test", "board")
client = load_in_package("ankiquest_password_test", "client")
language = load_in_package("ankiquest_password_test", "language")
prompt = load_in_package("ankiquest_password_test", "password_prompt")

ANA = ["https://quest.example", "ana", "ana-token"]
BO = ["https://quest.example", "bo", "bo-token"]
NOW = 1_800_000_000_000


def methods(sign_in=None):
    answer = {"account": False, "password": False, "providers": [], "linked_unavailable": False}
    if sign_in is not None:
        answer["sign_in"] = sign_in
    return answer


class PasswordPromptTests(unittest.TestCase):
    def test_sign_in_is_read_and_is_none_from_servers_without_it_or_with_a_new_value(self):
        self.assertIs(prompt._SignIn.TOKEN_ONLY, prompt._sign_in(methods("token_only")))
        self.assertIs(prompt._SignIn.PASSWORD, prompt._sign_in(methods("password")))
        self.assertIs(prompt._SignIn.PROVIDER, prompt._sign_in(methods("provider")))
        self.assertIsNone(prompt._sign_in(methods()))
        self.assertIsNone(prompt._sign_in(methods("passkey")))
        self.assertIsNone(prompt._sign_in(None))

    def test_not_now_hides_the_card_for_three_days_for_that_account(self):
        prefs = {}
        self.assertEqual(3 * 24 * 60 * 60 * 1000, prompt.SNOOZE_MS)
        self.assertFalse(prompt._snoozed(prefs, ANA, NOW))
        prompt._snooze(prefs, ANA, NOW)
        self.assertTrue(prompt._snoozed(prefs, ANA, NOW + prompt.SNOOZE_MS - 1))
        self.assertFalse(prompt._snoozed(prefs, ANA, NOW + prompt.SNOOZE_MS))
        self.assertFalse(prompt._snoozed(prefs, BO, NOW))
        self.assertNotIn("ana-token", repr(prefs), "the token is never kept as a key")

    def test_the_form_checks_the_length_and_that_both_passwords_match(self):
        self.assertEqual("Use 10 to 256 characters.", prompt._problem("short", "short"))
        self.assertEqual("Use 10 to 256 characters.", prompt._problem("x" * 257, "x" * 257))
        self.assertEqual("The two passwords are not the same.", prompt._problem("a new long password", "a new long passwort"))
        self.assertIsNone(prompt._problem("a new long password", "a new long password"))

    def test_the_client_reads_sign_in_methods_and_sets_a_password_with_the_token_alone(self):
        sent = []
        api = client.Client("https://quest.example", "ana", "ana-token")
        api._request = lambda path, body=None, method=None, extra=None: sent.append((path, body)) or {}
        api.sign_in_methods()
        api.set_password("a new long password")
        self.assertEqual([
            ("/api/sign-in/ana", None),
            ("/api/sign-in/ana", {"action": "password", "password": "a new long password", "sign_out_others": False}),
        ], sent)


class PasswordCardTests(unittest.TestCase):
    def view(self, **changes):
        view = {"focus": None, "goal": None, "board": None}
        view.update(changes)
        return view

    def test_the_card_offers_a_password_and_not_now_below_the_next_step(self):
        html = board.html({"level": 1}, None, 0, today=self.view(password=True))
        body = "You sign in with a token only. Set a password so you can still sign in on a new device or if the token stops working."
        self.assertIn(body, html)
        self.assertIn("pycmd('%s')" % board.PASSWORD_COMMAND, html)
        self.assertIn("pycmd('%s')" % board.PASSWORD_LATER_COMMAND, html)
        self.assertLess(html.index("Your next step"), html.index(body))
        self.assertLess(html.index(body), html.index(">Set a password</button>"))
        self.assertLess(html.index(">Set a password</button>"), html.index(">Not now</button>"))

    def test_no_card_without_a_token_only_answer(self):
        for view in (self.view(), self.view(password=False)):
            self.assertNotIn(board.PASSWORD_COMMAND, board.html({"level": 1}, None, 0, today=view))

    def test_the_card_is_translated(self):
        html = board.html({"level": 1}, None, 0, lambda text: language.tr(text, "fr"), today=self.view(password=True))
        self.assertIn("Tu te connectes uniquement avec un jeton.", html)
        self.assertIn(">Pas maintenant</button>", html)


if __name__ == "__main__":
    unittest.main()
