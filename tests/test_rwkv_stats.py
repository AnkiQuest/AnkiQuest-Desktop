"""The RWKV statistics: due/near/safe, the forecast line and the recall chart (rwkv_stats),
as AnkiQuest-Android's AnkiquestRwkvForecast and Pedrubik2000's anki-rwkv-forecast define them."""

import unittest

from addon_loader import load_in_package

rwkv = load_in_package("aq_rwkv_stats", "rwkv_stats")


def cards(*rows):
    """Each row is (target, now, 1h, 3h, tomorrow)."""
    return [rwkv.Recall(card_id=index, target=row[0], recall=row[1:]) for index, row in enumerate(rows)]


class Bands(unittest.TestCase):
    def test_below_the_target_is_due_and_just_above_is_near(self):
        self.assertEqual("due", rwkv.band(0.89, 0.9))
        self.assertEqual("near", rwkv.band(0.9, 0.9))
        self.assertEqual("near", rwkv.band(0.9 + rwkv.NEAR_MARGIN - 0.0001, 0.9))
        self.assertEqual("safe", rwkv.band(0.9 + rwkv.NEAR_MARGIN, 0.9))

    def test_every_offset_has_its_own_band(self):
        self.assertEqual("safe", rwkv.band(rwkv.Recall(2, 0.8, (0.9, 0.79, 0.5, 0.4)).recall[0], 0.8))
        self.assertEqual("due", rwkv.band(rwkv.Recall(2, 0.8, (0.9, 0.79, 0.5, 0.4)).recall[3], 0.8))


class Forecast(unittest.TestCase):
    def test_counts_due_near_safe_now_and_due_later(self):
        rows = cards(
            (0.9, 0.8, 0.8, 0.8, 0.8),  # due now, still due later
            (0.9, 0.9, 0.89, 0.8, 0.8),  # near now, due in 1 h
            (0.9, 0.95, 0.9, 0.5, 0.82),  # safe now, due in 3 h, due tomorrow
            (0.8, 0.85, 0.9, 0.95, 0.95),  # safe now under a lower target
        )
        forecast = rwkv.forecast(rows)
        self.assertEqual({"due": 1, "near": 1, "safe": 2, "in_1h": 1, "in_3h": 2, "by_tomorrow": 3}, forecast)

    def test_the_later_counts_leave_out_cards_due_now(self):
        # The first card is due now and due in 1 h: the +1 h count ignores it, the second card counts.
        rows = cards((0.9, 0.8, 0.89, 0.95, 0.95), (0.9, 0.95, 0.5, 0.5, 0.5))
        forecast = rwkv.forecast(rows)
        self.assertEqual(1, forecast["due"])
        self.assertEqual(1, forecast["in_1h"])
        self.assertEqual(1, forecast["in_3h"])
        self.assertEqual(1, forecast["by_tomorrow"])

    def test_without_cards_every_count_is_zero(self):
        self.assertEqual({"due": 0, "near": 0, "safe": 0, "in_1h": 0, "in_3h": 0, "by_tomorrow": 0}, rwkv.forecast([]))


class Percent(unittest.TestCase):
    def test_a_whole_percent_floor_with_floats_kept_in_place(self):
        self.assertEqual(90, rwkv.percent(0.9))
        self.assertEqual(100, rwkv.percent(1.0))
        self.assertEqual(51, rwkv.percent(0.512))
        self.assertEqual(50, rwkv.percent(0.505))

    def test_the_outer_buckets_take_everything_beyond(self):
        self.assertEqual(50, rwkv.percent(0.4999))
        self.assertEqual(50, rwkv.percent(0.0))
        self.assertEqual(100, rwkv.percent(1.5))
        self.assertEqual(50, rwkv.percent(-0.2))


class Chart(unittest.TestCase):
    def test_each_bucket_stacks_its_cards_by_band(self):
        rows = cards(
            (0.9, 0.5, 0.5, 0.5, 0.5),  # due below 50
            (0.9, 0.9, 0.9, 0.9, 0.9),  # near at 90
            (0.9, 0.95, 0.95, 0.95, 0.95),  # safe at 95
            (0.8, 0.84, 0.9, 0.9, 0.9),  # safe at 84 under the lower target
        )
        buckets, below, total, targets = rwkv.chart(rows)
        self.assertEqual(rwkv.HIGHEST - rwkv.LOWEST + 1, len(buckets))
        self.assertEqual((50, 1, 0, 0), buckets[0])
        self.assertEqual((90, 0, 1, 0), buckets[40])
        self.assertEqual((84, 0, 0, 1), buckets[34])
        self.assertEqual((95, 0, 0, 1), buckets[45])
        self.assertEqual({0.9, 0.8}, targets)
        self.assertEqual(1, below)
        self.assertEqual(4, total)

    def test_the_below_share_is_zero_without_cards(self):
        buckets, below, total, targets = rwkv.chart([])
        self.assertEqual(0.0, rwkv.below_share(below, total))
        self.assertEqual(rwkv.HIGHEST - rwkv.LOWEST + 1, len(buckets))
        self.assertEqual(0, total)


class Reading(unittest.TestCase):
    def test_backend_rows_keep_their_target_and_recalls(self):
        row = {"card_id": 7, "target_retention": 0.9, "recall": [0.8, 0.9, 0.95, 0.96]}
        (recall,) = rwkv._recalls_from({"available": True, "cards": [row]})
        self.assertEqual(7, recall.card_id)
        self.assertEqual(0.9, recall.target)
        self.assertEqual((0.8, 0.9, 0.95, 0.96), recall.recall)

    def test_an_unavailable_or_short_answer_is_nothing(self):
        self.assertEqual([], rwkv._recalls_from({"available": False, "cards": [{"card_id": 1, "target_retention": 0.9, "recall": [0.5, 0.5, 0.5, 0.5]}]}))
        self.assertEqual([], rwkv._recalls_from({"available": True, "cards": [{"card_id": 1, "target_retention": 0.9, "recall": [0.5, 0.5]}]}))
        self.assertEqual([], rwkv._recalls_from({"available": True, "cards": []}))

    def test_more_than_the_cap_hides_the_block(self):
        self.assertTrue(rwkv.too_large(rwkv.MAX_CARDS + 1))
        self.assertFalse(rwkv.too_large(rwkv.MAX_CARDS))


def plain_plural(one, other, count):
    """The test's own plural choice, so the words stay English whatever Anki reports."""
    return one if count == 1 else other


class Lines(unittest.TestCase):
    def test_the_forecast_lines_match_android(self):
        forecast = {"due": 62, "near": 4, "safe": 294, "in_1h": 3, "in_3h": 8, "by_tomorrow": 70}
        self.assertEqual("due 62 | near 4 | safe 294\n" + "due 62 · +3 in 1 h · +8 in 3 h · 70 by tomorrow", rwkv.forecast_text(forecast))

    def test_the_below_line_names_the_single_target(self):
        buckets, below, total, targets = rwkv.chart(cards((0.9, 0.5, 0.5, 0.5, 0.5), (0.9, 0.95, 0.95, 0.95, 0.95)))
        self.assertEqual("1 of 2 cards (50%) below 90%", rwkv.below_line(below, total, targets, plain_plural))
        self.assertEqual("1 of 1 card (100%) below 90%", rwkv.below_line(1, 1, {0.9}, plain_plural))

    def test_the_below_line_says_desired_retention_with_several_targets(self):
        buckets, below, total, targets = rwkv.chart(cards((0.9, 0.5, 0.5, 0.5, 0.5), (0.8, 0.9, 0.9, 0.9, 0.9)))
        self.assertEqual("1 of 2 cards (50%) below their desired retention", rwkv.below_line(below, total, targets, plain_plural))


if __name__ == "__main__":
    unittest.main()
