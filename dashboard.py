#!/usr/bin/env python3
"""Train + weather dashboard for an 800×480 screen.

    python3 dashboard.py               # defaults from config.py, overridden by ./config.toml if present
    python3 dashboard.py --mock        # fake data, no network needed

On a Raspberry Pi it draws straight to the display (no desktop needed). On a
laptop it opens an 800×480 window. layout.py, theme.py, scenery.py, effects.py and
icons.py are reloaded automatically when they change, so you can tweak the design
live; a change to any other module restarts the dashboard by itself.

Space = next screen (screens also advance on their own every 30 s) ·
               1–5 = Button SHIM A–E · R = refresh data · S = settings · Q/Esc = quit
               (all keys are configurable under [keys]; --show-keys prints names)
Touch (Elecrow): tap = switch page · tap the alert banner = alert details ·
               tap any corner 3 times = settings
Button SHIM (HyperPixel): A departures · B forecast · C alerts · D refresh ·
               E sleep/wake (configurable in [buttons]) · any button 3× quickly = settings
Any key, button or tap restarts the 30 s timer.
"""

from __future__ import annotations

import argparse
import importlib
import os
import platform
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

PI_ZERO = platform.machine().startswith("armv6")   # Pi Zero / Pi 1: too slow to animate
ON_PI = platform.machine().startswith(("armv6", "armv7", "aarch64")) and Path("/dev/fb0").exists()
# On the Pi, draw straight to /dev/fb0 (hardware/framebuffer.py) with pygame
# running headless. SDL's own kmsdrm driver needs EGL, which fails on some
# Pi + OS combinations; set SDL_VIDEODRIVER=kmsdrm yourself to use it anyway.
USE_FB = ON_PI and not os.environ.get("SDL_VIDEODRIVER")
if USE_FB:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

import config  # noqa: E402
from hardware.buttonshim import ButtonShim  # noqa: E402
from hardware import framebuffer  # noqa: E402
from hardware.display import Presenter, set_backlight  # noqa: E402
import icons  # noqa: E402
import layout  # noqa: E402
import scenery  # noqa: E402
import effects  # noqa: E402
import theme  # noqa: E402
import version  # noqa: E402
from sources import alerts as alerts_src, mock, weather as weather_src  # noqa: E402
from sources.trains import mta_subway  # noqa: E402

HOT_MODULES = [theme, icons, scenery, layout, effects]   # reload order matters: theme first
BUTTON_EVENT = pygame.USEREVENT + 1


@dataclass
class State:
    now: datetime
    station: str = ""
    location: str = ""
    clock24: bool = False
    max_rows: int = 5
    walk_minutes: int | dict = 0
    too_soon: str = "small"                       # "small" or "hide": trains sooner than walk_minutes
    multi_station: bool = False
    directions: list = field(default_factory=lambda: ["S", "N"])
    direction_labels: dict = field(default_factory=dict)
    page: int = 0
    departures: list | None = None
    weather: object | None = None
    subway_alerts: list = field(default_factory=list)
    weather_alerts: list = field(default_factory=list)
    updated: dict = field(default_factory=dict)   # source name → datetime of last success
    errors: dict = field(default_factory=dict)    # source name → last error message
    alert_index: int = 0                          # which alert the header banner shows
    alert_offset: int = 0                         # skipped ahead with a button
    toast: tuple | None = None                    # (message, hide at monotonic time)
    asleep: bool = False                          # screen blanked
    page_progress: float | None = None            # 0–1 until the next auto-advance (None = off)
    build: object | None = None                   # version.Build this process is running (None = not a git clone)
    update: object | None = None                  # version.UpdateStatus: is that build the latest?
    style: str = "classic"                        # look: classic, hearth, almanac, window
    season: str = "auto"                          # palette for the cozy looks (auto = by date)
    effects: str = "on"                           # animated touches: on, subtle, off
    holidays: bool = True
    special_dates: dict = field(default_factory=dict)  # "MM-DD" → message
    page_seconds: int = 30                        # auto-advance interval (0 = off)
    settings_open: bool = False
    settings_focus: int = -1                      # keyboard/button focus on the settings page

    # convenience views used by the layout
    @property
    def trains_updated(self):
        return self.updated.get("trains")

    @property
    def weather_updated(self):
        return self.updated.get("weather")

    @property
    def trains_error(self):
        return self.errors.get("trains")

    @property
    def weather_error(self):
        return self.errors.get("weather")
    version: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


# ── background data fetching ──────────────────────────────────────────────

class Fetcher(threading.Thread):
    """Polls each data source on its own schedule without blocking the screen.

    A failed fetch keeps the last good data on screen and retries in a minute.
    """

    def __init__(self, cfg: dict, state: State, scenario: str | None):
        super().__init__(daemon=True)
        self.cfg, self.state, self.scenario = cfg, state, scenario  # scenario set → mock data
        al = cfg["alerts"]
        # name → (fetch function, state attribute, seconds between updates)
        self.tasks = {
            "trains": (self._get_trains, "departures", cfg["subway"]["refresh_seconds"]),
            "weather": (self._get_weather, "weather", cfg["weather"]["refresh_minutes"] * 60),
        }
        if al["subway"]:
            self.tasks["subway_alerts"] = (self._get_subway_alerts, "subway_alerts", 120)
        if al["weather"]:
            self.tasks["weather_alerts"] = (self._get_weather_alerts, "weather_alerts", 300)
        self.due = {name: 0.0 for name in self.tasks}
        self.wake = threading.Event()
        self._station_ids = None

    def refresh_now(self):
        self.due = {name: 0.0 for name in self.tasks}
        self.wake.set()

    def run(self):
        while True:
            for name, (fn, attr, every) in self.tasks.items():
                if time.monotonic() >= self.due[name]:
                    ok = self._update(name, fn, attr)
                    self.due[name] = time.monotonic() + (every if ok else min(every, 60))
            self.wake.wait(max(1.0, min(self.due.values()) - time.monotonic()))
            self.wake.clear()

    # ── sources ──

    def _near(self):
        """Configured location, or None if it can't be resolved yet (offline)."""
        try:
            lat, lon, name = config.place(self.cfg)
        except Exception as e:
            print(f"[location] {type(e).__name__}: {e}", flush=True)
            return None
        if name and not self.state.location:
            self.state.location = name
        return lat, lon

    def _stations(self):
        if self._station_ids is None:
            self._station_ids = mta_subway.resolve_stations(self.cfg["subway"]["stations"], self._near())
        return self._station_ids

    def _get_trains(self):
        if self.scenario:
            return mock.trains(datetime.now().astimezone(), self.scenario)
        return mta_subway.fetch(self.cfg["subway"], self._near())

    def _get_weather(self):
        if self.scenario:
            return mock.weather(datetime.now().astimezone(), self.scenario)
        near = self._near()
        if near is None:
            raise RuntimeError("location not resolved yet")
        return weather_src.fetch(*near, units=self.cfg["display"]["units"])

    def _get_subway_alerts(self):
        if self.scenario:
            return mock.subway_alerts(datetime.now().astimezone(), self.scenario)
        sub = self.cfg["subway"]
        return alerts_src.fetch_subway(self._stations(), sub["routes"], self.cfg["alerts"]["upcoming_hours"])

    def _get_weather_alerts(self):
        if self.scenario:
            return mock.weather_alerts(datetime.now().astimezone(), self.scenario)
        near = self._near()
        if near is None:
            raise RuntimeError("location not resolved yet")
        return alerts_src.fetch_weather(*near)

    def _update(self, name, fn, attr) -> bool:
        try:
            value = fn()
        except Exception as e:  # keep showing the last good data
            print(f"[{name}] {type(e).__name__}: {e}", flush=True)
            with self.state.lock:
                self.state.errors[name] = str(e)
                self.state.version += 1
            return False
        with self.state.lock:
            setattr(self.state, attr, value)
            self.state.updated[name] = datetime.now().astimezone()
            self.state.errors.pop(name, None)
            self.state.version += 1
        return True


# ── hot reload ────────────────────────────────────────────────────────────

def project_files(root: Path = ROOT) -> set[Path]:
    """Source files of every module loaded from this project folder."""
    out = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if f and f.endswith(".py") and Path(f).resolve().is_relative_to(root):
            out.add(Path(f).resolve())
    return out


class Reloader:
    """Picks up code changes while the dashboard runs.

    The drawing modules (``hot``) are reloaded in place. Any other project
    module can't be: the data already in memory was built by the old code, so
    new drawing code would trip over it (e.g. ``'Weather' object has no
    attribute 'wind_dir'`` after an update added that field). A change there
    restarts the whole process instead.

    A git pull or rsync writes files one after another, so nothing happens
    until the files have stopped changing.
    """

    INTERVAL = 0.25   # seconds between looks at the files

    def __init__(self, hot, watch=None):
        self.hot = list(hot)
        self.hot_files = {Path(m.__file__).resolve() for m in self.hot}
        self.files = sorted(set(project_files() if watch is None else map(Path, watch)) | self.hot_files)
        self.loaded = self.seen = self._snapshot()
        self.checked = 0.0

    def _snapshot(self) -> dict:
        out = {}
        for f in self.files:
            try:
                out[f] = os.path.getmtime(f)
            except OSError:
                out[f] = 0
        return out

    def check(self) -> str | None:
        """None, "reload" (drawing modules reloaded) or "restart" (the caller should restart)."""
        if time.monotonic() - self.checked < self.INTERVAL:
            return None
        self.checked = time.monotonic()
        now = self._snapshot()
        if now != self.seen:          # still being written: look again next time
            self.seen = now
            return None
        changed = [f for f in self.files if now[f] != self.loaded[f]]
        if not changed:
            return None
        self.loaded = now
        names = ", ".join(str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else f.name for f in changed)
        if any(f not in self.hot_files for f in changed):
            print(f"↻ {names} changed — restarting", flush=True)
            return "restart"
        try:
            for m in self.hot:  # reload all, in order, so references stay in sync
                importlib.reload(m)
            print(f"↻ reloaded {names}", flush=True)
        except Exception as e:
            print(f"✗ reload failed: {type(e).__name__}: {e}", flush=True)
        return "reload"


# ── main loop ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml",
                    help="optional overrides for the defaults in config.py")
    ap.add_argument("--mock", action="store_true", help="use fake train + weather data")
    ap.add_argument("--scenario", help="mock scenario (implies --mock): normal, evening, rain, night, snow")
    ap.add_argument("--fullscreen", action="store_true", help="force fullscreen (default on the Pi)")
    ap.add_argument("--show-keys", action="store_true",
                    help="print the name of every key pressed (to fill in [keys])")
    ap.add_argument("--portrait", action="store_true",
                    help="laptop: open a 480×800 window to preview HyperPixel rotation")
    args = ap.parse_args()

    cfg = config.load(args.config)
    scenario = args.scenario or ("normal" if args.mock else None)
    disp, sub = cfg["display"], cfg["subway"]
    names = list(dict.fromkeys(_station_label(s) for s in sub["stations"]))

    state = State(
        now=datetime.now().astimezone(),
        station=sub["title"] or " & ".join(names),
        location=disp["location_name"] or "",
        multi_station=len(names) > 1,
        clock24=disp["clock"] == "24h",
        max_rows=sub["max_rows"],
        walk_minutes=sub["walk_minutes"],
        too_soon=sub["too_soon"],
        directions=sub["directions"],
        direction_labels=sub["direction_labels"],
        build=version.current(),
        style=disp["style"],
        season=disp["season"],
        effects=_effects_mode(cfg["effects"]["mode"]),
        holidays=bool(cfg["effects"]["holidays"]),
        special_dates=dict(cfg["effects"]["dates"]),
        page_seconds=int(disp["page_seconds"] or 0),
    )
    state.update = version.update_status(state.build)
    print(f"running {state.build.label} ({state.build.short})" if state.build else "running a copy without git",
          flush=True)
    if not state.location:
        zip_code = str(cfg["weather"]["zip"])
        state.location = config.KNOWN_ZIPS.get(zip_code, (0, 0, ""))[2]  # unknown zips: set once geocoded

    pygame.display.init()
    pygame.font.init()
    fb = console = None
    if USE_FB:
        # native resolution: 800×480 on the Elecrow, 480×800 (portrait) on a HyperPixel 4.0
        fb = framebuffer.Framebuffer()
        print(f"/dev/fb0: {fb.w}×{fb.h}, {fb.bpp}-bit", flush=True)
        screen = pygame.display.set_mode((fb.w, fb.h))
        console = framebuffer.Console()
    elif ON_PI or args.fullscreen:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        w, h = (theme.H, theme.W) if args.portrait else (theme.W, theme.H)
        screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("Dashboard")
    pygame.mouse.set_visible(not ON_PI)
    presenter = Presenter(screen, (theme.W, theme.H), disp["rotate"],
                          flip=(lambda: fb.show(screen)) if fb else None)
    print(presenter.describe(), flush=True)
    if fb:
        for dev in framebuffer.touch_devices():
            framebuffer.Touch(dev, screen.get_size(), disp["touch_swap_xy"],
                              disp["touch_invert_x"], disp["touch_invert_y"]).start()

    fetcher = Fetcher(cfg, state, scenario)
    fetcher.start()
    reloader = Reloader(HOT_MODULES)

    # Button SHIM → pygame events, so buttons and keys share one code path
    bcfg = cfg["buttons"]
    shim = None
    if bcfg["enabled"] and (ON_PI or bcfg["enabled"] == "always"):
        shim = ButtonShim.connect(
            lambda name: pygame.event.post(pygame.event.Event(BUTTON_EVENT, button=name)),
            bcfg["i2c_bus"], bcfg["led_brightness"])

    shot = threading.Event()
    running = [True]
    restart = False                           # code changed on disk: start again with the new code
    if hasattr(signal, "SIGUSR1"):  # `pkill -USR1 -f dashboard.py` → /tmp/dashboard.png
        signal.signal(signal.SIGUSR1, lambda *_: shot.set())
    signal.signal(signal.SIGTERM, lambda *_: running.__setitem__(0, False))

    keymap = cfg["keys"]
    for k, a in keymap.items():
        if a and a not in KEY_ACTIONS:
            print(f"[keys] {k!r}: unknown action {a!r} — choose from {', '.join(sorted(KEY_ACTIONS))}", flush=True)
    reported_keys = set()

    clock = pygame.time.Clock()
    update_checked = time.monotonic()
    drawn = None
    page_started = time.monotonic()
    frame = pygame.Surface((theme.W, theme.H))   # the still dashboard; effects animate on a copy
    fps = max(5, min(60, int(cfg["effects"]["fps"])))
    fx_was_on = False
    fx_error_until = 0.0
    corner_taps: list = []                    # times of recent taps in a screen corner
    presses: list = []                        # (time, button) of recent Button SHIM presses
    settings_idle = 0.0                       # settings page closes itself after a minute

    def open_settings():
        nonlocal settings_idle
        state.settings_open, state.settings_focus = True, -1
        settings_idle = time.monotonic()
        state.version += 1

    def close_settings(msg=None):
        state.settings_open = False
        if msg:
            state.toast = (msg, time.monotonic() + 2.0)
        state.version += 1

    def choose(setting, value):
        """Apply one settings-page choice now and remember it in settings.json."""
        nonlocal settings_idle
        settings_idle = time.monotonic()
        if setting == "done":
            close_settings()
            return
        if setting == "try":
            effects.preview(value, 20)
            close_settings(f"Playing · {value.capitalize()}")
            return
        if setting == "clock":
            state.clock24 = value == "24h"
        elif setting == "effects":
            state.effects = value
        else:
            setattr(state, setting, value)
        effects.preview("", 0)                # re-plan with the new settings
        config.save_setting("effects" if setting == "effects" else "display",
                            "mode" if setting == "effects" else setting, value)
        state.version += 1

    def settings_input(action):
        """Keys / buttons on the settings page: move focus, choose, close."""
        nonlocal settings_idle
        settings_idle = time.monotonic()
        hits = layout.SETTINGS_HITS
        if action in ("next_page", "prev_page") and hits:
            step = 1 if action == "next_page" else -1
            state.settings_focus = (state.settings_focus + step) % len(hits)
        elif action in ("refresh", "next_alert") and 0 <= state.settings_focus < len(hits):
            _, setting, value = hits[state.settings_focus]
            choose(setting, value)
        elif action in ("sleep", "quit", "settings", "overview"):
            close_settings()
        state.version += 1

    def act(action: str, label: str | None = None):
        """Run a named action (from a button, key or tap)."""
        nonlocal page_started
        page_started = time.monotonic()       # any input restarts the auto-advance timer
        names = layout.pages(state)
        if state.asleep:            # any input wakes the screen and does nothing else
            state.asleep = False
            set_backlight(True)
            return
        if action == "settings":
            open_settings()
            return
        if action in ("overview", "forecast", "alerts"):
            if action == "alerts" and "alerts" not in names:
                state.toast = ("No alerts right now", time.monotonic() + 1.8)
                return
            state.page = names.index(action)
        elif action == "next_page":
            state.page = (state.page + 1) % len(names)
        elif action == "prev_page":
            state.page = (state.page - 1) % len(names)
        elif action == "next_alert":
            state.alert_offset += 1
        elif action == "refresh":
            fetcher.refresh_now()
        elif action == "sleep":
            state.asleep = True
            set_backlight(False)
            return
        if label:
            state.toast = (label, time.monotonic() + 1.5)

    while running[0]:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running[0] = False
            elif ev.type == BUTTON_EVENT:
                t = time.monotonic()
                presses[:] = [p for p in presses if t - p[0] < 1.5 and p[1] == ev.button] + [(t, ev.button)]
                if state.settings_open:
                    # A up · B down · C/D choose · E close
                    settings_input({"A": "prev_page", "B": "next_page", "C": "refresh", "D": "refresh"}
                                   .get(ev.button, "sleep"))
                    continue
                if len(presses) >= 3:            # the same button three times quickly
                    presses.clear()
                    state.asleep = False
                    set_backlight(True)
                    open_settings()
                    continue
                action = bcfg[ev.button.lower()]
                act(action, f"{ev.button} · {ACTION_LABELS.get(action, action)}")
            elif ev.type == pygame.KEYDOWN:
                name, action = lookup_key(keymap, ev.key, ev.mod)
                if action is None:
                    if args.show_keys or name not in reported_keys:
                        print(f"[keys] {name!r} isn't mapped — add it under [keys] in config.toml", flush=True)
                        reported_keys.add(name)
                elif args.show_keys:
                    print(f"[keys] {name!r} → {action or '(ignored)'}", flush=True)
                if not action:
                    continue
                if state.settings_open and not action.startswith("button_"):
                    settings_input(action)
                elif action == "quit":
                    running[0] = False
                elif action.startswith("button_"):          # behave exactly like Button SHIM A–E
                    pygame.event.post(pygame.event.Event(BUTTON_EVENT, button=action[-1].upper()))
                else:
                    act(action, KEY_TOASTS.get(action))
            elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                # touchscreens send both; ignore the synthesized mouse event
                if ev.type == pygame.MOUSEBUTTONDOWN and getattr(ev, "touch", False):
                    continue
                if ev.type == pygame.FINGERDOWN:  # finger coordinates are 0–1 of the physical screen
                    pos = presenter.to_canvas((ev.x * screen.get_width(), ev.y * screen.get_height()))
                else:
                    pos = presenter.to_canvas(ev.pos)
                t = time.monotonic()
                if state.settings_open:
                    hit = next((h for h in layout.SETTINGS_HITS if h[0].collidepoint(pos)), None)
                    if hit:
                        choose(hit[1], hit[2])
                    continue
                if _in_corner(pos):
                    # three taps in a corner open settings (corner taps never switch pages)
                    corner_taps[:] = [c for c in corner_taps if t - c < 1.5] + [t]
                    if state.asleep:
                        act("wake")
                    elif len(corner_taps) >= 3:
                        corner_taps.clear()
                        open_settings()
                    continue
                if layout.BANNER_RECT.collidepoint(pos) and "alerts" in layout.pages(state):
                    act("alerts")            # tap the alert banner → details
                else:
                    act("next_page")

        # auto-advance: Departures → Forecast → (Alerts) → Departures …
        page_seconds = state.page_seconds
        elapsed = time.monotonic() - page_started
        if state.settings_open:
            page_started, elapsed = time.monotonic(), 0.0     # don't flip pages behind the settings
            if time.monotonic() - settings_idle > 60:
                close_settings()
        if page_seconds and not state.asleep and elapsed >= page_seconds:
            state.page = (state.page + 1) % len(layout.pages(state))
            page_started, elapsed = time.monotonic(), 0.0
        state.page_progress = min(1.0, elapsed / page_seconds) if page_seconds else None
        if state.toast and time.monotonic() > state.toast[1]:
            state.toast = None

        change = reloader.check()
        if change == "restart":
            restart = True
            break
        reloaded = change == "reload"
        if time.monotonic() - update_checked > 30:   # did the updater find something newer?
            update_checked = time.monotonic()
            status = version.update_status(state.build)
            if status != state.update:
                with state.lock:
                    state.update = status
                    state.version += 1

        now = datetime.now().astimezone()
        # the header banner cycles through alerts (a button can also skip ahead)
        state.alert_index = int(time.time() // max(1, cfg["alerts"]["rotate_seconds"])) + state.alert_offset
        if state.page >= len(layout.pages(state)):  # alerts page vanished because the alerts cleared
            state.page = 0
        # redraw on data/page/toast changes, reloads, banner rotation, or when the minute ticks
        rotation = state.alert_index if (state.subway_alerts or state.weather_alerts) else 0
        # the countdown bar moves in 2-second steps — cheap enough for a Pi Zero
        tick = int(elapsed // 2) if page_seconds else 0
        key = (state.version, now.strftime("%H:%M"), state.page, rotation, state.toast, state.asleep, tick,
               state.settings_focus)
        changed = reloaded or key != drawn
        if changed:
            state.now = now
            with state.lock:
                if state.asleep:
                    frame.fill((0, 0, 0))
                else:
                    try:
                        layout.draw(frame, state)
                    except Exception as e:
                        _draw_error(frame, e)
            drawn = key
            if shim:
                shim.set_color((0, 0, 0) if state.asleep else status_color(state))

        # effects: copy the still frame and animate on top while anything is moving
        fx_on = False
        if not state.asleep and not state.settings_open and time.monotonic() > fx_error_until:
            try:
                fx_on = effects.running(state)
            except Exception as e:
                print(f"[effects] {type(e).__name__}: {e}", flush=True)
                fx_error_until = time.monotonic() + 60
        if fx_on or changed or fx_was_on:
            presenter.canvas.blit(frame, (0, 0))
            if fx_on:
                try:
                    effects.step(presenter.canvas, state, clock.get_time() / 1000)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"[effects] paused for a minute: {type(e).__name__}: {e}", flush=True)
                    fx_error_until = time.monotonic() + 60
            presenter.present()
        fx_was_on = fx_on

        if shot.is_set():
            pygame.image.save(presenter.canvas, "/tmp/dashboard.png")
            pygame.image.save(screen, "/tmp/dashboard-raw.png")   # as sent to the panel
            print("saved /tmp/dashboard.png (+ dashboard-raw.png)", flush=True)
            shot.clear()

        clock.tick(fps if fx_on else 10)

    if shim:
        shim.set_color((0, 0, 0))
        time.sleep(0.2)
    set_backlight(True)
    if console:
        console.restore()
    pygame.quit()
    if restart and running[0]:              # (not if we were asked to stop meanwhile)
        # same PID, so systemd and the updater's health check see no change
        os.execv(sys.executable, [sys.executable, *sys.argv])


KEY_ACTIONS = {"next_page", "prev_page", "overview", "forecast", "alerts", "next_alert",
               "refresh", "sleep", "quit", "settings", "button_a", "button_b", "button_c", "button_d", "button_e"}
MODIFIER_KEYS = {f"{side}{m}" for side in ("left", "right") for m in ("ctrl", "shift", "alt", "gui")}
# brief on-screen confirmation for keys whose effect isn't obvious
KEY_TOASTS = {"refresh": "Refreshing", "next_alert": "Next alert"}


def key_name(key: int, mod: int) -> str:
    """Config-style name for a key press: 'space', 'audionext', 'ctrl+shift+c'."""
    # SDL's own names (use_compat=False) also cover media keys: "AudioNext", "VolumeUp"
    base = config.normalize_key(pygame.key.name(key, use_compat=False) or f"key{key}")
    mods = [m for m, flag in (("ctrl", pygame.KMOD_CTRL), ("alt", pygame.KMOD_ALT),
                               ("shift", pygame.KMOD_SHIFT), ("meta", pygame.KMOD_META))
            if mod & flag and base not in (f"left{m}", f"right{m}")]
    return config.normalize_key("+".join(mods + [base]))


def lookup_key(keymap: dict, key: int, mod: int):
    """(name, action). action is None if unmapped, "" if deliberately ignored.

    An exact match wins ("ctrl+c"); otherwise a plain key still works when a
    modifier happens to be held ("shift+space" → "space").
    """
    name = key_name(key, mod)
    if name.rsplit("+", 1)[-1] in MODIFIER_KEYS:   # a lone Ctrl/Shift/… press: nothing to do
        return name, ""
    if name in keymap:
        return name, keymap[name]
    plain = name.rsplit("+", 1)[-1]
    if plain in keymap and plain != name:
        return name, keymap[plain]
    return name, None


ACTION_LABELS = {
    "overview": "Departures", "forecast": "Forecast", "alerts": "Alerts",
    "next_page": "Next page", "prev_page": "Previous page", "next_alert": "Next alert",
    "refresh": "Refreshing", "sleep": "Sleep", "settings": "Settings",
}


def _effects_mode(mode: str) -> str:
    if mode == "auto":
        return "off" if PI_ZERO else "on"
    return mode if mode in ("on", "subtle", "off") else "on"


CORNER = (110, 90)   # size of each corner's tap zone on the 800×480 canvas


def _in_corner(pos) -> bool:
    x, y = pos
    return (x < CORNER[0] or x > theme.W - CORNER[0]) and (y < CORNER[1] or y > theme.H - CORNER[1])


def status_color(state):
    """Button SHIM LED: red = severe weather / offline, amber = trouble on your
    lines, blue = planned work coming up, green = all good."""
    now = state.now
    if any(a.level == "severe" and a.active(now) for a in state.weather_alerts) or state.trains_error:
        return (255, 30, 30)
    if any(a.active(now) for a in state.subway_alerts) or state.weather_alerts:
        return (255, 140, 0)
    if state.subway_alerts:
        return (40, 100, 255)
    return (0, 200, 60)


def _station_label(entry: str) -> str:
    """Display name for a configured station (ids → names)."""
    return mta_subway.station_name(entry) if entry in mta_subway.data()["stations"] else entry


def _draw_error(screen, e):
    """Show layout bugs on screen instead of crashing — fix, save, it reloads."""
    import traceback
    print(traceback.format_exc(), flush=True)
    screen.fill((60, 18, 24))
    f = pygame.font.Font(None, 26)
    lines = ["layout.py error — fix and save to reload", "", f"{type(e).__name__}: {e}"]
    for i, line in enumerate(lines):
        screen.blit(f.render(line[:90], True, (255, 230, 230)), (24, 24 + i * 28))


if __name__ == "__main__":
    main()
