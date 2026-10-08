# ---
# name: map.icons
# description: Agent logos and state marks for the map — the Private Use Area codepoints of the "Herdr Agent Icons Max" font, which ships in assets/fonts/ and is installed per user on first use (no elevation); used once the font is present (PROMETHEUS_MAP_ICONS=font|text overrides), plain Unicode otherwise.
# usage: imported (from map import icons); icons.font_wanted() → bool · python3 lib/map/icons.py install
# ---
# Font and codepoint tables from herdr-radar (https://github.com/hhdebb/herdr-radar), MIT License;
# notices in assets/fonts/. The tables must match the font, so they are copied, not re-derived.
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

FONT_FILES = "HerdrAgentIconsMax*"
FONT_DIRS = ("~/Library/Fonts", "/Library/Fonts", "~/.local/share/fonts", "~/.fonts")
BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "assets", "fonts", "HerdrAgentIconsMax-Regular.ttf")

LOGOS = {
    "claude": "", "codex": "", "opencode": "", "omp": "", "cline": "",
    "mastracode": "", "kimi": "", "kilo": "", "maki": "", "pi": "",
    "hermes": "", "cursor": "", "copilot": "", "deepseek": "", "gemini": "",
    "gpt": "", "qwen": "", "grok": "", "agy": "", "kiro": "", "amp": "",
    "devin": "", "qodercli": "", "glm": "", "kimchi": "", "muse": "",
    "crush": "",
}

# radar draws working, idle and done-fresh with one ring and lets colour carry the state
STATES = {
    "working": "", "idle": "", "done": "", "blocked": "", "unknown": "",
}


def font_installed() -> bool:
    for folder in FONT_DIRS:
        if glob.glob(os.path.join(os.path.expanduser(folder), "**", FONT_FILES), recursive=True):
            return True
    return False


def user_font_dir() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Fonts")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "fonts")


def install() -> str | None:
    """Copy the bundled font into the user's font folder; the installed path, or None if it could not."""
    if not os.path.isfile(BUNDLED):
        return None
    target = os.path.join(user_font_dir(), os.path.basename(BUNDLED))
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(BUNDLED, target)
    except OSError:
        return None
    if shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", os.path.dirname(target)], capture_output=True, timeout=30)
    return target


def font_wanted() -> bool:
    """Whether to draw with the icon font. In auto mode a missing font is installed, but this run stays on
    text: a terminal that is already open may not pick up a font added while it runs."""
    choice = (os.environ.get("PROMETHEUS_MAP_ICONS") or "auto").strip().lower()
    if choice in ("font", "text"):
        return choice == "font"
    if font_installed():
        return True
    install()
    return False


if __name__ == "__main__":
    if sys.argv[1:] == ["install"]:
        path = install()
        print(path or "icons: could not install the bundled font", file=sys.stdout if path else sys.stderr)
        sys.exit(0 if path else 1)
    print("usage: icons.py install", file=sys.stderr)
    sys.exit(2)
