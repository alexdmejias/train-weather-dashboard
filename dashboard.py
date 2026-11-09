#!/usr/bin/env python3
"""Train + weather dashboard for an 800×480 screen.

    python3 dashboard.py               # defaults from config.py, overridden by ./config.toml if present
    python3 dashboard.py --mock        # fake data, no network needed

On a Raspberry Pi it draws straight to the display (no desktop needed). On a
laptop it opens an 800×480 window. layout.py, theme.py, scenery.py and icons.py are
reloaded automatically when they change, so you can tweak the design live.

Space = next screen (screens also advance on their own every 30 s) ·
               1–5 = Button SHIM A–E · R = refresh data · Q/Esc = quit
               (all keys are configurable under [keys]; --show-keys prints names)
Touch (Elecrow): tap = switch page · tap the alert banner = alert details
Button SHIM (HyperPixel): A departures · B forecast · C alerts · D refresh ·
               E sleep/wake (configurable in [buttons])
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

ON_PI = platform.machine().startswith(("armv6", "armv7", "aarch64")) and Path("/dev/dri").exists()
if ON_PI and not os.environ.get("SDL_VIDEODRIVER"):
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

import config  # noqa: E402
from hardware.buttonshim import ButtonShim  # noqa: E402
from hardware.display import Presenter, set_backlight  # noqa: E402
import icons  # noqa: E402
import layout  # noqa: E402
import scenery  # noqa: E402
import theme  # noqa: E402
from sources import alerts as alerts_src, mock, weather as weather_src  # noqa: E402
from sources.trains import mta_subway  # noqa: E402

HOT_MODULES = [theme, icons, scenery, layout]   # reload order matters: theme first
BUTTON_EVENT = pygame.USEREVENT + 1


@dataclass
class State:
    now: datetime
    station: str = ""
    location: str = ""
    clock24: bool = False
    max_rows: int = 5
    walk_minutes: int | dict = 0
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
    style: str = "classic"                        # look: classic, hearth, almanac, window
    season: str = "auto"                          # palette for the cozy looks (auto = by date)

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

class Reloader:
    def __init__(self, modules):
        self.modules = modules
        self.mtimes = {m: self._mtime(m) for m in modules}

    @staticmethod
    def _mtime(m):
        try:
            return os.path.getmtime(m.__file__)
        except OSError:
            return 0

    def check(self) -> bool:
        changed = [m for m in self.modules if self._mtime(m) != self.mtimes[m]]
        if not changed:
            return False
        for m in self.modules:  # reload all, in order, so references stay in sync
            self.mtimes[m] = self._mtime(m)
        try:
            for m in self.modules:
                importlib.reload(m)
            print("↻ reloaded " + ", ".join(Path(m.__file__).name for m in changed), flush=True)
        except Exception as e:
            print(f"✗ reload failed: {type(e).__name__}: {e}", flush=True)
        return True


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
        directions=sub["directions"],
        direction_labels=sub["direction_labels"],
        style=disp["style"],
        season=disp["season"],
    )
    if not state.location:
        zip_code = str(cfg["weather"]["zip"])
        state.location = config.KNOWN_ZIPS.get(zip_code, (0, 0, ""))[2]  # unknown zips: set once geocoded

    pygame.display.init()
    pygame.font.init()
    if ON_PI or args.fullscreen:
        # native resolution: 800×480 on the Elecrow, 480×800 (portrait) on a HyperPixel 4.0
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        w, h = (theme.H, theme.W) if args.portrait else (theme.W, theme.H)
        screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("Dashboard")
    pygame.mouse.set_visible(not ON_PI)
    presenter = Presenter(screen, (theme.W, theme.H), disp["rotate"])
    print(presenter.describe(), flush=True)

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
    if hasattr(signal, "SIGUSR1"):  # `pkill -USR1 -f dashboard.py` → /tmp/dashboard.png
        signal.signal(signal.SIGUSR1, lambda *_: shot.set())
    signal.signal(signal.SIGTERM, lambda *_: running.__setitem__(0, False))

    keymap = cfg["keys"]
    for k, a in keymap.items():
        if a and a not in KEY_ACTIONS:
            print(f"[keys] {k!r}: unknown action {a!r} — choose from {', '.join(sorted(KEY_ACTIONS))}", flush=True)
    reported_keys = set()

    clock = pygame.time.Clock()
    drawn = None
    page_seconds = disp["page_seconds"]       # auto-advance interval; 0 = stay put
    page_started = time.monotonic()

    def act(action: str, label: str | None = None):
        """Run a named action (from a button, key or tap)."""
        nonlocal page_started
        page_started = time.monotonic()       # any input restarts the auto-advance timer
        names = layout.pages(state)
        if state.asleep:            # any input wakes the screen and does nothing else
            state.asleep = False
            set_backlight(True)
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
                if action == "quit":
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
                if layout.BANNER_RECT.collidepoint(pos) and "alerts" in layout.pages(state):
                    act("alerts")            # tap the alert banner → details
                else:
                    act("next_page")

        # auto-advance: Departures → Forecast → (Alerts) → Departures …
        elapsed = time.monotonic() - page_started
        if page_seconds and not state.asleep and elapsed >= page_seconds:
            state.page = (state.page + 1) % len(layout.pages(state))
            page_started, elapsed = time.monotonic(), 0.0
        state.page_progress = min(1.0, elapsed / page_seconds) if page_seconds else None
        if state.toast and time.monotonic() > state.toast[1]:
            state.toast = None

        reloaded = reloader.check()

        now = datetime.now().astimezone()
        # the header banner cycles through alerts (a button can also skip ahead)
        state.alert_index = int(time.time() // max(1, cfg["alerts"]["rotate_seconds"])) + state.alert_offset
        if state.page >= len(layout.pages(state)):  # alerts page vanished because the alerts cleared
            state.page = 0
        # redraw on data/page/toast changes, reloads, banner rotation, or when the minute ticks
        rotation = state.alert_index if (state.subway_alerts or state.weather_alerts) else 0
        # the countdown bar moves in 2-second steps — cheap enough for a Pi Zero
        tick = int(elapsed // 2) if page_seconds else 0
        key = (state.version, now.strftime("%H:%M"), state.page, rotation, state.toast, state.asleep, tick)
        if reloaded or key != drawn:
            state.now = now
            with state.lock:
                if state.asleep:
                    presenter.canvas.fill((0, 0, 0))
                else:
                    try:
                        layout.draw(presenter.canvas, state)
                    except Exception as e:
                        _draw_error(presenter.canvas, e)
            presenter.present()
            drawn = key
            if shim:
                shim.set_color((0, 0, 0) if state.asleep else status_color(state))

        if shot.is_set():
            pygame.image.save(presenter.canvas, "/tmp/dashboard.png")
            pygame.image.save(screen, "/tmp/dashboard-raw.png")   # as sent to the panel
            print("saved /tmp/dashboard.png (+ dashboard-raw.png)", flush=True)
            shot.clear()

        clock.tick(10)

    if shim:
        shim.set_color((0, 0, 0))
        time.sleep(0.2)
    set_backlight(True)
    pygame.quit()


KEY_ACTIONS = {"next_page", "prev_page", "overview", "forecast", "alerts", "next_alert",
               "refresh", "sleep", "quit", "button_a", "button_b", "button_c", "button_d", "button_e"}
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
    "refresh": "Refreshing", "sleep": "Sleep",
}


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
