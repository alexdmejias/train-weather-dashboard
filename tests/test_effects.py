"""Animated effects, holidays and the settings page.  Run: python3 -m pytest"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

pygame.display.init()
pygame.font.init()

import config  # noqa: E402
import dashboard  # noqa: E402
import effects  # noqa: E402
import layout  # noqa: E402
import theme  # noqa: E402
from dashboard import State  # noqa: E402
from sources import mock  # noqa: E402


def _state(when, scenario="normal", **kw):
    now = datetime(*when).astimezone()
    return State(now=now, station="Steinway St", location="Astoria", departures=mock.trains(now, scenario),
                 weather=mock.weather(now, scenario), style="hearth", **kw)


def setup_function():
    effects.preview("", 0)
    effects._S["layers"].clear()


def test_weather_and_season_pick_effects():
    def now_raining(code, minute):
        st = _state((2026, 11, 9, 8, minute))
        st.weather.code = code
        return effects.plan(st)
    assert "rain" in now_raining(63, 1) and "leaves" not in now_raining(65, 2)   # heavy rain: no leaves
    assert {"rain", "thunder"} <= set(now_raining(95, 3))
    assert "snow" in now_raining(73, 4) and "fog" in now_raining(45, 5)
    st = _state((2026, 11, 9, 8, 6))
    st.weather.wind = 28
    assert effects.plan(st)["wind"] > 0.8
    assert "leaves" in effects.plan(_state((2026, 10, 9, 12, 0)))          # autumn
    assert effects.plan(_state((2026, 10, 9, 12, 0), effects="off")) == {}


def test_holidays():
    assert {"christmas", "snow"} <= set(effects.holidays(datetime(2026, 12, 20, 9, 0)))
    assert "bats" in effects.holidays(datetime(2026, 10, 31, 19, 0))
    assert "bats" not in effects.holidays(datetime(2026, 10, 31, 12, 0))   # bats come out at dusk
    assert "fireworks" in effects.holidays(datetime(2026, 12, 31, 23, 58))
    assert "fireworks" in effects.holidays(datetime(2027, 1, 1, 0, 10))
    assert effects.special_message(datetime(2026, 11, 26, 9), {}) == "Happy Thanksgiving!"
    assert effects.special_message(datetime(2026, 3, 14, 9), {"03-14": "Happy birthday, Sam!"}) == "Happy birthday, Sam!"
    assert effects.special_message(datetime(2026, 12, 25, 9), {}, builtin=False) is None


def test_own_dates_get_confetti_holidays_dont():
    assert "confetti" in effects.plan(_state((2026, 3, 14, 9, 0), special_dates={"03-14": "Hi"}))
    assert "confetti" not in effects.plan(_state((2026, 12, 25, 9, 0)))


def test_every_effect_animates():
    surf = pygame.Surface((theme.W, theme.H))
    for name in effects.PREVIEWS:
        st = _state((2026, 11, 9, 18, 42))
        layout.draw(surf, st)
        effects._S["layers"].clear()
        effects.preview(name, 60)
        for _ in range(60):
            effects.step(surf, st, 1 / 24)
        assert effects._S["layers"], name
    effects.preview("", 0)
    theme.use("classic")


def test_settings_page_lists_every_choice():
    surf = pygame.Surface((theme.W, theme.H))
    layout.draw(surf, _state((2026, 11, 9, 18, 42), settings_open=True))
    keys = {(k, v) for _, k, v in layout.SETTINGS_HITS}
    assert ("done", None) in keys and ("style", "window") in keys and ("try", "christmas") in keys
    rects = [r for r, _, _ in layout.SETTINGS_HITS]
    assert all(surf.get_rect().contains(r) for r in rects)
    assert not any(a.colliderect(b) for i, a in enumerate(rects) for b in rects[i + 1:])
    theme.use("classic")


def test_settings_are_saved_and_win_over_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", tmp_path / "settings.json")
    config.save_setting("display", "style", "window")
    config.save_setting("effects", "mode", "subtle")
    (tmp_path / "settings.json").write_text(json.dumps({**json.loads((tmp_path / "settings.json").read_text()),
                                                        "subway": {"stations": ["evil"]}}))
    cfg = config.load(tmp_path / "missing.toml")
    assert cfg["display"]["style"] == "window" and cfg["effects"]["mode"] == "subtle"
    assert cfg["subway"]["stations"] != ["evil"]          # only page-settable keys are honoured


def test_corners():
    assert dashboard._in_corner((5, 5)) and dashboard._in_corner((795, 475))
    assert not dashboard._in_corner((400, 5)) and not dashboard._in_corner((5, 240))
    assert dashboard._effects_mode("auto") in ("on", "off")
