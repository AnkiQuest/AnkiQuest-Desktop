"""The add-on's web views: text stays readable in day and night mode (4.5:1, WCAG AA)."""

import re
import unittest

from addon_loader import load_in_package

board = load_in_package("ankiquest_a11y_test", "board")
heatmap_ui = load_in_package("ankiquest_a11y_test", "heatmap_ui")

# The style rules that colour text with the palette's fills get an ink of their own instead,
# dark in day mode and lighter at night, so both modes read on their own backgrounds.
TEXT_RULES = (
    (r"#ankiquest .aq-count.aq-review\{[^}]*color:var\(--aq-blue-ink\)", "the review count"),
    (r"#ankiquest .aq-count.aq-learn\{[^}]*color:var\(--aq-red-ink\)", "the learning count"),
    (r"#ankiquest .aq-count.aq-new\{[^}]*color:var\(--aq-green-ink\)", "the new count"),
    (r"#ankiquest .aq-done-today\{[^}]*color:var\(--aq-green-ink\)", "the done-today line"),
    (r"#ankiquest .aq-learning-later\{[^}]*color:var\(--aq-orange-ink\)", "the later line"),
    (r"#ankiquest .aq-xp\{[^}]*color:var\(--aq-orange-ink\)", "a player's XP"),
    (r"#ankiquest .aq-goal-edit\{[^}]*color:var\(--aq-blue-ink\)", "the goal edit link"),
    (r"#ankiquest .aq-empty-note a\{[^}]*color:var\(--aq-blue-ink\)", "an empty note's link"),
    (r"#ankiquest .aq-links a\{[^}]*color:var\(--aq-blue-ink\)", "an action link"),
)


def variables(style):
    """The CSS variables by the block they are set in, keyed by the block's selector."""
    found = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        names = {name: value for name, value in re.findall(r"(--[\w-]+):\s*(#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?)", body)}
        if names:
            found[selector.strip()] = names
    return found


def palettes(style):
    """The day palette (the plain block) and the night one (the .nightMode override)."""
    day = {}
    night = {}
    for selector, names in variables(style).items():
        if selector.startswith(".nightMode"):
            night.update(names)
        else:
            day.update(names)
        apply = night if selector.startswith(".nightMode") else day
        apply.update({name: value for name, value in names.items()})
    for name, value in day.items():
        night.setdefault(name, value)
    return day, night


def contrast(foreground, background):
    """The WCAG contrast ratio of two #rgb or #rrggbb colours."""
    if len(foreground) == 4:
        foreground = "#" + "".join(char * 2 for char in foreground[1:])
    if len(background) == 4:
        background = "#" + "".join(char * 2 for char in background[1:])

    def luminance(colour):
        parts = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in parts]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class WebAccessibility(unittest.TestCase):
    def test_the_text_rules_use_the_readable_inks(self):
        for pattern, what in TEXT_RULES:
            with self.subTest(rule=what):
                self.assertTrue(re.search(pattern, board.STYLE), pattern)

    def test_the_palette_reads_in_day_and_night_modes(self):
        for mode, palette in zip(("day", "night"), palettes(board.STYLE)):
            for foreground, background in (
                ("--aq-text", "--aq-bg"),
                ("--aq-muted", "--aq-bg"),
                ("--aq-muted", "--aq-soft"),
                ("--aq-blue-ink", "--aq-bg"),
                ("--aq-blue-ink", "--aq-soft"),
                ("--aq-green-ink", "--aq-bg"),
                ("--aq-green-ink", "--aq-soft"),
                ("--aq-red-ink", "--aq-bg"),
                ("--aq-red-ink", "--aq-soft"),
                ("--aq-orange-ink", "--aq-bg"),
                ("--aq-orange-ink", "--aq-soft"),
            ):
                with self.subTest(mode=mode, colour=foreground, on=background):
                    self.assertGreaterEqual(contrast(palette[foreground], palette[background]), 4.5)

    def test_the_heatmap_reads_in_day_and_night_modes(self):
        for mode, palette in zip(("day", "night"), palettes(heatmap_ui.STYLE)):
            for foreground, background in (("--hm-text", "--hm-bg"), ("--hm-muted", "--hm-bg")):
                with self.subTest(mode=mode, colour=foreground, on=background):
                    self.assertGreaterEqual(contrast(palette[foreground], palette[background]), 4.5)

    def test_bright_pill_badges_carry_their_own_ink(self):
        # The bright pill badges keep their fills; their text is the fill's own ink, like the
        # avatar initials, so every pill reads (WCAG AA, 4.5:1) in day mode; night keeps the fills.
        day, night = palettes(board.STYLE)
        for kind, fill, ink in (
            ("streak", "--aq-orange", "#5c3000"),
            ("level", "--aq-purple", "#23272e"),
            ("risk", "--aq-red", "#23272e"),
            ("rank", "--aq-gold", "#5c4400"),
        ):
            with self.subTest(pill=kind):
                rule = re.search(r"\.aq-pill\.aq-%s\{[^}]*\}" % kind, board.STYLE)
                self.assertIsNotNone(rule, kind)
                colours = dict(re.findall(r"(background|color):([^;}]*)", rule.group(0)))
                self.assertEqual(fill, colours["background"].strip().replace("var(", "").rstrip(")"), kind)
                self.assertEqual(ink, colours["color"].strip(), kind)
                for mode, palette in (("day", day), ("night", night)):
                    with self.subTest(mode=mode):
                        self.assertGreaterEqual(contrast(ink, palette[fill]), 4.5)

    def test_deck_row_day_badges_carry_their_own_ink(self):
        # A deck row's day badge tints the row with its colour and writes its text in
        # the colour's own ink: dark in day mode, lighter at night, both on the badge's tint.
        today = load_in_package("ankiquest_a11y_test", "today")
        day, night = today.BADGE_INKS.split(".nightMode", 1)
        ink = lambda block, name: re.search(
            "(?:^|[,}> ])\\.ankiquest-day\\.ankiquest-%s\\{color:(#[0-9a-f]{6})\\}" % name, block).group(1)
        day_inks = {status.replace("_", "-"): ink(day, status.replace("_", "-")) for status in today.BADGE_STYLE}
        night_inks = {status.replace("_", "-"): ink(".night" + night, status.replace("_", "-")) for status in today.BADGE_STYLE}

        alpha = 0x22 / 255

        def tint(fill, row):
            return "#" + "".join(
                "%02x" % round((1 - alpha) * int(row[index:index + 2], 16) + alpha * int(fill[index:index + 2], 16))
                for index in (1, 3, 5)
            )

        for status, (_icon, colour) in today.BADGE_STYLE.items():
            for mode, inks, row in (("day", day_inks, "#ffffff"), ("night", night_inks, "#1e1f22")):
                with self.subTest(status=status, mode=mode):
                    self.assertGreaterEqual(contrast(inks[status.replace("_", "-")], tint(colour, row)), 4.5)

    def test_avatar_initials_read_on_every_avatar_colour(self):
        for colour, ink in zip(board.AVATAR_COLOURS, board.AVATAR_INKS):
            with self.subTest(colour=colour):
                self.assertGreaterEqual(contrast(ink, colour), 4.5)

        # The web view's avatar span carries its ink, not only its fill.
        for name in ("hill", "AldanaBRZ", "float3"):
            with self.subTest(name=name):
                span = board.avatar(name)
                fill = re.search(r"background:(#\w+)", span).group(1)
                ink = re.search(r"color:(#\w+)", span)
                self.assertIsNotNone(ink, span)
                self.assertGreaterEqual(contrast(ink.group(1), fill), 4.5)


if __name__ == "__main__":
    unittest.main()
