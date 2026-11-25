"""The deck list's heatmap colours and describes each day as the Android app does."""

import json
import re
import unittest
from datetime import date, timedelta

from addon_loader import load_in_package

ui = load_in_package("aq_heatmap_pkg", "heatmap_ui")
heatmap = load_in_package("aq_heatmap_pkg", "heatmap")

TODAY = date(2024, 3, 1)


def day(offset):
    return TODAY + timedelta(days=offset)


def english(text):
    return text


def page_data(block):
    """The JSON the script draws from."""
    found = re.search(r"var D=(\{.*?\}),L=D\.labels", block, re.S)
    return json.loads(found.group(1).replace("<\\/", "</"))


class Colours(unittest.TestCase):
    def test_reviews_and_forecast_by_level(self):
        data = heatmap.summarize(TODAY, {day(0): 10, day(-1): 30}, {day(1): 4, day(2): 50})
        # The page adds each count's level from the rules module (qt_heatmap_rules.py).
        self.assertEqual(("l", 10, 0), ui.colour(data, day(0)))
        self.assertEqual(("l", 30, 0), ui.colour(data, day(-1)))
        self.assertEqual(("l", 0, 0), ui.colour(data, day(-2)))
        self.assertEqual(("f", 4, 0), ui.colour(data, day(1)))
        self.assertEqual(("f", 50, 0), ui.colour(data, day(2)))

    def test_the_verdict_colours_the_days_ankiquest_judged(self):
        verdicts = {
            day(-1): heatmap.Verdict(heatmap.SHORT, 3, 10),
            day(-2): heatmap.Verdict(heatmap.FROZEN, 1, 10),
            day(-3): heatmap.Verdict(heatmap.NONE),
            day(-4): heatmap.Verdict(heatmap.MET, 12, 10),
            day(-5): heatmap.Verdict(heatmap.SKIPPED),
        }
        reviews = {day(-1): 50, day(-2): 50, day(-3): 50, day(-4): 50}
        data = heatmap.summarize(TODAY, reviews, {}, {day(-2)}, verdicts)
        self.assertEqual(("s", None, 0), ui.colour(data, day(-1)))
        self.assertEqual(("z", None, 1), ui.colour(data, day(-2)))
        self.assertEqual(("l0", None, 0), ui.colour(data, day(-3)))
        self.assertEqual(("l", 50, 0), ui.colour(data, day(-4)))
        self.assertEqual(("z", None, 1), ui.colour(data, day(-5)))


class Texts(unittest.TestCase):
    def test_each_kind_of_day(self):
        data = heatmap.summarize(
            TODAY, {day(0): 1, day(-1): 4, day(-2): 2}, {day(1): 3}, {day(-2)},
            {day(0): heatmap.Verdict(heatmap.SHORT, 4, 10), day(-1): heatmap.Verdict(heatmap.SHORT, 12, 10),
             day(-2): heatmap.Verdict(heatmap.FROZEN), day(-3): heatmap.Verdict(heatmap.NONE),
             day(-4): heatmap.Verdict(heatmap.SKIPPED), day(-5): heatmap.Verdict(heatmap.MET, 10, 10)},
        )
        self.assertEqual("1 review · 4 of 10 minutes for the streak so far", ui.describe(data, day(0), english))
        self.assertEqual("4 reviews · 10 of 10 minutes, short of the streak minimum", ui.describe(data, day(-1), english))
        self.assertEqual("2 reviews · Frozen — streak kept", ui.describe(data, day(-2), english))
        self.assertEqual("0 reviews · No study counted", ui.describe(data, day(-3), english))
        self.assertEqual("0 reviews · Skipped day — streak kept", ui.describe(data, day(-4), english))
        self.assertEqual("0 reviews · Streak minimum met", ui.describe(data, day(-5), english))
        self.assertEqual("3 review cards due (estimate)", ui.describe(data, day(1), english))
        self.assertEqual("Forecast is available for the next 90 days.", ui.describe(data, day(91), english))

    def test_unjudged_reviews_are_not_called_a_met_day(self):
        data = heatmap.summarize(TODAY, {day(-1): 20}, {}, {day(-2)})
        self.assertEqual("20 reviews", ui.describe(data, day(-1), english))
        self.assertEqual("0 reviews · Protected — streak kept", ui.describe(data, day(-2), english))


class Block(unittest.TestCase):
    def test_sends_the_days_with_something_to_show(self):
        data = heatmap.summarize(TODAY, {day(-1): 2}, {day(3): 1})
        page = page_data(ui.html(data, english, "de_DE"))
        self.assertEqual("de-DE", page["lang"])
        self.assertEqual(("2024-03-01", "2024-05-30", 2024, 2024), (page["today"], page["end"], page["firstYear"], page["lastYear"]))
        self.assertEqual(2.0, page["average"])
        self.assertEqual({"2024-02-29": ["l", "2 reviews", 1, 2, 0], "2024-03-04": ["f", "1 review card due (estimate)", 1, 1, 0]}, page["days"])

    def test_a_label_cannot_end_the_script(self):
        block = ui.html(heatmap.summarize(TODAY, {}, {}), lambda text: text + "</script><b>")
        self.assertEqual(2, block.count("</script>") + block.count("<script>"))
        self.assertIn("<\\/script>", block)
        self.assertIn("&lt;/script&gt;", block)

    def test_collapsed_hides_the_body(self):
        self.assertIn("class=hm-body hidden", ui.html(heatmap.summarize(TODAY, {}, {}), english, expanded=False))
        self.assertIn("class=hm-body>", ui.html(heatmap.summarize(TODAY, {}, {}), english))

    def test_collapsed_keeps_the_stats(self):
        # As on Android, collapsing hides the calendar only.
        block = ui.html(heatmap.summarize(TODAY, {day(0): 1}, {}), english, expanded=False)
        self.assertLess(block.index("class=hm-stats"), block.index("class=hm-body"))
        self.assertLess(block.index("Reviews in available history"), block.index("class=hm-body"))

    def test_shows_the_share_of_days_studied(self):
        block = ui.html(heatmap.summarize(TODAY, {day(-2): 1, day(0): 1}, {}), english)
        self.assertIn("You studied on 66% of the days since your first review", block)
        self.assertNotIn("You studied on", ui.html(heatmap.summarize(TODAY, {}, {}), english))

    def test_offers_a_way_back_to_today(self):
        block = ui.html(heatmap.summarize(TODAY, {}, {}), english)
        self.assertIn("<button class=hm-today>Today</button>", block)
        self.assertIn('q("today").onclick', block)

    def test_says_so_before_the_first_review(self):
        self.assertIn("Your reviews will appear here after you study.", ui.html(heatmap.summarize(TODAY, {}, {}), english))
        self.assertNotIn("Your reviews will appear here", ui.html(heatmap.summarize(TODAY, {day(0): 1}, {}), english))


if __name__ == "__main__":
    unittest.main()
