"""Everything that is drawn on screen. Hot-reloaded: edit, save, and the
running dashboard picks up the change within half a second.

``draw(screen, state)`` is the only entry point. ``state`` is a
``dashboard.State`` (see that file for the fields).
"""

from __future__ import annotations

from datetime import datetime

import pygame

import icons
import theme as T

PAGES = 2  # 0 = overview, 1 = 7-day forecast
_cache: dict = {}


def draw(screen: pygame.Surface, state) -> None:
    screen.blit(_background(), (0, 0))
    _header(screen, state)
    top = 92
    body = pygame.Rect(T.PAD, top, T.W - 2 * T.PAD, T.H - top - T.PAD - 6)
    if state.page == 1:
        _forecast_page(screen, body, state)
    else:
        split = 486
        _departures(screen, pygame.Rect(body.x, body.y, split - body.x, body.h), state)
        wx = split + T.GAP
        _weather(screen, pygame.Rect(wx, body.y, body.right - wx, body.h), state)
    _page_dots(screen, state.page)


# ── header ────────────────────────────────────────────────────────────────

def _header(screen, state):
    now = state.now
    if state.clock24:
        hm, ampm = now.strftime("%H:%M"), ""
    else:
        hm, ampm = now.strftime("%I:%M").lstrip("0"), now.strftime("%p")

    x, y = T.PAD + 2, 14
    t = _text(hm, "display-semibold", 58, T.TEXT)
    screen.blit(t, (x, y))
    x += t.get_width() + 6
    if ampm:
        a = _text(ampm, "semibold", 17, T.MUTED)
        screen.blit(a, (x, y + 37))
        x += a.get_width()

    x += 22
    pygame.draw.line(screen, T.DIVIDER, (x - 11, y + 16), (x - 11, y + 56), 1)
    screen.blit(_text(now.strftime("%A"), "semibold", 19, T.TEXT), (x, y + 13))
    screen.blit(_text(f"{now.strftime('%B')} {now.day}", "regular", 16, T.MUTED), (x, y + 37))

    # "insight" chip on the right: the one thing worth knowing at a glance
    tip = _insight(state)
    if tip:
        code, is_day, msg = tip
        label = _text(msg, "medium", 16, T.TEXT)
        ico = icons.icon(code, is_day, 26)
        w = 16 + ico.get_width() + 8 + label.get_width() + 18
        r = pygame.Rect(T.W - T.PAD - w, 26, w, 42)
        screen.blit(_panel(r.w, r.h, r.h // 2, T.CARD, T.CARD_BORDER), r)
        screen.blit(ico, (r.x + 14, r.centery - ico.get_height() // 2))
        screen.blit(label, (r.x + 14 + ico.get_width() + 8, r.centery - label.get_height() // 2))


def _insight(state):
    w = state.weather
    if not w:
        return None
    upcoming = w.hourly[1:9]  # next ~8 hours
    wet = next((h for h in upcoming if h.precip_prob >= 50), None)
    if wet:
        snow = icons.kind(wet.code) == "snow"
        when = _hour_label(wet.time, state.clock24)
        if w.hourly and w.hourly[0].precip_prob >= 50:
            return wet.code, wet.is_day, f"{'Snow' if snow else 'Rain'} continues · bring {'boots' if snow else 'an umbrella'}"
        return wet.code, wet.is_day, f"{'Snow' if snow else 'Rain'} likely around {when}"
    if upcoming:
        temps = [h.temp for h in upcoming]
        hi = max(temps)
        if hi - w.temp >= 6:
            peak = upcoming[temps.index(hi)]
            return peak.code, peak.is_day, f"Warming to {hi:.0f}° by {_hour_label(peak.time, state.clock24)}"
        lo = min(temps)
        if w.temp - lo >= 6:
            dip = upcoming[temps.index(lo)]
            return dip.code, dip.is_day, f"Cooling to {lo:.0f}° by {_hour_label(dip.time, state.clock24)}"
    return w.code, w.is_day, "Dry for the next 8 hours"


# ── departures card ───────────────────────────────────────────────────────

def _departures(screen, r, state):
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 20
    screen.blit(_tracked("DEPARTURES", "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    screen.blit(_fit(state.station, "semibold", 22, T.TEXT, r.w - 200), (ix, r.y + 36))
    _status(screen, r.right - 20, r.y + 20, state.trains_updated, state.trains_error, state.now)

    deps = _upcoming(state.departures or [], state.now, state.walk_minutes)[: state.max_rows]
    list_top = r.y + 80
    if not deps:
        if state.departures is None:
            msg = "Can't reach the MTA · retrying" if state.trains_error else "Loading departures…"
        else:
            msg = "No upcoming trains"
        t = _text(msg, "medium", 17, T.MUTED)
        screen.blit(t, t.get_rect(center=(r.centerx, list_top + (r.bottom - list_top) // 2 - 10)))
        return

    row_h = min(56, (r.bottom - list_top - 10) // max(1, state.max_rows))
    for i, d in enumerate(deps):
        y = list_top + i * row_h
        row = pygame.Rect(r.x + 8, y, r.w - 16, row_h - 4)
        if i == 0:
            screen.blit(_panel(row.w, row.h, 12, T.CARD_HI), row)
        elif i > 0:
            pygame.draw.line(screen, T.DIVIDER, (r.x + 20, y - 2), (r.right - 20, y - 2), 1)
        _departure_row(screen, row, d, state)


def _departure_row(screen, row, d, state):
    mins = _minutes_until(d.depart_at, state.now)
    dim = d.cancelled

    # line badge
    badge = _badge(d.line, T.hex_color(d.color), 34, diamond=d.express)
    screen.blit(badge, (row.x + 12, row.centery - 17))

    # destination + detail line
    tx = row.x + 60
    right_w = 92
    dest = _fit(d.destination, "semibold", 19, T.FAINT if dim else T.TEXT, row.right - right_w - tx)
    screen.blit(dest, (tx, row.y + 6))

    parts = []
    if d.cancelled:
        parts.append(("Cancelled", T.BAD))
    elif d.delay_min is not None:  # only if the feed reports lateness
        parts.append((f"{d.delay_min} min late", T.WARN) if d.delay_min >= 2 else ("On time", T.GOOD))
    if d.express:
        parts.append(("Express", T.TEXT))
    if d.platform:
        parts.append((f"Track {d.platform}", T.MUTED))
    if d.depart_at:
        when = _clock(d.depart_at, state.clock24)
        parts.append((f"Arrives {when}", T.MUTED))

    x, y = tx, row.y + 30
    for j, (txt, col) in enumerate(parts):
        if j:
            dot = _text("·", "regular", 15, T.FAINT)
            screen.blit(dot, (x + 6, y))
            x += 6 + dot.get_width() + 6
        t = _text(txt, "medium" if col != T.MUTED else "regular", 15, col)
        screen.blit(t, (x, y))
        x += t.get_width()

    # minutes, right aligned
    rx = row.right - 14
    if mins <= 0 and not dim:
        t = _text("Now", "display-semibold", 26, T.ACCENT)
        screen.blit(t, (rx - t.get_width(), row.centery - t.get_height() // 2))
    else:
        unit = _text("min", "medium", 14, T.FAINT if dim else T.MUTED)
        num = _text(str(mins), "display-semibold", 30, T.FAINT if dim else T.TEXT)
        ux = rx - unit.get_width()
        nx = ux - 5 - num.get_width()
        ny = row.centery - num.get_height() // 2
        screen.blit(num, (nx, ny))
        screen.blit(unit, (ux, ny + num.get_height() - unit.get_height() - 5))
        if dim:
            sy = row.centery
            pygame.draw.line(screen, T.FAINT, (nx - 3, sy), (rx + 2, sy), 2)


def _upcoming(deps, now, walk_minutes=0):
    """Trains you can still make, soonest first."""
    keep = [d for d in deps if d.depart_at and _minutes_until(d.depart_at, now) >= walk_minutes]
    return sorted(keep, key=lambda d: d.depart_at)


# ── weather card ──────────────────────────────────────────────────────────

def _weather(screen, r, state):
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 20
    screen.blit(_tracked((state.location or "WEATHER").upper(), "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    w = state.weather
    if not w:
        msg = "Forecast offline · retrying" if state.weather_error else "Loading forecast…"
        t = _text(msg, "medium", 16, T.MUTED)
        screen.blit(t, t.get_rect(center=r.center))
        return
    if state.weather_error:
        _status(screen, r.right - 20, r.y + 20, state.weather_updated, state.weather_error, state.now, compact=True)

    # current conditions
    ico = icons.icon(w.code, w.is_day, 84)
    screen.blit(_glow(84, T.SUN if w.is_day and icons.kind(w.code).startswith(("clear", "partly")) else T.ACCENT),
                (ix - 30, r.y + 26))
    screen.blit(ico, (ix - 6, r.y + 40))
    temp = _text(f"{w.temp:.0f}", "display-light", 68, T.TEXT)
    tx = r.right - 26 - temp.get_width()
    screen.blit(temp, (tx, r.y + 38))
    deg = _text("°", "display-light", 40, T.MUTED)
    screen.blit(deg, (tx + temp.get_width() - 2, r.y + 44))

    y = r.y + 134
    screen.blit(_fit(icons.condition(w.code), "semibold", 18, T.TEXT, r.w - 40), (ix, y))
    y += 26
    hl = f"H {w.high:.0f}°   L {w.low:.0f}°   Feels {w.feels_like:.0f}°"
    screen.blit(_fit(hl, "regular", 15, T.MUTED, r.w - 40), (ix, y))

    # hourly strip, centred in the space left below the divider
    div = r.y + 196
    pygame.draw.line(screen, T.DIVIDER, (ix, div), (r.right - 20, div), 1)
    hours = w.hourly[1:5] if len(w.hourly) > 4 else w.hourly[:4]
    if not hours:
        return
    content_h = 124 if any(h.precip_prob >= 20 for h in hours) else 104
    y = div + (r.bottom - div - content_h) // 2 - 14
    col_w = (r.w - 24) / len(hours)
    for i, h in enumerate(hours):
        cx = round(r.x + 12 + col_w * (i + 0.5))
        lab = _text(_hour_label(h.time, state.clock24), "medium", 13, T.MUTED)
        screen.blit(lab, lab.get_rect(midtop=(cx, y + 16)))
        hi = icons.icon(h.code, h.is_day, 42)
        screen.blit(hi, hi.get_rect(midtop=(cx, y + 38)))
        tt = _text(f"{h.temp:.0f}°", "semibold", 17, T.TEXT)
        screen.blit(tt, tt.get_rect(midtop=(cx + 3, y + 86)))
        if h.precip_prob >= 20:
            pp = _text(f"{h.precip_prob}%", "semibold", 12, T.RAIN)
            screen.blit(pp, pp.get_rect(midtop=(cx, y + 110)))


# ── forecast page ─────────────────────────────────────────────────────────

def _forecast_page(screen, r, state):
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 22
    screen.blit(_tracked("7-DAY FORECAST", "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    if state.location:
        screen.blit(_text(state.location, "semibold", 22, T.TEXT), (ix, r.y + 36))
    w = state.weather
    if not w or not w.daily:
        t = _text("Loading forecast…", "medium", 16, T.MUTED)
        screen.blit(t, t.get_rect(center=r.center))
        return

    days = w.daily[:7]
    lo_all = min(d.low for d in days)
    hi_all = max(d.high for d in days)
    span = max(1.0, hi_all - lo_all)

    top = r.y + 76
    row_h = (r.bottom - top - 8) // len(days)
    bar_x0, bar_x1 = r.x + 450, r.right - 86
    for i, d in enumerate(days):
        y = top + i * row_h
        cy = y + row_h // 2
        if i:
            pygame.draw.line(screen, T.DIVIDER, (ix, y), (r.right - 22, y), 1)
        name = "Today" if i == 0 else d.day.strftime("%A")
        screen.blit(_text(name, "semibold", 18, T.TEXT), (ix, cy - 12))
        ico = icons.icon(d.code, True, 32)
        screen.blit(ico, (r.x + 170, cy - 16))
        screen.blit(_fit(icons.condition(d.code), "regular", 15, T.MUTED, 118), (r.x + 212, cy - 9))
        if d.precip_prob >= 20:
            pp = _text(f"{d.precip_prob}%", "semibold", 14, T.RAIN)
            screen.blit(pp, (r.x + 384 - pp.get_width(), cy - 9))

        lo = _text(f"{d.low:.0f}°", "medium", 17, T.MUTED)
        screen.blit(lo, (bar_x0 - 12 - lo.get_width(), cy - 11))
        hi = _text(f"{d.high:.0f}°", "semibold", 17, T.TEXT)
        screen.blit(hi, (bar_x1 + 12, cy - 11))

        # range bar: faint full track + coloured segment for this day
        screen.blit(_panel(bar_x1 - bar_x0, 6, 3, T.CARD_HI), (bar_x0, cy - 3))
        a = bar_x0 + (d.low - lo_all) / span * (bar_x1 - bar_x0)
        b = bar_x0 + (d.high - lo_all) / span * (bar_x1 - bar_x0)
        seg = _gradient_bar(max(6, round(b - a)), 6,
                            _temp_color((d.low - lo_all) / span), _temp_color((d.high - lo_all) / span))
        screen.blit(seg, (round(a), cy - 3))
        if i == 0:  # current temperature marker on today's bar
            m = bar_x0 + (min(max(w.temp, lo_all), hi_all) - lo_all) / span * (bar_x1 - bar_x0)
            pygame.draw.circle(screen, T.CARD, (round(m), cy), 6)
            pygame.draw.circle(screen, T.TEXT, (round(m), cy), 4)


def _temp_color(t):
    return T.mix(T.TEMP_COLD, T.TEMP_MILD, t * 2) if t < 0.5 else T.mix(T.TEMP_MILD, T.TEMP_WARM, (t - 0.5) * 2)


# ── small widgets ─────────────────────────────────────────────────────────

def _status(screen, right, y, updated, error, now, compact=False):
    if error and updated:
        color, msg = T.WARN, f"Offline · {_ago(updated, now)}"
    elif error:
        color, msg = T.BAD, "Offline"
    elif updated:
        color, msg = T.GOOD, "Live"
    else:
        color, msg = T.FAINT, "Connecting"
    if compact:
        msg = "Offline" if error else msg
    t = _text(msg, "medium", 13, T.MUTED)
    screen.blit(t, (right - t.get_width(), y - 1))
    pygame.draw.circle(screen, color, (right - t.get_width() - 10, y + t.get_height() // 2 - 1), 4)


def _page_dots(screen, page):
    cx, y = T.W // 2, T.H - 13
    for i in range(PAGES):
        x = cx + (i - (PAGES - 1) / 2) * 14
        pygame.draw.circle(screen, T.MUTED if i == page else T.CARD_BORDER, (round(x), y), 3)


def _badge(label, color, d, diamond=False):
    key = ("badge", label, color, d, diamond)
    if key not in _cache:
        S = d * 4
        s = pygame.Surface((S, S), pygame.SRCALPHA)
        if diamond:  # express service
            h = S / 2
            pygame.draw.polygon(s, color, [(h, 0), (S, h), (h, S), (0, h)])
        elif len(label) <= 2:
            pygame.draw.circle(s, color, (S // 2, S // 2), S // 2)
        else:
            pygame.draw.rect(s, color, s.get_rect(), border_radius=S // 4)
        s = pygame.transform.smoothscale(s, (d, d))
        lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        size = 19 if len(label) == 1 else 15 if len(label) == 2 else 11
        if diamond:
            size -= 2
        t = _text(label[:4], "bold", size, (12, 16, 24) if lum > 165 else (255, 255, 255))
        s.blit(t, t.get_rect(center=(d / 2, d / 2 + 0.5)))
        _cache[key] = s
    return _cache[key]


def _panel(w, h, radius, fill, border=None):
    """Anti-aliased rounded rectangle (supersampled, cached)."""
    key = ("panel", w, h, radius, fill, border)
    if key not in _cache:
        k = 3
        s = pygame.Surface((w * k, h * k), pygame.SRCALPHA)
        rect = s.get_rect()
        if border:
            pygame.draw.rect(s, border, rect, border_radius=radius * k)
            rect = rect.inflate(-2 * k, -2 * k)
            pygame.draw.rect(s, fill, rect, border_radius=max(0, radius - 1) * k)
        else:
            pygame.draw.rect(s, fill, rect, border_radius=radius * k)
        _cache[key] = pygame.transform.smoothscale(s, (w, h))
    return _cache[key]


def _gradient_bar(w, h, c0, c1):
    key = ("grad", w, h, c0, c1)
    if key not in _cache:
        k = 3
        strip = pygame.Surface((w * k, h * k), pygame.SRCALPHA)
        for x in range(w * k):
            pygame.draw.line(strip, T.mix(c0, c1, x / max(1, w * k - 1)), (x, 0), (x, h * k))
        mask = pygame.Surface((w * k, h * k), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=h * k // 2)
        strip.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        _cache[key] = pygame.transform.smoothscale(strip, (w, h))
    return _cache[key]


def _glow(d, color):
    """Soft radial light behind the big weather icon."""
    key = ("glow", d, color)
    if key not in _cache:
        size = d + 60
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size // 2
        steps = 24
        for i in range(steps, 0, -1):
            r = c * i / steps
            a = round(26 * (1 - i / steps) ** 1.6)
            pygame.draw.circle(s, (*color, a), (c, c), round(r))
        _cache[key] = s
    return _cache[key]


def _background():
    if "bg" not in _cache:
        s = pygame.Surface((T.W, T.H))
        for y in range(T.H):
            pygame.draw.line(s, T.mix(T.BG_TOP, T.BG_BOTTOM, y / T.H), (0, y), (T.W, y))
        _cache["bg"] = s
    return _cache["bg"]


# ── text helpers ──────────────────────────────────────────────────────────

def _text(s, face, size, color):
    key = ("t", s, face, size, color)
    hit = _cache.get(key)
    if hit is None:
        hit = T.font(face, size).render(s, True, color)
        if len(_cache) > 1500:  # keep memory bounded on the Pi
            for k in [k for k in _cache if k[0] == "t"]:
                del _cache[k]
        _cache[key] = hit
    return hit


def _fit(s, face, size, color, max_w):
    """Render text, truncating with an ellipsis if it is too wide."""
    f = T.font(face, size)
    if f.size(s)[0] <= max_w:
        return _text(s, face, size, color)
    while s and f.size(s + "…")[0] > max_w:
        s = s[:-1]
    return _text(s.rstrip() + "…", face, size, color)


def _tracked(s, face, size, color, spacing):
    """Letter-spaced text (for small caps labels)."""
    key = ("tr", s, face, size, color, spacing)
    if key not in _cache:
        glyphs = [T.font(face, size).render(ch, True, color) for ch in s]
        w = sum(g.get_width() for g in glyphs) + spacing * (len(glyphs) - 1)
        out = pygame.Surface((max(1, round(w)), T.font(face, size).get_height()), pygame.SRCALPHA)
        x = 0.0
        for g in glyphs:
            out.blit(g, (round(x), 0))
            x += g.get_width() + spacing
        _cache[key] = out
    return _cache[key]


# ── time helpers ──────────────────────────────────────────────────────────

def _minutes_until(t: datetime | None, now: datetime) -> int:
    if t is None:
        return 0
    return int((t - now).total_seconds() // 60)


def _clock(t: datetime, h24: bool) -> str:
    t = t.astimezone()
    return t.strftime("%H:%M") if h24 else t.strftime("%I:%M").lstrip("0")


def _hour_label(t: datetime, h24: bool) -> str:
    return t.strftime("%H:00") if h24 else t.strftime("%I %p").lstrip("0")


def _ago(t: datetime, now: datetime) -> str:
    s = (now - t).total_seconds()
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    return f"{int(s // 3600)}h ago"
