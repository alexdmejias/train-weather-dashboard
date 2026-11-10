"""Styles and seasonal palettes.  Run: python3 -m pytest"""

import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

pygame.display.init()
pygame.font.init()

import layout  # noqa: E402
import theme  # noqa: E402
from dashboard import State  # noqa: E402
from sources import mock  # noqa: E402


def test_season_follows_calendar():
    assert [theme.season_for(date(2026, m, 1)) for m in (12, 1, 3, 6, 9, 11)] == \
        ["winter", "winter", "spring", "summer", "autumn", "autumn"]
    assert theme.season_for(date(2026, 1, 1), "summer") == "summer"   # pinned


def test_classic_is_restored_after_a_cozy_look():
    before = (theme.CARD, theme.TEXT, dict(theme.FACE_MAP))
    theme.use("hearth", "winter")
    assert theme.TEXT != before[1] and theme.FACE_MAP["heading"].startswith("serif")
    theme.use("classic")
    assert (theme.CARD, theme.TEXT, dict(theme.FACE_MAP)) == before


def test_every_look_renders():
    now = datetime(2026, 11, 9, 18, 42).astimezone()
    surf = pygame.Surface((theme.W, theme.H))
    for style in theme.STYLES:
        for season in theme.SEASONS:
            for page in (0, 1, 2):
                state = State(now=now, station="Steinway St", location="Astoria", page=page,
                              departures=mock.trains(now, "alerts"), weather=mock.weather(now, "alerts"),
                              subway_alerts=mock.subway_alerts(now, "alerts"),
                              weather_alerts=mock.weather_alerts(now, "alerts"),
                              style=style, season=season)
                layout.draw(surf, state)
    theme.use("classic")


def test_warming_prepares_other_looks_without_disturbing_the_screen():
    now = datetime(2026, 11, 9, 18, 42).astimezone()
    state = State(now=now, station="Steinway St", location="Astoria", departures=mock.trains(now, "normal"),
                  weather=mock.weather(now, "normal"), style="hearth")
    surf = pygame.Surface((theme.W, theme.H))
    layout.draw(surf, state)
    cards = list(layout.CARD_RECTS)
    layout._warmed.clear()
    rounds = 0
    while layout.warm(state):
        rounds += 1
    assert rounds == len(theme.STYLES) - 1
    assert state.style == "hearth" and not state.settings_open and theme.STYLE == "hearth"
    assert layout.CARD_RECTS == cards
    import scenery
    assert all(("window" if s == "window" else s, "autumn") in scenery._cache for s in ("almanac", "window"))
    theme.use("classic")
