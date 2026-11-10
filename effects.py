"""Little moments of delight drawn over the dashboard. Hot-reloaded.

The still dashboard is drawn once into a cached frame; while an effect is
running, the main loop copies that frame and draws moving particles on top
about 24 times a second (fine on a Raspberry Pi 3; a Pi Zero should leave
``[effects] mode`` on "off"). With no effect running the loop goes back to
redrawing only when something changes.

What plays is decided from data the dashboard already has:

- weather   rain (with splashes), drizzle, snow (settling on the cards), fog,
            thunder flashes, wind (gusts push everything sideways, wisps fly by)
- seasons   falling leaves (autumn), blossom petals (spring), fireflies on
            summer nights, the odd shooting star on clear nights
- holidays  Christmas lights + snow flurries (December), bats (Halloween week),
            fireworks (New Year's midnight, 4th of July night), hearts
            (Valentine's), plus confetti and a message on your own dates

``plan(state)`` → {effect: intensity}; ``step(surface, state, dt)`` animates;
``preview(name)`` forces one for a few seconds (from the settings page).
"""

from __future__ import annotations

import math
import random
import time
from datetime import date, datetime, timedelta

import pygame

import icons
import layout
import theme as T

FPS = 24
PREVIEWS = ["rain", "snow", "wind", "leaves", "petals", "fireflies", "fog", "thunder",
            "christmas", "halloween", "fireworks", "hearts", "confetti"]

_S: dict = {"layers": {}, "forced": None, "plan": ({}, None), "msg": None, "snow_depth": 0.0}
_spr: dict = {}
rnd = random.Random()


# ── what to play ──────────────────────────────────────────────────────────

def plan(state) -> dict:
    """{effect name: intensity 0–1} for right now."""
    mode = getattr(state, "effects", "on")
    forced = _S["forced"]
    if forced and time.monotonic() < forced[1]:
        return _expand(forced[0])
    _S["forced"] = None
    if mode == "off":
        return {}
    now = state.now
    key = (now.strftime("%Y%m%d%H%M"), id(state.weather), mode, state.style, state.season)
    if _S["plan"][1] == key:
        return _S["plan"][0]

    out: dict = {}
    w = state.weather
    if w:
        k = icons.kind(w.code, w.is_day)
        if k in ("rain", "drizzle", "thunder"):
            out["rain"] = {"drizzle": 0.45, "rain": 0.9, "thunder": 1.0}[k] if w.code not in (61, 80) else 0.6
        if k == "thunder":
            out["thunder"] = 1.0
        if k == "snow":
            out["snow"] = 0.6 if w.code in (71, 77, 85) else 1.0
        if k == "fog":
            out["fog"] = 1.0
        mph = w.wind / 1.609 if "km" in getattr(w, "wind_unit", "mph") else w.wind
        if mph >= 14:
            out["wind"] = min(1.0, (mph - 10) / 20)
        season = T.season_for(now, getattr(state, "season", "auto"))
        wet = any(x in out for x in ("rain", "snow"))
        if season == "autumn" and not out.get("rain", 0) > 0.7:
            out["leaves"] = 0.7 if "wind" in out else 0.45
        if season == "spring" and not wet:
            out["petals"] = 0.5
        if season == "summer" and not w.is_day and not wet:
            out["fireflies"] = 1.0
        if k in ("clear-night", "partly-night"):
            out["shooting_star"] = 1.0
    if getattr(state, "holidays", True):
        for name, val in holidays(now, w).items():
            out[name] = max(out.get(name, 0), val)
    dates = getattr(state, "special_dates", {})
    msg = special_message(now, dates, getattr(state, "holidays", True))
    if msg and now.hour >= 7 and _own_date(now, dates):     # confetti is for your own days
        out["confetti"] = max(out.get("confetti", 0), 0.35)
    _S["msg"] = msg
    if mode == "subtle":
        out = {k: v * 0.45 for k, v in out.items() if k not in ("thunder",)}
    _S["plan"] = (out, key)
    return out


def _expand(name):
    return {"thunder": {"rain": 1.0, "thunder": 1.0, "wind": 0.5},
            "christmas": {"christmas": 1.0, "snow": 0.5},
            "halloween": {"bats": 1.0, "leaves": 0.4},
            "wind": {"wind": 1.0, "leaves": 0.6},
            "fireworks": {"fireworks": 1.0, "confetti": 0.4}}.get(name, {name: 1.0})


def holidays(now: datetime, w=None) -> dict:
    d, m, h = now.day, now.month, now.hour
    dark = (w is not None and not w.is_day) or h >= 17 or h < 7
    out = {}
    if m == 12 and d <= 26:
        out["christmas"] = 1.0
        if not (w and icons.kind(w.code) == "snow"):
            out["snow"] = 0.55 if d in (24, 25) else 0.3      # a few flurries, whatever the weather
    if m == 10 and d >= 24 and dark:
        out["bats"] = 1.0 if d == 31 else 0.6
    if (m == 12 and d == 31 and (h, now.minute) >= (23, 55)) or (m == 1 and d == 1 and h == 0):
        out["fireworks"], out["confetti"] = 1.0, 0.8
    if m == 7 and d == 4 and (h >= 21 or (h == 20 and now.minute >= 30)):
        out["fireworks"] = 0.8
    if m == 2 and d == 14:
        out["hearts"] = 0.8
    return out


def _own_date(now, dates) -> bool:
    return any(k in (dates or {}) for k in (now.strftime("%m-%d"), now.strftime("%Y-%m-%d")))


def special_message(now: datetime, dates: dict, builtin=True) -> str | None:
    """A greeting for today: your own dates ([effects] dates) win over holidays."""
    for k in (now.strftime("%m-%d"), now.strftime("%Y-%m-%d")):
        if k in (dates or {}):
            return str(dates[k])
    if not builtin:
        return None
    md = (now.month, now.day)
    fixed = {(12, 25): "Merry Christmas!", (12, 24): "Happy Christmas Eve", (1, 1): "Happy New Year!",
             (10, 31): "Happy Halloween!", (2, 14): "Happy Valentine's Day", (7, 4): "Happy Fourth of July!",
             (12, 31): "Happy New Year's Eve"}
    if md in fixed:
        return fixed[md]
    if now.month == 11 and now.weekday() == 3 and 22 <= now.day <= 28:
        return "Happy Thanksgiving!"
    return None


def preview(name: str, seconds: float = 20):
    _S["forced"] = (name, time.monotonic() + seconds)
    _S["plan"] = ({}, None)


def running(state) -> bool:
    return bool(plan(state)) or bool(_S["layers"]) or _show_message(state)


# ── animation ─────────────────────────────────────────────────────────────

def step(surf: pygame.Surface, state, dt: float):
    if _spr.get("key") != T.KEY:
        _spr.clear()
        _spr["key"] = T.KEY
    want = plan(state)
    layers = _S["layers"]
    for name, val in want.items():
        if name not in layers and name in LAYERS:
            layers[name] = LAYERS[name]()
        if name in layers:
            layers[name].target = val
    for name, layer in list(layers.items()):
        if name not in want:
            layer.target = 0.0
    dt = min(dt, 0.1)
    t = time.monotonic()
    env = _env(state, want, t)
    for name in ORDER:
        layer = layers.get(name)
        if not layer:
            continue
        layer.level += (layer.target - layer.level) * min(1.0, dt * 0.8)
        layer.update(dt, env)
        layer.draw(surf, env)
        if layer.target == 0 and layer.done():
            del layers[name]
    _snow_cap(surf, env, dt, "snow" in want)
    if _show_message(state):
        _message(surf, _S["msg"])


def _env(state, want, t):
    w = want.get("wind", 0)
    gust = 0.55 + 0.45 * math.sin(t * 0.37) * math.sin(t * 0.11 + 1.3)
    wind = (14 + 260 * w * (0.4 + 0.9 * gust)) if w else 10 * math.sin(t * 0.2)
    return {"wind": wind, "t": t, "cards": list(layout.CARD_RECTS), "W": T.W, "H": T.H,
            "dark": T.STYLE != "almanac"}


def _show_message(state) -> bool:
    msg = _S.get("msg")
    if not msg or getattr(state, "effects", "on") == "off":
        return False
    return (time.time() % 180) < 9          # every 3 minutes, for 9 seconds


def _message(surf, msg):
    f = T.font("heading", 18)
    txt = f.render(msg, True, T.TEXT)
    w, h = txt.get_width() + 44, 42
    r = pygame.Rect((T.W - w) // 2, T.H - 80, w, h)
    key = ("msg", msg, T.KEY)
    if key not in _spr:
        s = pygame.Surface((w + 16, h + 16), pygame.SRCALPHA)
        pygame.draw.rect(s, (0, 0, 0, 70), (8, 11, w, h), border_radius=h // 2)
        pill = layout._panel(w, h, h // 2, T.mix(T.CARD_HI, T.ACCENT, 0.18), T.ACCENT)
        s.blit(pill, (8, 8))
        s.blit(txt, txt.get_rect(center=(8 + w // 2, 8 + h // 2)))
        _spr[key] = s
    surf.blit(_spr[key], (r.x - 8, r.y - 8))


# ── layers ────────────────────────────────────────────────────────────────

class P:
    __slots__ = ("x", "y", "vx", "vy", "a", "va", "s", "life", "age", "c", "ph", "floor")

    def __init__(self, **kw):
        self.a = self.va = self.ph = self.age = 0.0
        self.life = 1e9
        self.c = 0
        self.floor = None
        for k, v in kw.items():
            setattr(self, k, v)


class Layer:
    def __init__(self):
        self.parts: list[P] = []
        self.level = 0.0
        self.target = 0.0
        self.acc = 0.0

    def done(self):
        return not self.parts

    def spawn_n(self, dt, per_sec):
        """How many to spawn this frame for a steady rate of ``per_sec``."""
        self.acc += per_sec * dt * (self.level if self.target else 0)
        n = int(self.acc)
        self.acc -= n
        return n

    def update(self, dt, env):
        pass

    def draw(self, surf, env):
        pass


def _off(p, env, margin=40):
    return p.y > env["H"] + margin or p.x < -margin * 3 or p.x > env["W"] + margin * 3 or p.age > p.life


class Rain(Layer):
    def update(self, dt, env):
        for _ in range(self.spawn_n(dt, 150)):
            speed = rnd.uniform(560, 760)
            floor = env["H"] - rnd.uniform(0, 12)
            if env["cards"] and rnd.random() < 0.35:   # some land on top of a card
                c = rnd.choice(env["cards"])
                x = rnd.uniform(c.left + 10, c.right - 10)
                floor = c.top
            else:
                x = rnd.uniform(-60, env["W"] + 60)
            self.parts.append(P(x=x - env["wind"] * 0.5, y=rnd.uniform(-60, -10), vx=0, vy=speed,
                                s=rnd.choice((0, 1, 1, 2)), floor=floor))
        keep = []
        for p in self.parts:
            if p.life < 1e9:                      # a splash
                p.age += dt
                if p.age < p.life:
                    keep.append(p)
                continue
            p.vx = env["wind"] * 0.9
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.y >= p.floor:
                keep.append(P(x=p.x, y=p.floor, vx=0, vy=0, s=0, life=0.18))
            elif not _off(p, env):
                keep.append(p)
        self.parts = keep

    def draw(self, surf, env):
        ang = round(math.degrees(math.atan2(env["wind"] * 0.9, 650)) / 4) * 4
        for p in self.parts:
            if p.life < 1e9:
                sp = _splash()
                surf.blit(sp, (p.x - sp.get_width() / 2, p.y - sp.get_height() + 1))
            else:
                d = _drop(ang, p.s)
                surf.blit(d, (p.x - d.get_width() / 2, p.y - d.get_height()))


class Snow(Layer):
    def update(self, dt, env):
        for _ in range(self.spawn_n(dt, 34)):
            self.parts.append(P(x=rnd.uniform(-80, env["W"] + 80), y=rnd.uniform(-20, -4), vx=0,
                                vy=rnd.uniform(26, 62), s=rnd.choice((1, 2, 2, 3, 3, 4)),
                                ph=rnd.uniform(0, 6.3)))
        for p in self.parts:
            p.ph += dt
            p.x += (env["wind"] * (0.5 + p.s * 0.12) + math.sin(p.ph * 1.3) * 16) * dt
            p.y += p.vy * (0.7 + p.s * 0.1) * dt
        self.parts = [p for p in self.parts if not _off(p, env)]

    def draw(self, surf, env):
        for p in self.parts:
            f = _flake(p.s)
            surf.blit(f, (p.x - f.get_width() / 2, p.y - f.get_height() / 2))


class Leaves(Layer):
    kind = "leaf"
    rate = 1.6

    def update(self, dt, env):
        windy = env["wind"] > 60
        for _ in range(self.spawn_n(dt, self.rate * (2.2 if windy else 1))):
            if windy and rnd.random() < 0.6:    # blown in from the side
                x, y = (-30, rnd.uniform(0, env["H"] * 0.7)) if env["wind"] > 0 else (env["W"] + 30, rnd.uniform(0, env["H"] * 0.7))
            else:
                x, y = rnd.uniform(-40, env["W"] + 40), -24
            self.parts.append(P(x=x, y=y, vx=0, vy=rnd.uniform(34, 62), a=rnd.uniform(0, 360),
                                va=rnd.uniform(-160, 160), s=rnd.choice((0, 1, 2)), c=rnd.randrange(4),
                                ph=rnd.uniform(0, 6.3)))
        for p in self.parts:
            p.ph += dt
            flutter = math.sin(p.ph * 2.1)
            p.x += (env["wind"] * 0.95 + flutter * 34) * dt
            p.y += (p.vy + math.cos(p.ph * 2.1) * 18) * dt
            p.a += (p.va + flutter * 60) * dt
        self.parts = [p for p in self.parts if not _off(p, env)]

    def draw(self, surf, env):
        for p in self.parts:
            img = _leaf(self.kind, p.c, p.s, int(p.a % 360) // 15)
            surf.blit(img, (p.x - img.get_width() / 2, p.y - img.get_height() / 2))


class Petals(Leaves):
    kind = "petal"
    rate = 2.2


class Fireflies(Layer):
    def update(self, dt, env):
        want = round(14 * self.level) if self.target else 0
        while len(self.parts) < want:
            self.parts.append(P(x=rnd.uniform(20, env["W"] - 20), y=rnd.uniform(env["H"] * 0.25, env["H"] - 20),
                                vx=rnd.uniform(-12, 12), vy=rnd.uniform(-8, 8), ph=rnd.uniform(0, 6.3),
                                s=rnd.uniform(0.6, 1.4)))
        if len(self.parts) > want:
            self.parts.pop()
        for p in self.parts:
            p.ph += dt * p.s
            p.vx += rnd.uniform(-20, 20) * dt
            p.vy += rnd.uniform(-20, 20) * dt
            p.vx, p.vy = max(-16, min(16, p.vx)), max(-12, min(12, p.vy))
            p.x = (p.x + (p.vx + env["wind"] * 0.2) * dt) % env["W"]
            p.y = min(env["H"] - 8, max(60, p.y + p.vy * dt))

    def draw(self, surf, env):
        for p in self.parts:
            b = max(0.0, math.sin(p.ph * 1.7)) ** 2
            g = _glow((214, 236, 120), 9, int(b * 7))
            surf.blit(g, (p.x - g.get_width() / 2, p.y - g.get_height() / 2))


class Wind(Layer):
    def update(self, dt, env):
        for _ in range(self.spawn_n(dt, 1.4)):
            left = env["wind"] >= 0
            self.parts.append(P(x=-160 if left else env["W"] + 160, y=rnd.uniform(70, env["H"] - 40),
                                vx=(1 if left else -1) * rnd.uniform(420, 620), vy=rnd.uniform(-10, 10),
                                life=3.0, s=rnd.randrange(3)))
        for p in self.parts:
            p.age += dt
            p.x += p.vx * dt
            p.y += p.vy * dt
        self.parts = [p for p in self.parts if -260 < p.x < env["W"] + 260 and p.age < p.life]

    def draw(self, surf, env):
        for p in self.parts:
            img = _wisp(p.s, p.vx < 0)
            surf.blit(img, (p.x - img.get_width() / 2, p.y))


class Fog(Layer):
    def update(self, dt, env):
        while len(self.parts) < 5 and self.target:
            self.parts.append(P(x=rnd.uniform(-300, env["W"]), y=rnd.uniform(60, env["H"] - 60),
                                vx=rnd.uniform(8, 18), vy=0, s=rnd.randrange(2)))
        for p in self.parts:
            p.x += (p.vx + env["wind"] * 0.3) * dt
            if p.x > env["W"] + 260:
                p.x = -560
        if not self.target and self.level < 0.05:
            self.parts = []

    def draw(self, surf, env):
        a = round(self.level * 5)
        for p in self.parts:
            img = _fog(p.s, a)
            if img:
                surf.blit(img, (p.x - img.get_width() / 2, p.y - img.get_height() / 2))


class Thunder(Layer):
    def __init__(self):
        super().__init__()
        self.next = time.monotonic() + rnd.uniform(4, 10)
        self.flash = []      # remaining (start, length, strength)

    def done(self):
        return not self.flash

    def update(self, dt, env):
        t = env["t"]
        if self.target and t >= self.next:
            self.flash = [(t, 0.07, 46), (t + 0.16, 0.05, 30), (t + 0.32, 0.12, 60)][: rnd.choice((2, 3))]
            self.next = t + rnd.uniform(18, 50)
        self.flash = [f for f in self.flash if t < f[0] + f[1]]

    def draw(self, surf, env):
        t = env["t"]
        for start, length, k in self.flash:
            if start <= t:
                surf.fill((k, k, k - 6), special_flags=pygame.BLEND_RGB_ADD)


class ShootingStar(Layer):
    def __init__(self):
        super().__init__()
        self.next = time.monotonic() + rnd.uniform(8, 40)

    def done(self):
        return not self.parts

    def update(self, dt, env):
        t = env["t"]
        if self.target and t >= self.next:
            self.parts.append(P(x=rnd.uniform(120, env["W"] - 260), y=rnd.uniform(4, 40), vx=520, vy=150,
                                life=0.9))
            self.next = t + rnd.uniform(90, 240)
        for p in self.parts:
            p.age += dt
            p.x += p.vx * dt
            p.y += p.vy * dt
        self.parts = [p for p in self.parts if p.age < p.life]

    def draw(self, surf, env):
        for p in self.parts:
            k = math.sin(math.pi * p.age / p.life)
            img = _streak()
            img.set_alpha(round(255 * k))
            surf.blit(img, (p.x - img.get_width(), p.y - img.get_height()))


class Bats(Layer):
    def __init__(self):
        super().__init__()
        self.acc = 0.95          # the first little colony shows up right away

    def update(self, dt, env):
        for _ in range(self.spawn_n(dt, 0.3)):
            left = rnd.random() < 0.5
            y = rnd.uniform(30, env["H"] * 0.55)
            for i in range(rnd.choice((1, 2, 3, 4))):
                self.parts.append(P(x=(-30 - i * 40) if left else env["W"] + 30 + i * 40, y=y + rnd.uniform(-24, 24),
                                    vx=(1 if left else -1) * rnd.uniform(110, 170), vy=0,
                                    ph=rnd.uniform(0, 6.3), s=rnd.choice((0, 1))))
        for p in self.parts:
            p.ph += dt
            p.x += p.vx * dt
            p.y += math.sin(p.ph * 3) * 26 * dt
        self.parts = [p for p in self.parts if -200 < p.x < env["W"] + 200]

    def draw(self, surf, env):
        for p in self.parts:
            img = _bat(p.s, int(p.ph * 9) % 2)
            surf.blit(img, (p.x - img.get_width() / 2, p.y - img.get_height() / 2))


SPARK_COLORS = [(255, 214, 110), (255, 110, 90), (130, 220, 120), (120, 180, 255), (255, 150, 220), (255, 255, 230)]


class Fireworks(Layer):
    def __init__(self):
        super().__init__()
        self.next = 0.0

    def update(self, dt, env):
        t = env["t"]
        if self.target and t >= self.next:
            self.parts.append(P(x=rnd.uniform(80, env["W"] - 80), y=env["H"] + 4, vx=rnd.uniform(-30, 30),
                                vy=-rnd.uniform(400, 470), life=rnd.uniform(1.0, 1.3), c=rnd.randrange(len(SPARK_COLORS)),
                                s=-1))
            self.next = t + rnd.uniform(0.7, 1.8) / max(0.3, self.level)
        new = []
        for p in self.parts:
            p.age += dt
            if p.s == -1:            # rocket
                p.vy += 120 * dt
                p.x += p.vx * dt
                p.y += p.vy * dt
                if p.age >= p.life:
                    n = 56
                    for i in range(n):
                        ang = i / n * math.tau + rnd.uniform(-0.05, 0.05)
                        sp = rnd.uniform(90, 150)
                        new.append(P(x=p.x, y=p.y, vx=math.cos(ang) * sp, vy=math.sin(ang) * sp,
                                     life=rnd.uniform(1.2, 1.8), c=p.c if rnd.random() < 0.85 else 5, s=1))
                    continue
            else:
                p.vx *= 1 - 1.2 * dt
                p.vy = p.vy * (1 - 1.2 * dt) + 70 * dt
                p.x += p.vx * dt
                p.y += p.vy * dt
                if p.age >= p.life:
                    continue
            new.append(p)
        self.parts = new

    def draw(self, surf, env):
        for p in self.parts:
            if p.s == -1:
                g = _glow((255, 236, 200), 3, 6)
            else:
                fade = 1 - p.age / p.life
                if fade < 0.35 and int(p.age * 20) % 3 == 0:   # crackle as they die
                    continue
                lv = max(1, round(fade * 7))
                for back, dim in ((0.09, 3), (0.045, 1)):      # a short fading trail
                    t = _glow(SPARK_COLORS[p.c], 4, max(1, lv - dim))
                    surf.blit(t, (p.x - p.vx * back - t.get_width() / 2, p.y - p.vy * back - t.get_height() / 2))
                g = _glow(SPARK_COLORS[p.c], 6, lv)
            surf.blit(g, (p.x - g.get_width() / 2, p.y - g.get_height() / 2))


class Hearts(Layer):
    def update(self, dt, env):
        for _ in range(self.spawn_n(dt, 1.4)):
            self.parts.append(P(x=rnd.uniform(20, env["W"] - 20), y=env["H"] + 20, vx=0, vy=-rnd.uniform(26, 44),
                                ph=rnd.uniform(0, 6.3), s=rnd.choice((0, 1, 2)), c=rnd.randrange(3)))
        for p in self.parts:
            p.ph += dt
            p.x += (math.sin(p.ph * 1.5) * 22 + env["wind"] * 0.3) * dt
            p.y += p.vy * dt
        self.parts = [p for p in self.parts if p.y > -30]

    def draw(self, surf, env):
        for p in self.parts:
            img = _heart(p.s, p.c)
            surf.blit(img, (p.x - img.get_width() / 2, p.y - img.get_height() / 2))


CONFETTI = [(240, 90, 80), (255, 196, 70), (110, 200, 140), (110, 160, 250), (240, 130, 200), (250, 240, 220)]


class Confetti(Layer):
    def update(self, dt, env):
        for _ in range(self.spawn_n(dt, 40)):
            self.parts.append(P(x=rnd.uniform(-20, env["W"] + 20), y=-10, vx=rnd.uniform(-30, 30),
                                vy=rnd.uniform(60, 110), ph=rnd.uniform(0, 6.3), va=rnd.uniform(4, 9),
                                c=rnd.randrange(len(CONFETTI)), s=rnd.choice((4, 5, 6))))
        for p in self.parts:
            p.ph += p.va * dt
            p.x += (p.vx + env["wind"] * 0.6 + math.sin(p.ph * 0.5) * 20) * dt
            p.y += p.vy * dt
        self.parts = [p for p in self.parts if not _off(p, env)]

    def draw(self, surf, env):
        for p in self.parts:
            h = max(1, round(abs(math.cos(p.ph)) * p.s * 1.6))
            col = CONFETTI[p.c] if math.cos(p.ph) > 0 else T.mix(CONFETTI[p.c], (0, 0, 0), 0.25)
            surf.fill(col, (round(p.x), round(p.y), p.s, h))


BULBS = [(255, 84, 70), (90, 210, 110), (255, 200, 80), (90, 160, 255), (255, 140, 200)]


class Christmas(Layer):
    """String lights along the top of each card, twinkling."""

    def done(self):
        return self.level < 0.03

    def draw(self, surf, env):
        if self.level < 0.03:
            return
        t = env["t"]
        for r in env["cards"]:
            wire, bulbs = _string(r)
            surf.blit(wire, (r.x, r.y - 4))
            for i, (bx, by) in enumerate(bulbs):
                ph = (math.sin(t * (1.1 + (i * 7 % 5) * 0.23) + i * 1.7) + 1) / 2
                level = round((0.35 + 0.65 * ph) * self.level * 7)
                col = BULBS[i % len(BULBS)]
                g = _glow(col, 9, max(1, level))
                surf.blit(g, (r.x + bx - g.get_width() / 2, r.y + by - g.get_height() / 2))
                b = _bulb(col)
                surf.blit(b, (r.x + bx - b.get_width() / 2, r.y + by - 3))


LAYERS = {"fog": Fog, "fireflies": Fireflies, "shooting_star": ShootingStar, "wind": Wind,
          "leaves": Leaves, "petals": Petals, "snow": Snow, "rain": Rain, "bats": Bats,
          "fireworks": Fireworks, "hearts": Hearts, "confetti": Confetti, "christmas": Christmas,
          "thunder": Thunder}
ORDER = ["fog", "shooting_star", "fireworks", "fireflies", "wind", "bats", "christmas", "leaves", "petals",
         "hearts", "snow", "rain", "confetti", "thunder"]


def _snow_cap(surf, env, dt, snowing):
    """Snow slowly settles on top of the cards while it snows, and melts after."""
    d = _S["snow_depth"]
    d = min(7.0, d + dt / 25) if snowing else max(0.0, d - dt / 10)
    _S["snow_depth"] = d
    if d < 0.5:
        return
    for r in env["cards"]:
        img = _cap(r.w, int(d))
        surf.blit(img, (r.x, r.y - img.get_height() + 3))


# ── sprites (drawn once, cached until the palette changes) ────────────────

def _ss(w, h, k=4):
    return pygame.Surface((w * k, h * k), pygame.SRCALPHA), k


def _cached(key, make):
    if key not in _spr:
        _spr[key] = make()
    return _spr[key]


def _drop(angle, size):
    def make():
        ln = 16 + size * 5
        dx = math.tan(math.radians(angle)) * ln
        w = int(abs(dx)) + 6
        s, k = _ss(w, ln + 2)
        x0 = 3 + (abs(dx) if dx < 0 else 0)
        col = (*T.mix(T.RAIN, (255, 255, 255), 0.35), 150 + size * 30)
        pygame.draw.line(s, col, (x0 * k, 1 * k), ((x0 + dx) * k, (ln + 1) * k), max(2, round(k * (1 + size * 0.3))))
        return pygame.transform.smoothscale(s, (w, ln + 2))
    return _cached(("drop", angle, size), make)


def _splash():
    def make():
        s, k = _ss(12, 6)
        col = (*T.mix(T.RAIN, (255, 255, 255), 0.35), 170)
        pygame.draw.arc(s, col, (1 * k, 2 * k, 10 * k, 8 * k), math.radians(25), math.radians(155), k)
        return pygame.transform.smoothscale(s, (12, 6))
    return _cached(("splash",), make)


def _flake(size):
    def make():
        d = size * 2 + 6
        s, k = _ss(d, d)
        c = d * k / 2
        snow = T.SNOW if T.STYLE != "almanac" else (255, 255, 255)
        pygame.draw.circle(s, (*snow, 60), (c, c), (size + 2) * k)
        pygame.draw.circle(s, (*snow, 235), (c, c), size * k * 0.8)
        return pygame.transform.smoothscale(s, (d, d))
    return _cached(("flake", size), make)


LEAF_COLORS = [(214, 104, 48), (232, 156, 64), (176, 74, 44), (196, 138, 60)]
PETAL_COLORS = [(244, 178, 186), (250, 210, 214), (236, 150, 170), (255, 236, 240)]


def _leaf(kind, color, size, rot):
    def make():
        r = (9 + size * 2) if kind == "leaf" else (5 + size)
        d = r * 2 + 4
        s, k = _ss(d, d)
        c, rr = d * k / 2, r * k
        if kind == "leaf":
            col = LEAF_COLORS[color]
            pts = []
            for i in range(28):
                a = i / 28 * math.tau
                w = 0.5 + 0.12 * math.cos(a * 5)
                pts.append((c + math.cos(a) * rr, c + math.sin(a) * rr * w))
            pygame.draw.polygon(s, col, pts)
            pygame.draw.line(s, T.mix(col, (60, 30, 12), 0.45), (c - rr * 1.15, c), (c + rr * 0.8, c), k)
        else:
            col = PETAL_COLORS[color]
            pygame.draw.ellipse(s, col, (c - rr, c - rr * 0.62, rr * 2, rr * 1.24))
            pygame.draw.ellipse(s, T.mix(col, (255, 255, 255), 0.5), (c - rr * 0.6, c - rr * 0.25, rr * 0.9, rr * 0.5))
        base = pygame.transform.smoothscale(s, (d, d))
        return [pygame.transform.rotate(base, i * 15) for i in range(24)]
    return _cached(("leaf", kind, color, size), make)[rot]


def _glow(color, radius, level):
    """Soft dot; ``level`` 1–7 is brightness (pre-rendered so nothing is computed per frame)."""
    def make():
        d = radius * 2 + 2
        out = []
        for lv in range(8):
            s = pygame.Surface((d, d), pygame.SRCALPHA)
            for i in range(radius, 0, -1):
                a = round(255 * (lv / 7) * (1 - i / radius) ** 1.6)
                pygame.draw.circle(s, (*color, a), (d // 2, d // 2), i)
            if lv:
                pygame.draw.circle(s, (*T.mix(color, (255, 255, 255), 0.6), round(255 * lv / 7)), (d // 2, d // 2),
                                   max(1, radius // 4))
            out.append(s)
        return out
    return _cached(("glow", color, radius), make)[max(0, min(7, level))]


def _wisp(variant, flip):
    def make():
        w, h = 200, 26
        s, k = _ss(w, h, 3)
        col = T.TEXT if T.STYLE != "almanac" else T.MUTED
        amp, f = (4, 2.2), (1.0, 1.6, 2.3)[variant]
        pts = [(x * k, (h / 2 + math.sin(x / w * math.pi * f) * amp[0] * (x / w)) * k) for x in range(0, w, 4)]
        for i in range(len(pts) - 1):
            a = round(70 * math.sin(math.pi * i / (len(pts) - 1)))
            pygame.draw.line(s, (*col, a), pts[i], pts[i + 1], 2 * k // 2 + 1)
        img = pygame.transform.smoothscale(s, (w, h))
        return [img, pygame.transform.flip(img, True, False)]
    return _cached(("wisp", variant), make)[1 if flip else 0]


def _fog(variant, level):
    if level <= 0:
        return None

    def make():
        w, h = (520, 120) if variant == 0 else (420, 90)
        out = [None]
        col = T.mix(T.CLOUD_BACK, T.TEXT, 0.3)
        for lv in range(1, 6):
            s = pygame.Surface((w, h), pygame.SRCALPHA)
            for i in range(24, 0, -1):
                a = round(lv * 9 * (1 - i / 24) ** 1.3)
                rw, rh = w * i / 24, h * i / 24
                pygame.draw.ellipse(s, (*col, a), ((w - rw) / 2, (h - rh) / 2, rw, rh))
            out.append(s)
        return out
    return _cached(("fog", variant), make)[min(5, level)]


def _streak():
    def make():
        w, h = 130, 38
        s, k = _ss(w, h, 3)
        steps = 40
        for i in range(steps):
            f = i / steps
            x, y = f * (w - 4), f * (h - 4)
            pygame.draw.circle(s, (255, 250, 236, round(230 * f ** 2)), ((x + 2) * k, (y + 2) * k), max(1, f * 1.8 * k))
        return pygame.transform.smoothscale(s, (w, h))
    return _cached(("streak",), make).copy()


def _bat(size, frame):
    def make():
        w, h = (38, 19) if size == 0 else (50, 25)
        col = T.mix(T.BG_TOP, T.TEXT, 0.5 if T.STYLE != "almanac" else 0.85)
        frames = []
        for up in (0, 1):
            s, k = _ss(w, h)
            cx, cy = w * k / 2, h * k / 2
            wy = -h * k * 0.35 if up else h * k * 0.25
            for sign in (-1, 1):
                pts = [(cx, cy), (cx + sign * w * k * 0.5, cy + wy), (cx + sign * w * k * 0.36, cy + wy * 0.2 + h * k * 0.12),
                       (cx + sign * w * k * 0.22, cy + h * k * 0.2), (cx + sign * w * k * 0.1, cy + h * k * 0.12)]
                pygame.draw.polygon(s, col, pts)
            pygame.draw.ellipse(s, col, (cx - w * k * 0.07, cy - h * k * 0.25, w * k * 0.14, h * k * 0.55))
            frames.append(pygame.transform.smoothscale(s, (w, h)))
        return frames
    return _cached(("bat", size), make)[frame]


def _heart(size, color):
    def make():
        d = 12 + size * 4
        s, k = _ss(d, d)
        col = [(236, 96, 110), (250, 150, 170), (214, 70, 90)][color]
        r = d * k * 0.27
        pygame.draw.circle(s, col, (d * k * 0.3, d * k * 0.36), r)
        pygame.draw.circle(s, col, (d * k * 0.7, d * k * 0.36), r)
        pygame.draw.polygon(s, col, [(d * k * 0.05, d * k * 0.44), (d * k * 0.95, d * k * 0.44), (d * k * 0.5, d * k * 0.92)])
        img = pygame.transform.smoothscale(s, (d, d))
        img.set_alpha(210)
        return img
    return _cached(("heart", size, color), make)


def _bulb(color):
    def make():
        s, k = _ss(6, 9)
        pygame.draw.rect(s, (70, 74, 60), (1.5 * k, 0, 3 * k, 2.5 * k))
        pygame.draw.ellipse(s, color, (0, 2 * k, 6 * k, 7 * k))
        pygame.draw.ellipse(s, T.mix(color, (255, 255, 255), 0.6), (1.5 * k, 3 * k, 1.6 * k, 2.6 * k))
        return pygame.transform.smoothscale(s, (6, 9))
    return _cached(("bulb", color), make)


def _string(r):
    """Wire surface + bulb positions for lights draped along the top of rect ``r``."""
    def make():
        span = 34
        n = max(2, round((r.w - 40) / span))
        xs = [20 + i * (r.w - 40) / n for i in range(n + 1)]
        s, k = _ss(r.w, 20, 2)
        wire = (46, 70, 44) if T.STYLE != "almanac" else (70, 96, 64)
        bulbs = []
        for a, b in zip(xs, xs[1:]):
            pts = []
            for j in range(13):
                f = j / 12
                pts.append(((a + (b - a) * f) * k, (4 + 9 * 4 * f * (1 - f)) * k))
            pygame.draw.lines(s, wire, False, pts, 2 * k // 2 + 1)
            bulbs.append(((a + b) / 2, 4 + 9 - 4 + 3))
        return pygame.transform.smoothscale(s, (r.w, 20)), bulbs
    return _cached(("string", r.w, r.h), make)


def _cap(width, depth):
    def make():
        h = depth + 6
        s, k = _ss(width, h, 2)
        white = (250, 250, 252)
        shade = T.mix(white, (150, 160, 190), 0.35)
        rr = random.Random(width)
        pygame.draw.rect(s, shade, (10 * k, (h - 4) * k, (width - 20) * k, 4 * k), border_radius=2 * k)
        x = 14
        while x < width - 14:
            rad = depth * rr.uniform(0.7, 1.15) + 2
            pygame.draw.circle(s, white, (x * k, (h - 3) * k), rad * k)
            x += rr.uniform(6, 12)
        pygame.draw.rect(s, white, (12 * k, (h - 5) * k, (width - 24) * k, 4 * k))
        return pygame.transform.smoothscale(s, (width, h))
    return _cached(("cap", width, depth), make)
