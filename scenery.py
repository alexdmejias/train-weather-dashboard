"""Seasonal backdrops for the cozy styles. Hot-reloaded like layout.py.

``background()`` returns a full-screen surface for the current ``theme``
style + season. Everything is drawn once (supersampled where it matters) and
cached until the look changes, so it costs nothing per frame on a Pi Zero.

- hearth:  warm gradient, a soft lamp glow behind the clock and a few
           seasonal motifs (leaves, snowflakes, petals, fireflies) drifting
           in the corners.
- almanac: paper gradient with faint motifs.
- window:  an evening landscape — sky, rolling hills, trees and a little
           house with a lit window — that the frosted cards sit over.
"""

from __future__ import annotations

import math
import random

import pygame

import theme as T

_cache: dict = {}


def background() -> pygame.Surface:
    key = T.KEY
    if _cache.get("key") != key:
        _cache.clear()
        _cache["key"] = key
        if T.STYLE == "window":
            _cache["bg"] = _landscape()
        else:
            _cache["bg"] = _plain()
    return _cache["bg"]


# ── hearth / almanac ──────────────────────────────────────────────────────

def _gradient(top, bottom, w=T.W, h=T.H):
    s = pygame.Surface((w, h))
    for y in range(h):
        pygame.draw.line(s, T.mix(top, bottom, y / h), (0, y), (w, y))
    return s


def _plain():
    s = _gradient(T.BG_TOP, T.BG_BOTTOM)
    if T.STYLE == "classic":
        return s
    dark = T.STYLE != "almanac"
    if dark:  # lamplight pooling behind the clock, top-left
        _glow(s, (150, 40), 340, T.GLOW, 30)
    # a few motifs in the margins nothing is drawn over (edges, card gap, tabs strip);
    # the header is left clear because the alert banner can take it over
    rnd = random.Random(T.SEASON)
    spots = [(11, 128), (11, 330), (789, 214), (789, 402), (493, 150), (493, 372),
             (150, 470), (600, 470), (240, 86), (680, 86)]
    alpha = 150 if dark else 120
    for i, (x, y) in enumerate(spots):
        _motif(s, x, y + rnd.randint(-5, 5), rnd.uniform(6, 7.5),
               rnd.uniform(0, math.tau), T.DECOR[i % len(T.DECOR)], alpha)
    return s


# ── window: an evening landscape ──────────────────────────────────────────

SCENES = {
    #          sky top,        sky horizon,     far hills,      near hills,     trees
    "autumn": ((44, 28, 38), (150, 82, 52), (98, 52, 40), (64, 36, 28), ((196, 84, 40), (222, 134, 52), (150, 58, 36))),
    "winter": ((20, 20, 38), (70, 58, 90), (86, 84, 110), (124, 122, 146), ((34, 48, 52), (40, 58, 60))),
    "spring": ((30, 38, 50), (150, 128, 130), (78, 104, 72), (52, 76, 50), ((236, 170, 182), (246, 200, 206), (210, 140, 160))),
    "summer": ((48, 28, 52), (232, 142, 82), (150, 84, 60), (96, 58, 44), ((70, 96, 52), (88, 112, 58))),
}


def _landscape():
    sky_top, horizon, far, near, trees = SCENES[T.SEASON]
    W, H = T.W, T.H
    s = _gradient(sky_top, horizon, W, H)
    rnd = random.Random(T.SEASON)

    # low sun / moon glowing near the horizon
    if T.SEASON in ("winter", "spring"):  # a moon in the gap of the header
        _glow(s, (452, 44), 90, (250, 236, 210), 46)
        pygame.draw.circle(s, (248, 238, 216), (452, 44), 15)
    else:
        _glow(s, (610, 330), 300, T.GLOW, 60)
        pygame.draw.circle(s, T.mix((255, 210, 140), horizon, 0.2), (610, 330), 38)
    if T.SEASON == "winter":  # stars
        for _ in range(60):
            x, y = rnd.randrange(W), rnd.randrange(250)
            c = T.mix(sky_top, (240, 236, 250), rnd.uniform(0.3, 0.8))
            s.set_at((x, y), c)

    k = 2  # supersample the hills + trees
    hs = pygame.Surface((W * k, H * k), pygame.SRCALPHA)
    _hill(hs, far, 300 * k, 26 * k, 0.9, 1.3, k)
    _hill(hs, near, 372 * k, 34 * k, 2.1, 4.0, k)
    # trees along the near ridge
    for i in range(13):
        x = rnd.uniform(-20, W + 20)
        base = _ridge(x * k, 372 * k, 34 * k, 2.1, 4.0, k) / k
        _tree(hs, x, base + 6, rnd.uniform(26, 44), rnd.choice(trees), k)
    # a little house with a lit window on the far hill
    hx = 168
    _house(hs, hx, _ridge(hx * k, 300 * k, 26 * k, 0.9, 1.3, k) / k + 4, k, T.mix(far, (20, 12, 10), 0.45))
    s.blit(pygame.transform.smoothscale(hs, (W, H)), (0, 0))

    # falling things
    for _ in range(26):
        x, y = rnd.uniform(0, W), rnd.uniform(86, H - 30)   # clear of the header and tabs strip
        _motif(s, x, y, rnd.uniform(6, 10), rnd.uniform(0, math.tau), rnd.choice(T.DECOR), 170)
    # gentle vignette so text near the edges stays readable
    shade = pygame.Surface((W, H), pygame.SRCALPHA)
    for i in range(40):
        a = round(70 * (1 - i / 40) ** 2)
        pygame.draw.rect(shade, (0, 0, 0, a), (i, i, W - 2 * i, H - 2 * i), 1)
    for i in range(70):  # and a darker floor under the tabs strip
        pygame.draw.line(shade, (0, 0, 0, round(150 * (i / 70) ** 1.4)), (0, H - 70 + i), (W, H - 70 + i))
    s.blit(shade, (0, 0))
    return s


def _ridge(x, base, amp, f1, f2, k):
    W = T.W * k
    return base - amp * (0.6 * math.sin(x / W * math.pi * f1 + 0.7) + 0.4 * math.sin(x / W * math.pi * f2 + 2.1))


def _hill(s, color, base, amp, f1, f2, k):
    W, H = s.get_size()
    pts = [(x, _ridge(x, base, amp, f1, f2, k)) for x in range(0, W + 8, 8)]
    pygame.draw.polygon(s, color, pts + [(W, H), (0, H)])


def _tree(s, x, base, h, color, k):
    x, base, h = x * k, base * k, h * k
    trunk = T.mix(color, (30, 20, 16), 0.7)
    if T.SEASON == "winter":  # pines with a dusting of snow
        pygame.draw.rect(s, trunk, (x - h * 0.05, base - h * 0.2, h * 0.1, h * 0.25))
        for i, (w, y) in enumerate(((0.55, 0.15), (0.42, 0.42), (0.28, 0.68))):
            top = base - h * (y + 0.38)
            pts = [(x, top), (x + h * w / 2 + h * 0.08, base - h * y), (x - h * w / 2 - h * 0.08, base - h * y)]
            pygame.draw.polygon(s, color, pts)
            pygame.draw.polygon(s, (226, 224, 236), [(x, top), (x + h * 0.08, top + h * 0.12), (x - h * 0.08, top + h * 0.12)])
        return
    pygame.draw.rect(s, trunk, (x - h * 0.05, base - h * 0.5, h * 0.1, h * 0.55))
    r = h * 0.3
    for dx, dy, rr in ((0, -0.62, 1.0), (-0.22, -0.48, 0.75), (0.22, -0.5, 0.75)):
        pygame.draw.circle(s, color, (x + dx * h, base + dy * h), r * rr)


def _house(s, x, base, k, color):
    x, base = x * k, base * k
    w, h = 26 * k, 16 * k
    pygame.draw.rect(s, color, (x - w / 2, base - h, w, h))
    pygame.draw.polygon(s, color, [(x - w / 2 - 3 * k, base - h), (x, base - h - 13 * k), (x + w / 2 + 3 * k, base - h)])
    pygame.draw.rect(s, color, (x + 5 * k, base - h - 12 * k, 4 * k, 8 * k))  # chimney
    lit = (255, 208, 120)
    pygame.draw.rect(s, lit, (x - 8 * k, base - h + 4 * k, 6 * k, 6 * k))
    pygame.draw.rect(s, lit, (x + 3 * k, base - h + 4 * k, 6 * k, 6 * k))


# ── motifs ────────────────────────────────────────────────────────────────

def _motif(s, x, y, size, angle, color, alpha):
    """One seasonal motif: leaf (autumn), snowflake (winter), petal (spring), firefly (summer)."""
    d = round(size * 2.4)
    k = 4
    m = pygame.Surface((d * k, d * k), pygame.SRCALPHA)
    c = d * k / 2
    r = size * k
    col = (*color, 255)
    if T.SEASON == "autumn":
        pts = []
        for i in range(24):
            t = i / 24 * math.tau
            w = 0.48 + 0.12 * math.cos(t * 5)  # gently lobed oval
            pts.append((c + math.cos(t) * r, c + math.sin(t) * r * w))
        pygame.draw.polygon(m, col, pts)
        pygame.draw.line(m, (*T.mix(color, (40, 20, 10), 0.4), 255), (c - r * 1.1, c), (c + r * 0.8, c), k)
    elif T.SEASON == "winter":
        for i in range(3):
            a = i * math.pi / 3
            dx, dy = math.cos(a) * r * 0.8, math.sin(a) * r * 0.8
            pygame.draw.line(m, col, (c - dx, c - dy), (c + dx, c + dy), round(k * 1.4))
        pygame.draw.circle(m, col, (c, c), r * 0.18)
    elif T.SEASON == "spring":
        for i in range(5):
            a = i * math.tau / 5
            pygame.draw.circle(m, col, (c + math.cos(a) * r * 0.42, c + math.sin(a) * r * 0.42), r * 0.34)
        pygame.draw.circle(m, (*T.mix(color, (255, 236, 160), 0.7), 255), (c, c), r * 0.18)
    else:
        steps = 10
        for i in range(steps, 0, -1):
            a = round(120 * (1 - i / steps) ** 1.5)
            pygame.draw.circle(m, (*color, a), (c, c), r * i / steps)
        pygame.draw.circle(m, (255, 246, 200, 255), (c, c), r * 0.16)
    m = pygame.transform.rotate(pygame.transform.smoothscale(m, (d, d)), math.degrees(angle))
    m.set_alpha(alpha)
    s.blit(m, m.get_rect(center=(round(x), round(y))))


def _glow(s, center, radius, color, strength):
    g = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
    steps = 32
    for i in range(steps, 0, -1):
        a = round(strength * (1 - i / steps) ** 1.8)
        pygame.draw.circle(g, (*color, a), (radius, radius), round(radius * i / steps))
    s.blit(g, (center[0] - radius, center[1] - radius))
