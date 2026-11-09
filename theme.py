"""Colours, fonts and spacing. Hot-reloaded: edit and save to see changes live."""

from __future__ import annotations

from pathlib import Path

import pygame

W, H = 800, 480
PAD = 22            # outer margin
GAP = 14            # space between cards
RADIUS = 18         # card corner radius

# ── palette ───────────────────────────────────────────────────────────────
BG_TOP = (10, 13, 20)
BG_BOTTOM = (15, 19, 29)
CARD = (21, 26, 38)
CARD_HI = (28, 34, 49)          # highlighted row / chip
CARD_BORDER = (35, 42, 58)
DIVIDER = (33, 40, 55)

TEXT = (236, 240, 246)
TEXT_SOFT = (196, 203, 216)     # secondary emphasis (station name on a row)
MUTED = (139, 149, 168)
FAINT = (86, 95, 114)

ACCENT = (110, 168, 254)
GOOD = (64, 210, 140)
WARN = (245, 182, 66)
BAD = (240, 104, 104)

# weather icon colours
SUN = (255, 196, 70)
MOON = (220, 228, 246)
CLOUD = (214, 221, 233)
CLOUD_BACK = (139, 151, 172)
RAIN = (98, 160, 255)
SNOW = (232, 240, 252)
BOLT = (255, 210, 80)

# temperature range bar (cold → warm)
TEMP_COLD = (98, 160, 255)
TEMP_MILD = (110, 214, 190)
TEMP_WARM = (255, 182, 80)

DEFAULT_LINE = (120, 132, 156)

# ── fonts ─────────────────────────────────────────────────────────────────
FONT_DIR = Path(__file__).parent / "assets" / "fonts"
FACES = {
    "regular": "Inter-Regular.otf",
    "medium": "Inter-Medium.otf",
    "semibold": "Inter-SemiBold.otf",
    "bold": "Inter-Bold.otf",
    "display-light": "InterDisplay-Light.otf",
    "display": "InterDisplay-Medium.otf",
    "display-semibold": "InterDisplay-SemiBold.otf",
}
_fonts: dict = {}


def font(face: str, size: int) -> pygame.font.Font:
    key = (face, size)
    if key not in _fonts:
        _fonts[key] = pygame.font.Font(str(FONT_DIR / FACES[face]), size)
    return _fonts[key]


def hex_color(value, default=DEFAULT_LINE):
    if not value:
        return default
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
