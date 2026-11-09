"""Design tokens and wording helpers. Pure Python, so these run on every CI platform."""
from pathlib import Path
import unittest
from datetime import datetime, timedelta, timezone
from vapor_board import ui_theme
from vapor_board.radio_event_state import RadioDisplayState
from vapor_board.tcp import ConnectionState
from vapor_board.ui_format import friendly_time, radio_presentation, first_line, plural

ACCENTS = ("#238C9C", "#FFE066", "#F5F5F5", "#111111", "#FF0000", "#00FF7F", "#6F42C1")


class ContrastTests(unittest.TestCase):
    def test_contrast_ratio_matches_wcag(self):
        self.assertAlmostEqual(ui_theme.contrast("#000000", "#FFFFFF"), 21.0, places=1)
        self.assertAlmostEqual(ui_theme.contrast("#777777", "#777777"), 1.0)

    def test_text_tokens_are_readable_on_every_surface(self):
        for palette in (ui_theme.LIGHT, ui_theme.DARK):
            for surface in (palette.background, palette.card, palette.field, palette.sidebar):
                with self.subTest(palette=palette.name, surface=surface):
                    self.assertGreaterEqual(ui_theme.contrast(palette.text, surface), 7.0)
                    self.assertGreaterEqual(ui_theme.contrast(palette.muted, surface), 4.5)

    def test_status_colours_are_readable_on_cards(self):
        for palette in (ui_theme.LIGHT, ui_theme.DARK):
            for colour in (palette.success, palette.warning, palette.info, ui_theme.readable(palette.danger, palette.card)):
                with self.subTest(palette=palette.name, colour=colour):
                    self.assertGreaterEqual(ui_theme.contrast(colour, palette.card), 4.5)

    def test_only_disabled_controls_use_the_faint_colour(self):
        source = (Path(ui_theme.__file__).read_text() + (Path(ui_theme.__file__).parent / "desktop.py").read_text()).splitlines()
        uses = [line for line in source if ".subtle" in line]
        self.assertTrue(uses)
        for line in uses:
            with self.subTest(line=line.strip()):
                self.assertIn('"disabled"', line)

    def test_any_shop_accent_stays_readable(self):
        for palette in (ui_theme.LIGHT, ui_theme.DARK):
            for accent in ACCENTS:
                themed = ui_theme.with_accent(palette, accent)
                with self.subTest(palette=palette.name, accent=accent):
                    self.assertGreaterEqual(ui_theme.contrast(themed.on_accent, themed.accent_fill), 4.5)
                    self.assertGreaterEqual(ui_theme.contrast(themed.accent_text, themed.card), 4.5)
                    self.assertGreaterEqual(ui_theme.contrast(themed.text, themed.selection), 4.5)

    def test_text_scales(self):
        self.assertEqual(set(ui_theme.TEXT_SCALES), {"standard", "large", "larger"})
        self.assertLess(ui_theme.TEXT_SCALES["standard"], ui_theme.TEXT_SCALES["larger"])


class FriendlyTimeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)

    def stamp(self, delta):
        return (self.now - delta).strftime("%Y-%m-%d %H:%M:%S")

    def test_relative_days(self):
        local_now = self.now.astimezone()
        today = friendly_time(self.stamp(timedelta(minutes=5)), now=self.now)
        self.assertTrue(today.startswith("Today ") or local_now.hour == 0)
        self.assertTrue(friendly_time(self.stamp(timedelta(days=1)), now=self.now).startswith("Yesterday "))
        self.assertRegex(friendly_time(self.stamp(timedelta(days=20)), now=self.now), r"^[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [AP]M$")
        self.assertRegex(friendly_time("2020-03-04 10:00:00", now=self.now), r"^Mar [34], 2020$")

    def test_unparseable_text_is_shown_as_is(self):
        self.assertEqual(friendly_time("soon"), "soon")
        self.assertEqual(friendly_time(None), "None")


class RadioWordingTests(unittest.TestCase):
    def test_every_state_has_plain_wording(self):
        cases = {
            RadioDisplayState(): ("neutral", "Not connected"),
            RadioDisplayState(ConnectionState.CONNECTING): ("warning", "Connecting…"),
            RadioDisplayState(ConnectionState.CONNECTED): ("info", "Connected"),
            RadioDisplayState(ConnectionState.CONNECTED, True, 1): ("success", "Receiving"),
            RadioDisplayState(ConnectionState.ERROR, detail="Connection refused"): ("danger", "Connection problem"),
        }
        for state, (kind, label) in cases.items():
            with self.subTest(state=state):
                self.assertEqual(radio_presentation(state)[:2], (kind, label))

    def test_errors_include_the_cause_and_a_next_step(self):
        text = radio_presentation(RadioDisplayState(ConnectionState.ERROR, detail="Connection refused"))[2]
        self.assertTrue(text.startswith("Connection refused. "))
        self.assertIn("4403", text)

    def test_packet_count_wording(self):
        self.assertIn("1 packet received", radio_presentation(RadioDisplayState(ConnectionState.CONNECTED, True, 1))[2])
        self.assertIn("3 packets received", radio_presentation(RadioDisplayState(ConnectionState.CONNECTED, True, 3))[2])


class TextHelperTests(unittest.TestCase):
    def test_first_line_trims_with_an_ellipsis(self):
        self.assertEqual(first_line("Short\nsecond", 40), "Short")
        self.assertEqual(first_line("", 10), "")
        self.assertEqual(first_line("abcdefghijkl", 6), "abcde…")

    def test_plural(self):
        self.assertEqual(plural(1, "post"), "1 post")
        self.assertEqual(plural(2, "post"), "2 posts")


if __name__ == "__main__":
    unittest.main()
