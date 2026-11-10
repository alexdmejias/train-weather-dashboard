"""Weather icons drawn in code — no image assets needed.

Icons are drawn at 4× size and smooth-scaled down, which gives clean
anti-aliased edges even though pygame's shape drawing has none. Results are
cached, so each icon is only drawn once per size.
"""

from __future__ import annotations

import math

import pygame

import theme as T

SS = 4                       # supersampling factor
CLEAR = (0, 0, 0, 0)         # pygame.draw writes this straight through → "eraser"
_cache: dict = {}

CONDITIONS = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}


def condition(code: int) -> str:
    return CONDITIONS.get(code, "—")


def kind(code: int, is_day: bool = True) -> str:
    if code == 0:
        return "clear-day" if is_day else "clear-night"
    if code in (1, 2):
        return "partly-day" if is_day else "partly-night"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunder"
    return "cloudy"


def icon(code: int, is_day: bool, size: int) -> pygame.Surface:
    key = (kind(code, is_day), size, T.KEY)     # colours depend on the look
    if key not in _cache:
        if len(_cache) > 400:
            _cache.clear()
        _cache[key] = _render(key[0], size)
    return _cache[key]


# ── drawing ───────────────────────────────────────────────────────────────

def _render(name: str, size: int) -> pygame.Surface:
    S = size * SS
    s = pygame.Surface((S, S), pygame.SRCALPHA)
    k = S / 100  # draw in a 100×100 unit box

    def P(x, y):
        return (x * k, y * k)

    if name == "clear-day":
        _sun(s, P(50, 50), 21 * k, rays=True)
    elif name == "clear-night":
        _moon(s, P(50, 50), 30 * k)
    elif name in ("partly-day", "partly-night"):
        if name == "partly-day":
            _sun(s, P(37, 37), 15 * k, rays=True)
        else:
            _moon(s, P(38, 36), 21 * k)
        _cloud(s, P(57, 63), 68 * k, T.CLOUD, gap=4 * k)
    elif name == "cloudy":
        _cloud(s, P(63, 42), 60 * k, T.CLOUD_BACK)
        _cloud(s, P(42, 60), 72 * k, T.CLOUD, gap=4 * k)
    else:
        _cloud(s, P(50, 44), 76 * k, T.CLOUD)
        if name == "rain":
            for x in (34, 50, 66):
                _stroke(s, P(x, 68), P(x - 5, 84), 5.5 * k, T.RAIN)
        elif name == "drizzle":
            for x, y in ((35, 70), (51, 74), (67, 70)):
                _stroke(s, P(x, y), P(x - 2, y + 7), 5 * k, T.RAIN)
        elif name == "snow":
            for x, y in ((32, 74), (50, 84), (68, 74)):
                _flake(s, P(x, y), 8 * k)
        elif name == "thunder":
            bolt = [(52, 62), (39, 81), (49, 81), (44, 96), (62, 74), (52, 74), (58, 62)]
            pygame.draw.polygon(s, T.BOLT, [P(*p) for p in bolt])
        elif name == "fog":
            _stroke(s, P(20, 74), P(74, 74), 6 * k, T.CLOUD_BACK)
            _stroke(s, P(30, 86), P(82, 86), 6 * k, T.CLOUD_BACK)

    return pygame.transform.smoothscale(s, (size, size))


def _circle(s, color, c, r):
    pygame.draw.circle(s, color, (round(c[0]), round(c[1])), max(1, round(r)))


def _stroke(s, a, b, w, color):
    """Line with round caps."""
    pygame.draw.line(s, color, a, b, max(1, round(w)))
    _circle(s, color, a, w / 2)
    _circle(s, color, b, w / 2)


def _sun(s, c, r, rays=True):
    _circle(s, T.SUN, c, r)
    if rays:
        for i in range(8):
            a = i * math.pi / 4
            p1 = (c[0] + math.cos(a) * r * 1.45, c[1] + math.sin(a) * r * 1.45)
            p2 = (c[0] + math.cos(a) * r * 1.85, c[1] + math.sin(a) * r * 1.85)
            _stroke(s, p1, p2, r * 0.26, T.SUN)


def _moon(s, c, r):
    _circle(s, T.MOON, c, r)
    _circle(s, CLEAR, (c[0] + r * 0.55, c[1] - r * 0.38), r * 0.82)


def _cloud(s, c, w, color, gap=0.0):
    """A cloud of width ``w`` whose flat base sits at ``c[1] + 0.2w``.

    ``gap`` first erases a slightly larger cloud, leaving a thin transparent
    outline that separates it from whatever is drawn behind (sun, moon…).
    """
    cx, cy = c
    parts = [
        ((cx + 0.04 * w, cy - 0.06 * w), 0.25 * w),
        ((cx - 0.25 * w, cy + 0.04 * w), 0.16 * w),
        ((cx + 0.32 * w, cy + 0.06 * w), 0.14 * w),
    ]
    base = pygame.Rect(0, 0, 0, 0)
    base.left, base.right = round(cx - 0.25 * w), round(cx + 0.32 * w)
    base.top, base.bottom = round(cy + 0.02 * w), round(cy + 0.20 * w)

    if gap:
        for (pc, r) in parts:
            _circle(s, CLEAR, pc, r + gap)
        pygame.draw.rect(s, CLEAR, base.inflate(gap * 2, gap * 2))
    for (pc, r) in parts:
        _circle(s, color, pc, r)
    pygame.draw.rect(s, color, base)
    # round the two bottom corners so the base isn't boxy
    for (pc, r) in parts[1:]:
        _circle(s, color, pc, r)


def _flake(s, c, r):
    for i in range(3):
        a = i * math.pi / 3 + math.pi / 2
        dx, dy = math.cos(a) * r, math.sin(a) * r
        _stroke(s, (c[0] - dx, c[1] - dy), (c[0] + dx, c[1] + dy), r * 0.42, T.SNOW)
