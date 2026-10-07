import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from map import screen  # noqa: E402

# captured from `herdr pane read --ansi` of a Claude pane
CLAUDE = ("\x1b[0m\x1b[38;2;80;80;80m\x1b[48;2;70;70;70m❯ Read your brief\x1b[0m\r\n"
          "\x1b[2m\x1b[38;2;248;248;242m  7 \x1b[0m\x1b[38;5;208m✻\x1b[39m done\r\n")


def text(rows):
    return ["".join(c for c, _ in row).rstrip() for row in rows]


class ParseTest(unittest.TestCase):
    def test_truecolor_and_reset(self):
        rows, clipped = screen.parse(CLAUDE, 30, 2)
        self.assertEqual(text(rows), ["❯ Read your brief", "  7 ✻ done"])
        self.assertFalse(clipped)
        ch, attr = rows[0][0]
        self.assertEqual(attr.fg, (80, 80, 80))
        self.assertEqual(attr.bg, (70, 70, 70))
        self.assertEqual(rows[0][20][1], screen.PLAIN)
        self.assertTrue(rows[1][2][1].dim)

    def test_256_bright_and_default(self):
        rows, _ = screen.parse(CLAUDE, 30, 2)
        star = next(a for c, a in rows[1] if c == "✻")
        self.assertEqual(star.fg, 208)
        done = next(a for c, a in rows[1] if c == "d")
        self.assertIsNone(done.fg)
        rows, _ = screen.parse("\x1b[1;91;104mX\x1b[22mY", 4, 1)
        self.assertEqual(rows[0][0][1], screen.Attr(fg=9, bg=12, bold=True))
        self.assertFalse(rows[0][1][1].bold)

    def test_wide_characters_take_two_cells(self):
        rows, _ = screen.parse("漢字ab", 6, 1)
        self.assertEqual([c for c, _ in rows[0]], ["漢", "", "字", "", "a", "b"])

    def test_clip_and_bottom_rows(self):
        rows, clipped = screen.parse("abcdef\n1\n2\n3", 3, 2)
        self.assertTrue(clipped)
        self.assertEqual(text(rows), ["2", "3"])
        rows, _ = screen.parse("a", 2, 3)
        self.assertEqual(len(rows), 3)

    def test_other_sequences_skipped(self):
        rows, _ = screen.parse("\x1b[2K\x1b[?25la\x1b]0;title\x07b\x1b[3Cc", 5, 1)
        self.assertEqual(text(rows), ["abc"])

    def test_nearest256(self):
        self.assertEqual(screen.nearest256((255, 0, 0)), 196)
        self.assertEqual(screen.nearest256((0, 0, 0)), 16)
        self.assertEqual(screen.nearest256((128, 128, 128)), 244)


if __name__ == "__main__":
    unittest.main()
