"""Colours, fonts and spacing. Hot-reloaded: edit and save to see changes live.

There are several looks (``STYLES``) and, for the cozy ones, a palette per
season (``SEASONS``). ``use(style, season)`` swaps the module-level colours in
place; the layout calls it before every frame, so ``[display] style`` /
``season`` in config.toml pick the look and ``season = "auto"`` follows the
calendar.
"""

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

# extras used by the cozy styles (classic leaves them alone)
TOAST = (44, 52, 70)
TOAST_EDGE = (70, 80, 102)
GLOW = (255, 196, 70)           # warm lamp light
CARD_ALPHA = 255                # < 255: cards are frosted glass over the scenery
CARD_SHADOW = 0                 # drop-shadow strength under cards (0 = none)
DECOR: tuple = ()               # seasonal motif colours

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
    # Fraunces "Soft" — a warm, rounded serif for the cozy styles
    "serif-light": "Fraunces72ptSoft-Light.ttf",
    "serif": "Fraunces72ptSoft-Regular.ttf",
    "serif-semibold": "Fraunces72ptSoft-SemiBold.ttf",
    "serif-text": "Fraunces9ptSoft-SemiBold.ttf",
}
# semantic faces the layout asks for; styles remap them (see use())
FACE_MAP: dict = {"heading": "semibold"}
_fonts: dict = {}


def font(face: str, size: int) -> pygame.font.Font:
    face = FACE_MAP.get(face, face)
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


# ── styles & seasons ──────────────────────────────────────────────────────

STYLES = {
    "classic": "The original cool, dark look",
    "hearth": "Warm dark cards and lamplight, serif numbers",
    "almanac": "Light paper and ink, like a printed almanac",
    "window": "Frosted cards over a seasonal evening landscape",
}
SEASONS = ("autumn", "winter", "spring", "summer")
STYLE = "classic"
SEASON = "autumn"
KEY = ("classic", None)          # changes whenever the look changes → caches reset

_CLASSIC = {k: v for k, v in globals().items() if k.isupper() and k not in
            ("W", "H", "PAD", "GAP", "RADIUS", "FONT_DIR", "FACES", "STYLES", "SEASONS")}
_CLASSIC["FACE_MAP"] = dict(FACE_MAP)

SERIF_FACES = {"heading": "serif-text", "display-semibold": "serif-semibold",
               "display-light": "serif-light", "display": "serif"}

# Dark, warm palettes (hearth + window). Text is cream rather than white and
# nothing is blue-white, so the screen glows like a lamp, not a monitor.
DARK = {
    "autumn": dict(  # pumpkin, rust and walnut
        BG_TOP=(33, 22, 16), BG_BOTTOM=(22, 15, 11), CARD=(44, 31, 23), CARD_HI=(60, 42, 31),
        CARD_BORDER=(70, 51, 38), DIVIDER=(64, 47, 35), TEXT=(248, 236, 218), TEXT_SOFT=(228, 210, 186),
        MUTED=(180, 154, 126), FAINT=(124, 102, 82), ACCENT=(236, 146, 70), GLOW=(255, 150, 60),
        DECOR=((214, 104, 48), (232, 156, 64), (176, 74, 44), (196, 138, 60))),
    "winter": dict(  # ink and plum with candlelight gold and cranberry
        BG_TOP=(26, 22, 34), BG_BOTTOM=(17, 15, 24), CARD=(38, 33, 48), CARD_HI=(52, 45, 64),
        CARD_BORDER=(62, 55, 76), DIVIDER=(58, 51, 72), TEXT=(246, 240, 230), TEXT_SOFT=(222, 212, 204),
        MUTED=(166, 154, 164), FAINT=(112, 102, 118), ACCENT=(236, 188, 112), BAD=(222, 92, 96),
        GLOW=(255, 186, 100), DECOR=((236, 232, 240), (210, 204, 222), (196, 72, 82))),
    "spring": dict(  # moss and sage with blossom pink
        BG_TOP=(25, 29, 22), BG_BOTTOM=(18, 21, 16), CARD=(36, 42, 32), CARD_HI=(49, 57, 43),
        CARD_BORDER=(60, 70, 52), DIVIDER=(56, 65, 48), TEXT=(246, 242, 228), TEXT_SOFT=(224, 220, 198),
        MUTED=(166, 172, 146), FAINT=(110, 118, 96), ACCENT=(240, 156, 146), GOOD=(150, 204, 120),
        GLOW=(250, 214, 150), DECOR=((244, 178, 186), (250, 210, 214), (226, 140, 156))),
    "summer": dict(  # terracotta dusk with golden hour
        BG_TOP=(36, 22, 19), BG_BOTTOM=(24, 15, 14), CARD=(50, 32, 27), CARD_HI=(67, 43, 35),
        CARD_BORDER=(80, 53, 43), DIVIDER=(74, 49, 40), TEXT=(252, 238, 222), TEXT_SOFT=(232, 210, 190),
        MUTED=(192, 156, 134), FAINT=(130, 100, 86), ACCENT=(252, 176, 84), GLOW=(255, 172, 92),
        DECOR=((255, 222, 120), (255, 200, 96))),
}
_DARK_COMMON = dict(
    GOOD=(156, 196, 110), WARN=(244, 184, 76), BAD=(232, 106, 82),
    SUN=(255, 192, 84), MOON=(246, 234, 206), CLOUD=(226, 214, 200), CLOUD_BACK=(150, 134, 122),
    RAIN=(132, 176, 214), SNOW=(244, 240, 234), BOLT=(255, 206, 90),
    TEMP_COLD=(132, 176, 214), TEMP_MILD=(170, 196, 140), TEMP_WARM=(250, 170, 80),
)

# Light "paper" palettes (almanac): cream stock, sepia ink, one seasonal accent.
LIGHT = {
    "autumn": dict(BG_TOP=(243, 232, 212), BG_BOTTOM=(235, 220, 194), CARD=(250, 243, 229),
                   CARD_HI=(240, 226, 202), CARD_BORDER=(224, 206, 178), DIVIDER=(226, 210, 184),
                   TEXT=(54, 37, 26), TEXT_SOFT=(94, 68, 50), MUTED=(130, 105, 84), FAINT=(172, 150, 126),
                   ACCENT=(184, 82, 34), DECOR=((196, 96, 44), (214, 140, 56), (160, 70, 40), (184, 128, 52))),
    "winter": dict(BG_TOP=(238, 233, 226), BG_BOTTOM=(228, 221, 212), CARD=(249, 246, 241),
                   CARD_HI=(236, 230, 222), CARD_BORDER=(216, 208, 198), DIVIDER=(222, 214, 204),
                   TEXT=(40, 34, 46), TEXT_SOFT=(78, 68, 82), MUTED=(122, 112, 122), FAINT=(166, 156, 162),
                   ACCENT=(162, 46, 56), DECOR=((150, 162, 186), (186, 194, 210), (162, 46, 56))),
    "spring": dict(BG_TOP=(240, 238, 222), BG_BOTTOM=(229, 229, 208), CARD=(249, 248, 237),
                   CARD_HI=(234, 236, 216), CARD_BORDER=(212, 216, 190), DIVIDER=(218, 222, 198),
                   TEXT=(42, 50, 36), TEXT_SOFT=(74, 86, 62), MUTED=(116, 124, 100), FAINT=(160, 166, 142),
                   ACCENT=(190, 84, 104), DECOR=((232, 150, 166), (240, 190, 198), (132, 168, 108))),
    "summer": dict(BG_TOP=(248, 234, 212), BG_BOTTOM=(240, 220, 190), CARD=(252, 245, 232),
                   CARD_HI=(244, 228, 202), CARD_BORDER=(230, 208, 176), DIVIDER=(232, 214, 186),
                   TEXT=(62, 36, 24), TEXT_SOFT=(102, 66, 46), MUTED=(140, 104, 80), FAINT=(182, 148, 120),
                   ACCENT=(196, 92, 36), DECOR=((228, 166, 60), (214, 120, 60))),
}
_LIGHT_COMMON = dict(
    GOOD=(70, 132, 64), WARN=(196, 128, 20), BAD=(186, 58, 48),
    SUN=(238, 160, 40), MOON=(150, 136, 160), CLOUD=(184, 172, 160), CLOUD_BACK=(150, 136, 122),
    RAIN=(70, 120, 172), SNOW=(132, 150, 178), BOLT=(232, 160, 30),
    TEMP_COLD=(84, 132, 182), TEMP_MILD=(120, 160, 100), TEMP_WARM=(220, 132, 52),
    TOAST=(62, 46, 36), TOAST_EDGE=(62, 46, 36), CARD_SHADOW=26,
)


def season_for(when, season="auto") -> str:
    """Meteorological seasons: Dec–Feb winter, Mar–May spring, …"""
    if season in SEASONS:
        return season
    return ("winter", "spring", "summer", "autumn")[(when.month % 12) // 3]


def use(style: str = "classic", season: str = "autumn") -> bool:
    """Switch the palette. Returns True if anything changed."""
    global KEY
    style = style if style in STYLES else "classic"
    season = season if season in SEASONS else "autumn"
    key = (style, season if style != "classic" else None)
    if key == KEY:
        return False
    g = globals()
    g.update({k: (dict(v) if isinstance(v, dict) else v) for k, v in _CLASSIC.items()})
    if style == "almanac":
        g.update(_LIGHT_COMMON, **LIGHT[season])
    elif style in ("hearth", "window"):
        g.update(_DARK_COMMON, **DARK[season])
    if style != "classic":
        FACE_MAP.update(SERIF_FACES)
        g["TOAST"], g["TOAST_EDGE"] = (g["TOAST"], g["TOAST_EDGE"]) if style == "almanac" else \
            (mix(g["CARD_HI"], g["TEXT"], 0.06), mix(g["CARD_BORDER"], g["TEXT"], 0.12))
    if style == "window":
        g["CARD_ALPHA"] = 178
    g["STYLE"], g["SEASON"], KEY = style, season, key
    return True
