"""Everything that is drawn on screen. Hot-reloaded: edit, save, and the
running dashboard picks up the change within half a second.

``draw(screen, state)`` is the only entry point. ``state`` is a
``dashboard.State`` (see that file for the fields).
"""

from __future__ import annotations

from datetime import datetime

import pygame

import re

import icons
import theme as T
from sources.alerts import ordered as order_alerts
from sources.trains import mta_subway

_cache: dict = {}
BANNER_RECT = pygame.Rect(0, 0, 0, 0)   # where the alert banner was drawn (for taps)


def pages(state) -> list[str]:
    """Pages the user can tap through. The alerts page only exists when needed;
    System is last and skipped by the auto-advance."""
    return ["overview", "forecast"] + (["alerts"] if _alerts(state) else []) + ["system"]


def draw(screen: pygame.Surface, state) -> None:
    screen.blit(_background(), (0, 0))
    _header(screen, state)
    top = 92
    body = pygame.Rect(T.PAD, top, T.W - 2 * T.PAD, T.H - top - T.PAD - 6)
    names = pages(state)
    page = names[state.page % len(names)]
    if page == "forecast":
        _forecast_page(screen, body, state)
    elif page == "alerts":
        _alerts_page(screen, body, state)
    elif page == "system":
        _system_page(screen, body, state)
    else:
        _departures(screen, body, state)
    _page_tabs(screen, names, state.page % len(names), getattr(state, "page_progress", None))
    _build_tag(screen, state)
    if getattr(state, "toast", None):
        _toast(screen, state.toast[0])


def _toast(screen, msg):
    """Brief confirmation of a button press, bottom centre."""
    t = _text(msg, "semibold", 16, T.TEXT)
    w, h = t.get_width() + 36, 40
    r = pygame.Rect((T.W - w) // 2, T.H - 74, w, h)
    shadow = _panel(w + 12, h + 12, h // 2 + 6, (0, 0, 0))
    shadow.set_alpha(110)
    screen.blit(shadow, (r.x - 6, r.y - 2))
    screen.blit(_panel(w, h, h // 2, (44, 52, 70), (70, 80, 102)), r)
    screen.blit(t, t.get_rect(center=r.center))


def _alerts(state):
    return order_alerts(list(state.weather_alerts) + list(state.subway_alerts), state.now)


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
    day = _text(now.strftime("%A"), "semibold", 19, T.TEXT)
    date = _text(f"{now.strftime('%B')} {now.day}", "regular", 16, T.MUTED)
    screen.blit(day, (x, y + 13))
    screen.blit(date, (x, y + 37))

    # alerts take over the right side of the header
    alerts = _alerts(state)
    if alerts:
        left = x + max(day.get_width(), date.get_width()) + 22
        _alert_banner(screen, pygame.Rect(left, 18, T.W - T.PAD - left, 58), alerts, state)
        return
    BANNER_RECT.update(0, 0, 0, 0)

    # "insight" chip on the right: the one thing worth knowing at a glance
    tip = _insight(state)
    if tip:
        code, is_day, msg = tip
        label = _text(f"{state.weather.temp:.0f}°  ·  {msg}", "medium", 16, T.TEXT)
        ico = icons.icon(code, is_day, 26)
        w = 16 + ico.get_width() + 8 + label.get_width() + 18
        r = pygame.Rect(T.W - T.PAD - w, 26, w, 42)
        screen.blit(_panel(r.w, r.h, r.h // 2, T.CARD, T.CARD_BORDER), r)
        screen.blit(ico, (r.x + 14, r.centery - ico.get_height() // 2))
        screen.blit(label, (r.x + 14 + ico.get_width() + 8, r.centery - label.get_height() // 2))


def _alert_banner(screen, r, alerts, state):
    i = state.alert_index % len(alerts)
    a = alerts[i]
    fill, edge, accent = _level_colors(a.level)
    screen.blit(_panel(r.w, r.h, 14, fill, edge), r)
    BANNER_RECT.update(r)

    ico = _warn_icon(22, accent)
    screen.blit(ico, (r.x + 12, r.y + 10))
    tx = r.x + 44
    right = r.right - 14
    if len(alerts) > 1:
        c = _text(f"{i + 1}/{len(alerts)}", "medium", 12, T.MUTED)
        screen.blit(c, (right - c.get_width(), r.y + 10))
        right -= c.get_width() + 10

    meta = _alert_when(a, state)
    prefix = ("Weather · " if a.source == "weather" else "") + meta
    lines = _rich_lines(a.title, "semibold", 15, T.TEXT, right - tx, 2)
    if len(lines) == 1:  # room for the timing underneath
        _blit_rich(screen, lines[0], tx, r.y + 9)
        screen.blit(_text(prefix, "medium", 13, accent), (tx, r.y + 32))
    else:
        for j, line in enumerate(lines):
            _blit_rich(screen, line, tx, r.y + 8 + j * 21)


def _level_colors(level):
    """(fill, border, accent) for an alert level."""
    if level == "severe":
        return (54, 22, 30), (110, 42, 52), T.BAD
    if level == "warning":
        return (48, 38, 20), (98, 76, 34), T.WARN
    return (22, 32, 52), (44, 62, 96), T.ACCENT


def _alert_when(a, state) -> str:
    now = state.now
    if a.starts and a.starts > now:
        until = f" – {_when(a.ends, state)}" if a.ends else ""
        return f"From {_when(a.starts, state)}{until}"
    if a.ends:
        return f"Until {_when(a.ends, state)}"
    return "Now"


def _when(t, state) -> str:
    """'3:30 PM', 'Tue 3:30 PM' (within a week) or 'Nov 18'."""
    t = t.astimezone(state.now.tzinfo)
    if state.clock24:
        clock = t.strftime("%H:%M")
    else:
        clock = t.strftime("%I:%M").lstrip("0").removesuffix(":00") + t.strftime(" %p")
    days = (t.date() - state.now.date()).days
    if days == 0:
        return clock
    if days == 1:
        return f"tomorrow {clock}"
    if days < 7:
        return f"{t.strftime('%a')} {clock}"
    return f"{t.strftime('%b')} {t.day}"


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
    """Upcoming trains, one column per direction."""
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 22
    screen.blit(_tracked_fit(state.station.upper(), "semibold", 12, T.MUTED, 1.6, r.w - 160), (ix, r.y + 18))
    _status(screen, r.right - 22, r.y + 20, state.trains_updated, state.trains_error, state.now)

    top = r.y + 46
    if state.departures is None:
        msg = "Can't reach the MTA · retrying" if state.trains_error else "Loading departures…"
        t = _text(msg, "medium", 17, T.MUTED)
        screen.blit(t, t.get_rect(center=(r.centerx, top + (r.bottom - top) // 2 - 10)))
        return

    soon, ok = _partition(state.departures, state.now, state.walk_minutes)
    small = getattr(state, "too_soon", "hide") == "small"
    directions = state.directions or ["S", "N"]
    cols = len(directions)
    head_h, row_h = 28, 48
    per_col = max(1, min(state.max_rows, (r.bottom - 8 - top - head_h) // row_h))
    col_w = (r.w - 16 - T.GAP * (cols - 1)) // cols

    for c, direction in enumerate(directions):
        x = r.x + 8 + c * (col_w + T.GAP)
        label = state.direction_labels.get(direction, direction)
        t = _tracked(f"TO {label.upper()}", "bold", 11, T.TEXT_SOFT, 1.4)
        ty = top + 8 + t.get_height() // 2
        screen.blit(t, (x + 12, top + 8))
        pygame.draw.line(screen, T.DIVIDER, (x + 22 + t.get_width(), ty), (x + col_w - 12, ty), 1)
        if c:
            lx = x - T.GAP // 2
            pygame.draw.line(screen, T.DIVIDER, (lx, top + 4), (lx, r.bottom - 12), 1)

        # "small": the train you'd just miss stays on top, faded; "hide": it's left out
        missed = [d for d in soon if d.direction == direction][-1:] if small else []
        trains = (missed + [d for d in ok if d.direction == direction])[:per_col]
        y = top + head_h
        if not trains:
            screen.blit(_text("No upcoming trains", "regular", 15, T.FAINT), (x + 12, y + 6))
            continue
        for i, d in enumerate(trains):
            row = pygame.Rect(x, y, col_w, row_h - 4)
            if i == len(missed):            # the next train you can catch
                screen.blit(_panel(row.w, row.h, 12, T.CARD_HI), row)
            elif i:
                pygame.draw.line(screen, T.DIVIDER, (row.x + 12, row.y - 2), (row.right - 12, row.y - 2), 1)
            _departure_row(screen, row, d, state, compact=True, faded=d in missed)
            y += row_h


def _departure_row(screen, row, d, state, compact=False, faded=False):
    """``faded``: leaves too soon to catch (greyed, no strike-through)."""
    mins = _minutes_until(d.depart_at, state.now)
    dim = d.cancelled
    bd = 30 if compact else 34          # badge diameter
    dest_size, sub_size = (18, 14) if compact else (19, 15)

    # line badge (+ amber dot if this line has a current service alert)
    badge = _badge(d.line, T.hex_color(d.color), bd, diamond=d.express)
    bx, by = row.x + 12, row.centery - bd // 2
    screen.blit(badge, (bx, by))
    if d.line in _troubled_lines(state):
        cx, cy = bx + bd - 3, by + 3
        pygame.draw.circle(screen, T.CARD, (cx, cy), 7)
        pygame.draw.circle(screen, T.WARN, (cx, cy), 5)

    # destination + detail line
    tx = row.x + 12 + bd + 14
    right_w = 92
    dest = _fit(d.destination, "semibold", dest_size, T.FAINT if dim or faded else T.TEXT, row.right - right_w - tx)
    screen.blit(dest, (tx, row.y + (3 if compact else 6)))

    parts = []
    if state.multi_station and d.station:
        parts.append((d.station, T.TEXT_SOFT))
    if d.cancelled:
        parts.append(("Cancelled", T.BAD))
    elif d.delay_min is not None:  # only if the feed reports lateness
        parts.append((f"{d.delay_min} min late", T.WARN) if d.delay_min >= 2 else ("On time", T.GOOD))
    if d.express:
        parts.append(("Express", T.TEXT_SOFT))
    if d.platform:
        parts.append((f"Track {d.platform}", T.MUTED))
    if d.depart_at:
        when = _clock(d.depart_at, state.clock24)
        parts.append((f"Arrives {when}", T.MUTED))

    if faded:
        parts = [("Too soon to make", T.FAINT)] + [(txt, T.FAINT) for txt, _ in parts]
    x, y = tx, row.y + (24 if compact else 30)
    limit = row.right - right_w
    for j, (txt, col) in enumerate(parts):
        t = _text(txt, "medium" if col != T.MUTED else "regular", sub_size, col)
        dot = _text("·", "regular", sub_size, T.FAINT)
        gap = 12 + dot.get_width() if j else 0
        if x + gap + t.get_width() > limit:   # narrow row: drop what doesn't fit
            break
        if j:
            screen.blit(dot, (x + 6, y))
        x += gap
        screen.blit(t, (x, y))
        x += t.get_width()

    # minutes, right aligned
    rx = row.right - 14
    if mins <= 0 and not dim:
        t = _text("Now", "display-semibold", 24 if compact else 26, T.ACCENT)
        screen.blit(t, (rx - t.get_width(), row.centery - t.get_height() // 2))
    else:
        unit = _text("min", "medium", 14, T.FAINT if dim else T.MUTED)
        num = _text(str(mins), "display-semibold", 28 if compact else 30, T.FAINT if dim or faded else T.TEXT)
        ux = rx - unit.get_width()
        nx = ux - 5 - num.get_width()
        ny = row.centery - num.get_height() // 2
        screen.blit(num, (nx, ny))
        screen.blit(unit, (ux, ny + num.get_height() - unit.get_height() - 5))
        if dim:
            sy = row.centery
            pygame.draw.line(screen, T.FAINT, (nx - 3, sy), (rx + 2, sy), 2)


def _troubled_lines(state) -> set:
    return {r for a in state.subway_alerts if a.active(state.now) for r in a.routes}


def _upcoming(deps, now, walk_minutes=0):
    """Trains you can still make, soonest first."""
    return _partition(deps, now, walk_minutes)[1]


def _partition(deps, now, walk_minutes=0):
    """(too soon to make, can still make) — each soonest first, departed trains dropped.

    ``walk_minutes`` is a number, or a {station name: minutes} table.
    """
    def walk(d):
        if isinstance(walk_minutes, dict):
            return walk_minutes.get(d.station, 0)
        return walk_minutes

    live = sorted((d for d in deps if d.depart_at), key=lambda d: d.depart_at)
    soon = [d for d in live if 0 <= _minutes_until(d.depart_at, now) < walk(d)]
    keep = [d for d in live if _minutes_until(d.depart_at, now) >= walk(d)]
    return soon, keep


# ── forecast page ─────────────────────────────────────────────────────────

def _forecast_page(screen, r, state):
    split = r.x + 500
    _today(screen, pygame.Rect(r.x, r.y, split - r.x, r.h), state)
    _next_days(screen, pygame.Rect(split + T.GAP, r.y, r.right - split - T.GAP, r.h), state)


def _today(screen, r, state):
    """Current conditions and the rest of today, in detail."""
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 22
    head = "TODAY" + (f"  ·  {state.location.upper()}" if state.location else "")
    screen.blit(_tracked(head, "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    w = state.weather
    if not w:
        msg = "Forecast offline · retrying" if state.weather_error else "Loading forecast…"
        t = _text(msg, "medium", 16, T.MUTED)
        screen.blit(t, t.get_rect(center=r.center))
        return
    wa = [a for a in order_alerts(state.weather_alerts, state.now) if a.active(state.now)]
    if wa:
        _, _, accent = _level_colors(wa[0].level)
        label = _fit(wa[0].title, "semibold", 12, accent, r.w - 230)
        lx = r.right - 20 - label.get_width()
        screen.blit(label, (lx, r.y + 18))
        screen.blit(_warn_icon(14, accent), (lx - 19, r.y + 18))
    else:
        _status(screen, r.right - 22, r.y + 20, state.weather_updated, state.weather_error, state.now, compact=True)

    # now: icon, big temperature, condition + high/low
    y0 = r.y + 40
    screen.blit(_glow(76, T.SUN if w.is_day and icons.kind(w.code).startswith(("clear", "partly")) else T.ACCENT),
                (ix - 30, y0 - 12))
    screen.blit(icons.icon(w.code, w.is_day, 76), (ix - 6, y0))
    temp = _text(f"{w.temp:.0f}", "display-light", 64, T.TEXT)
    tx = ix + 86
    screen.blit(temp, (tx, y0 - 2))
    screen.blit(_text("°", "display-light", 38, T.MUTED), (tx + temp.get_width() - 2, y0 + 4))
    cx = tx + temp.get_width() + 34
    screen.blit(_fit(icons.condition(w.code), "semibold", 19, T.TEXT, r.right - 22 - cx), (cx, y0 + 12))
    screen.blit(_text(f"H {w.high:.0f}°   L {w.low:.0f}°", "regular", 15, T.MUTED), (cx, y0 + 40))

    # details grid
    stats = [("FEELS LIKE", f"{w.feels_like:.0f}°"),
             ("WIND", f"{w.wind:.0f} {w.wind_unit}" + (f" {_compass(w.wind_dir)}" if w.wind_dir is not None else "")),
             ("HUMIDITY", f"{w.humidity:.0f}%" if w.humidity is not None else "–"),
             ("RAIN TODAY", f"{w.precip_prob}%" if w.precip_prob is not None else "–"),
             ("UV INDEX", _uv(w.uv_max)),
             ("DAYLIGHT", f"{_clock(w.sunrise, state.clock24)} – {_clock(w.sunset, state.clock24)}"
              if w.sunrise and w.sunset else "–")]
    gy = r.y + 124
    cell_w = (r.w - 44) // 3
    for i, (label, value) in enumerate(stats):
        row, col = divmod(i, 3)
        x, y = ix + col * cell_w, gy + row * 46
        screen.blit(_tracked(label, "semibold", 10, T.FAINT, 1.2), (x, y))
        screen.blit(_fit(value, "semibold", 17, T.TEXT_SOFT, cell_w - 12), (x, y + 15))

    # the next few hours
    div = gy + 92
    pygame.draw.line(screen, T.DIVIDER, (ix, div), (r.right - 22, div), 1)
    hours = w.hourly[1:7] if len(w.hourly) > 6 else w.hourly[:6]
    if not hours:
        return
    y = div + 10
    col_w = (r.w - 24) / len(hours)
    for i, h in enumerate(hours):
        hx = round(r.x + 12 + col_w * (i + 0.5))
        lab = _text(_hour_label(h.time, state.clock24), "medium", 13, T.MUTED)
        screen.blit(lab, lab.get_rect(midtop=(hx, y)))
        hi = icons.icon(h.code, h.is_day, 36)
        screen.blit(hi, hi.get_rect(midtop=(hx, y + 20)))
        tt = _text(f"{h.temp:.0f}°", "semibold", 17, T.TEXT)
        screen.blit(tt, tt.get_rect(midtop=(hx + 3, y + 60)))
        if h.precip_prob >= 20:
            pp = _text(f"{h.precip_prob}%", "semibold", 12, T.RAIN)
            screen.blit(pp, pp.get_rect(midtop=(hx, y + 82)))


def _next_days(screen, r, state):
    """The next three days, compact."""
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 20
    screen.blit(_tracked("NEXT DAYS", "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    w = state.weather
    days = w.daily[1:4] if w else []
    if not days:
        return
    top = r.y + 44
    row_h = (r.bottom - top - 8) // len(days)
    for i, d in enumerate(days):
        y = top + i * row_h
        cy = y + row_h // 2
        if i:
            pygame.draw.line(screen, T.DIVIDER, (ix, y), (r.right - 20, y), 1)
        name = "Tomorrow" if i == 0 else d.day.strftime("%A")
        screen.blit(_text(name, "semibold", 18, T.TEXT), (ix, cy - 30))
        cond = _fit(icons.condition(d.code), "regular", 14, T.MUTED, r.w - 110)
        screen.blit(cond, (ix, cy - 5))
        if d.precip_prob >= 20:
            screen.blit(_text(f"{d.precip_prob}% chance", "semibold", 13, T.RAIN), (ix, cy + 15))
        ico = icons.icon(d.code, True, 40)
        screen.blit(ico, (r.right - 20 - ico.get_width(), cy - 36))
        hi = _text(f"{d.high:.0f}°", "semibold", 17, T.TEXT)
        lo = _text(f"{d.low:.0f}°", "medium", 15, T.MUTED)
        screen.blit(lo, (r.right - 20 - lo.get_width(), cy + 10))
        screen.blit(hi, (r.right - 20 - lo.get_width() - 8 - hi.get_width(), cy + 8))


def _compass(deg) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def _uv(uv) -> str:
    if uv is None:
        return "–"
    level = "Low" if uv < 3 else "Moderate" if uv < 6 else "High" if uv < 8 else "Very high"
    return f"{uv:.0f} · {level}"


# ── system page ───────────────────────────────────────────────────────────

UPDATE_COLORS = {"latest": "GOOD", "pending": "ACCENT", "failed": "WARN"}


def _update_color(update):
    return getattr(T, UPDATE_COLORS.get(getattr(update, "state", ""), "FAINT"))


def _build_tag(screen, state):
    """Bottom-left: which build is running, with a dot that's green when it's the latest."""
    build = getattr(state, "build", None)
    if not build:
        return
    t = _text(build.label, "medium", 12, T.FAINT)
    x, y = T.PAD + 12, T.H - 22
    pygame.draw.circle(screen, _update_color(getattr(state, "update", None)), (T.PAD + 4, y + t.get_height() // 2), 3)
    screen.blit(t, (x, y))


def _system_page(screen, r, state):
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 22
    screen.blit(_tracked("SYSTEM", "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    build, update = getattr(state, "build", None), getattr(state, "update", None)

    # hero: is this the latest version?
    color = _update_color(update)
    cy = r.y + 78
    screen.blit(_glow(56, color), (ix - 14, cy - 28 - 14))
    pygame.draw.circle(screen, color, (ix + 14, cy), 14)
    if getattr(update, "state", "") == "latest":     # check mark
        pygame.draw.lines(screen, T.CARD, False, [(ix + 7, cy), (ix + 12, cy + 5), (ix + 21, cy - 5)], 3)
    else:
        pygame.draw.circle(screen, T.CARD, (ix + 14, cy), 5)
    msg = update.message if update else "Version unknown"
    screen.blit(_fit(msg, "semibold", 24, T.TEXT, r.w - 100), (ix + 44, cy - 24))
    if build:
        sub = f"{build.label} · {build.short}"
        if build.date:
            sub += f" · built {_when(build.date, state)}"
    else:
        sub = "Not a git clone — copied with sync.sh?"
    screen.blit(_fit(sub, "regular", 15, T.MUTED, r.w - 100), (ix + 44, cy + 6))

    # details
    def feed(name):
        updated, error = state.updated.get(name), state.errors.get(name)
        if error:
            return f"Offline · {_ago(updated, state.now)}" if updated else "Offline"
        return f"Live · {_ago(updated, state.now)}" if updated else "Connecting"

    checked = getattr(update, "checked", None)
    started = getattr(state, "started", None)
    stats = [
        ("CHANGE", build.subject if build and build.subject else "–"),
        ("LAST UPDATE CHECK", _ago(checked, state.now) if checked else "–"),
        ("RUNNING SINCE", f"{_when(started, state)}" if started else "–"),
        ("TRAINS", feed("trains")),
        ("WEATHER", feed("weather")),
        ("NETWORK", getattr(state, "ip", None) or "Offline"),
    ]
    gy = r.y + 130
    pygame.draw.line(screen, T.DIVIDER, (ix, gy - 12), (r.right - 22, gy - 12), 1)
    cell_w = (r.w - 44) // 3
    for i, (label, value) in enumerate(stats):
        if i == 0:                      # the commit message gets the whole first row
            x, y, w = ix, gy, r.w - 44
        else:
            row, col = divmod(i - 1, 3)
            x, y, w = ix + col * cell_w, gy + (row + 1) * 56, cell_w - 12
        screen.blit(_tracked(label, "semibold", 10, T.FAINT, 1.2), (x, y))
        screen.blit(_fit(value, "semibold", 17, T.TEXT_SOFT, w), (x, y + 15))

    hint = "Updates are checked every 5 min · press Space to go back"
    t = _text(hint, "regular", 13, T.FAINT)
    screen.blit(t, (ix, r.bottom - 18 - t.get_height()))


# ── alerts page ───────────────────────────────────────────────────────────

def _alerts_page(screen, r, state):
    screen.blit(_panel(r.w, r.h, T.RADIUS, T.CARD, T.CARD_BORDER), r)
    ix = r.x + 22
    screen.blit(_tracked("ALERTS", "semibold", 12, T.MUTED, 1.6), (ix, r.y + 18))
    alerts = _alerts(state)
    y = r.y + 44
    bottom = r.bottom - 14
    shown = 0
    for a in alerts:
        _, _, accent = _level_colors(a.level)
        title = _rich_lines(a.title, "semibold", 17, T.TEXT, r.w - 90, 2)
        body = _rich_lines(a.body, "regular", 14, T.MUTED, r.w - 90, 2) if a.body else []
        h = 8 + len(title) * 23 + 20 + len(body) * 19 + 10
        if y + h > bottom and shown:
            more = _text(f"+{len(alerts) - shown} more", "medium", 14, T.MUTED)
            screen.blit(more, (r.right - 22 - more.get_width(), r.y + 18))
            break
        if shown:
            pygame.draw.line(screen, T.DIVIDER, (ix, y), (r.right - 22, y), 1)
        screen.blit(_warn_icon(24, accent), (ix, y + 10))
        tx, ty = ix + 40, y + 8
        for line in title:
            _blit_rich(screen, line, tx, ty)
            ty += 23
        src = "Weather alert" if a.source == "weather" else "Subway"
        meta = _text(f"{src} · {_alert_when(a, state)}", "medium", 13, accent)
        screen.blit(meta, (tx, ty + 1))
        ty += 20
        for line in body:
            _blit_rich(screen, line, tx, ty)
            ty += 19
        y += h
        shown += 1


def _warn_icon(d, color):
    """Rounded warning triangle with an exclamation mark."""
    key = ("warn", d, color)
    if key not in _cache:
        S = d * 4
        s = pygame.Surface((S, S), pygame.SRCALPHA)
        pts = [(S / 2, S * 0.08), (S * 0.96, S * 0.9), (S * 0.04, S * 0.9)]
        pygame.draw.polygon(s, color, pts)
        for p in pts:  # soften the corners
            pygame.draw.circle(s, color, (round(p[0]), round(p[1])), round(S * 0.06))
        ink = (20, 16, 10)
        pygame.draw.line(s, ink, (S / 2, S * 0.38), (S / 2, S * 0.62), max(2, round(S * 0.1)))
        pygame.draw.circle(s, ink, (round(S / 2), round(S * 0.76)), round(S * 0.06))
        _cache[key] = pygame.transform.smoothscale(s, (d, d))
    return _cache[key]


# ── rich text: words + inline line badges ("[N] trains are delayed") ──────

_TOKEN = re.compile(r"\[([^\]]+)\]")


def _route_badge_color(name):
    routes = mta_subway.data()["routes"]
    info = routes.get(name) or next((v for v in routes.values() if v["name"] == name), None)
    return T.hex_color(info["color"]) if info else None


def _rich_tokens(text):
    """Split text into (kind, value, glued) tokens: kind 't' = word, 'b' = line badge.

    ``glued`` means no space before it (punctuation right after a badge: "[R].").
    """
    out = []

    def words(chunk):
        for j, w in enumerate(chunk.split()):
            out.append(("t", w, j == 0 and bool(out) and not chunk[:1].isspace()))

    pos = 0
    for m in _TOKEN.finditer(text):
        words(text[pos:m.start()])
        inner = m.group(1).strip()
        if _route_badge_color(inner) is not None:
            out.append(("b", inner, False))
        elif "shuttle bus" in inner.lower():
            out.append(("t", "shuttle bus", False))
        elif "accessibility" not in inner.lower():
            words(inner)
        pos = m.end()
    words(text[pos:])
    return out


def _rich_lines(text, face, size, color, max_w, max_lines):
    """Word-wrap into at most ``max_lines`` lines of rendered pieces, with an ellipsis if cut."""
    f = T.font(face, size)
    space = f.size(" ")[0]
    bd = round(size * 1.15)
    lines, cur, w = [], [], 0
    for kind, val, glued in _rich_tokens(text):
        piece = _badge(val, _route_badge_color(val), bd) if kind == "b" else _text(val, face, size, color)
        if glued and cur:  # stick to the previous piece
            merged = pygame.Surface((cur[-1].get_width() + piece.get_width() + 1,
                                     max(cur[-1].get_height(), piece.get_height())), pygame.SRCALPHA)
            merged.blit(cur[-1], (0, (merged.get_height() - cur[-1].get_height()) // 2))
            merged.blit(piece, (cur[-1].get_width() + 1, (merged.get_height() - piece.get_height()) // 2))
            w += piece.get_width() + 1
            cur[-1] = merged
            continue
        pw = piece.get_width() + (space if cur else 0)
        if cur and w + pw > max_w:
            lines.append(cur)
            if len(lines) == max_lines:
                last = lines[-1]
                ell = _text("…", face, size, color)
                while last and sum(p.get_width() + space for p in last) + ell.get_width() > max_w:
                    last.pop()
                last.append(ell)
                return lines
            cur, w = [], 0
            pw = piece.get_width()
        cur.append(piece)
        w += pw
    if cur:
        lines.append(cur)
    return lines


def _blit_rich(screen, pieces, x, y):
    if not pieces:
        return
    h = max(p.get_height() for p in pieces)
    space = 4
    for p in pieces:
        screen.blit(p, (x, y + (h - p.get_height()) // 2))
        x += p.get_width() + space



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


TAB_LABELS = {"overview": "Departures", "forecast": "Forecast", "alerts": "Alerts", "system": "System"}


def _page_tabs(screen, names, current, progress):
    """Bottom strip: which screen is showing, time until the next one, and how to switch."""
    y = T.H - 22
    labels = [_text(TAB_LABELS.get(n, n), "semibold" if i == current else "medium", 12,
                    T.TEXT if i == current else T.FAINT) for i, n in enumerate(names)]
    gap = 22
    total = sum(l.get_width() for l in labels) + gap * (len(labels) - 1)
    x = (T.W - total) // 2
    for i, lab in enumerate(labels):
        screen.blit(lab, (x, y))
        if i == current:
            # countdown to the next auto-advance, filling under the active tab
            bar = pygame.Rect(x, y + lab.get_height() + 1, lab.get_width(), 2)
            pygame.draw.rect(screen, T.CARD_BORDER, bar, border_radius=1)
            if progress is not None:
                fill = bar.copy()
                fill.width = max(2, round(bar.width * progress))
                pygame.draw.rect(screen, T.ACCENT, fill, border_radius=1)
        if i < len(labels) - 1:
            dot = _text("·", "medium", 12, T.FAINT)
            screen.blit(dot, (x + lab.get_width() + (gap - dot.get_width()) // 2, y))
        x += lab.get_width() + gap

    # key hint, bottom right
    key = _text("SPACE", "semibold", 9, T.MUTED)
    cap = pygame.Rect(0, 0, key.get_width() + 12, 15)
    hint = _text("next", "medium", 12, T.FAINT)
    cap.topleft = (T.W - T.PAD - hint.get_width() - 6 - cap.width, y)
    screen.blit(_panel(cap.w, cap.h, 4, T.CARD, T.CARD_BORDER), cap)
    screen.blit(key, key.get_rect(center=cap.center))
    screen.blit(hint, (cap.right + 6, y))


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
        size = round(d * (0.56 if len(label) == 1 else 0.44 if len(label) == 2 else 0.33))
        if diamond:
            size = round(size * 0.88)
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


def _tracked_fit(s, face, size, color, spacing, max_w):
    out = _tracked(s, face, size, color, spacing)
    while out.get_width() > max_w and len(s) > 2:
        s = s[:-2].rstrip() + "…"
        out = _tracked(s, face, size, color, spacing)
    return out


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
