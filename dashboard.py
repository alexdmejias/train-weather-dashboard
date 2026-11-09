#!/usr/bin/env python3
"""Train + weather dashboard for an 800×480 screen.

    python3 dashboard.py               # uses ./config.toml
    python3 dashboard.py --mock        # fake data, no network needed

On a Raspberry Pi it draws straight to the display (no desktop needed). On a
laptop it opens an 800×480 window. layout.py, theme.py and icons.py are
reloaded automatically when they change, so you can tweak the design live.

Keys (laptop): ←/→ or click = switch page · R = refresh data · Q/Esc = quit
Touch (Pi): tap = switch page · it returns to the overview after 30 s
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
import tomllib
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

import icons  # noqa: E402
import layout  # noqa: E402
import theme  # noqa: E402
from sources import mock, weather as weather_src  # noqa: E402
from sources.trains import get_provider  # noqa: E402

HOT_MODULES = [theme, icons, layout]   # reload order matters: theme first
PAGE_TIMEOUT = 30                      # seconds before returning to overview


@dataclass
class State:
    now: datetime
    station: str = ""
    location: str = ""
    clock24: bool = False
    max_rows: int = 5
    walk_minutes: int = 0
    page: int = 0
    departures: list | None = None
    weather: object | None = None
    trains_updated: datetime | None = None
    weather_updated: datetime | None = None
    trains_error: str | None = None
    weather_error: str | None = None
    version: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


def load_config(path: Path) -> dict:
    if not path.exists():
        example = ROOT / "config.example.toml"
        print(f"{path.name} not found — using {example.name}. Copy it to config.toml and edit.")
        path = example
    with open(path, "rb") as f:
        return tomllib.load(f)


# ── background data fetching ──────────────────────────────────────────────

class Fetcher(threading.Thread):
    """Polls the APIs on their own schedules without blocking the screen."""

    def __init__(self, cfg: dict, state: State, use_mock: bool):
        super().__init__(daemon=True)
        self.cfg, self.state, self.use_mock = cfg, state, use_mock
        tcfg = cfg.get("trains", {})
        self.provider = get_provider("mock" if use_mock else tcfg.get("provider", "mock"))
        self.train_every = tcfg.get("refresh_seconds", 45)
        self.weather_every = cfg.get("weather", {}).get("refresh_minutes", 15) * 60
        self.wake = threading.Event()
        self.next_train = self.next_weather = 0.0

    def refresh_now(self):
        self.next_train = self.next_weather = 0.0
        self.wake.set()

    def run(self):
        while True:
            t = time.monotonic()
            if t >= self.next_train:
                self._update("trains", self._get_trains)
                self.next_train = t + self.train_every
            if t >= self.next_weather:
                ok = self._update("weather", self._get_weather)
                # retry sooner after a failure
                self.next_weather = t + (self.weather_every if ok else 60)
            self.wake.wait(max(1.0, min(self.next_train, self.next_weather) - time.monotonic()))
            self.wake.clear()

    def _get_trains(self):
        tcfg = dict(self.cfg.get("trains", {}))
        return self.provider.fetch(tcfg)

    def _get_weather(self):
        wcfg = dict(self.cfg.get("weather", {}))
        wcfg["units"] = self.cfg.get("display", {}).get("units", "fahrenheit")
        if self.use_mock or wcfg.get("mock"):
            return mock.weather(datetime.now().astimezone(), self.cfg.get("trains", {}).get("mock_scenario", "normal"))
        return weather_src.fetch(wcfg)

    def _update(self, what, fn) -> bool:
        try:
            value = fn()
        except Exception as e:  # keep showing the last good data
            print(f"[{what}] {type(e).__name__}: {e}", flush=True)
            with self.state.lock:
                setattr(self.state, f"{what}_error", str(e))
                self.state.version += 1
            return False
        with self.state.lock:
            setattr(self.state, "departures" if what == "trains" else "weather", value)
            setattr(self.state, f"{what}_updated", datetime.now().astimezone())
            setattr(self.state, f"{what}_error", None)
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
    ap.add_argument("--config", type=Path, default=ROOT / "config.toml")
    ap.add_argument("--mock", action="store_true", help="use fake train + weather data")
    ap.add_argument("--scenario", help="mock scenario: normal, evening, rain, night, snow")
    ap.add_argument("--fullscreen", action="store_true", help="force fullscreen (default on the Pi)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.scenario:
        cfg.setdefault("trains", {})["mock_scenario"] = args.scenario
    disp, tcfg = cfg.get("display", {}), cfg.get("trains", {})

    state = State(
        now=datetime.now().astimezone(),
        station=tcfg.get("station_name", "Station"),
        location=disp.get("location_name", ""),
        clock24=disp.get("clock", "12h") == "24h",
        max_rows=tcfg.get("max_rows", 5),
        walk_minutes=tcfg.get("walk_minutes", 0),
    )

    pygame.display.init()
    pygame.font.init()
    flags = pygame.FULLSCREEN if (ON_PI or args.fullscreen) else 0
    screen = pygame.display.set_mode((theme.W, theme.H), flags)
    pygame.display.set_caption("Dashboard")
    pygame.mouse.set_visible(not ON_PI)

    fetcher = Fetcher(cfg, state, use_mock=args.mock or tcfg.get("provider") == "mock")
    fetcher.start()
    reloader = Reloader(HOT_MODULES)

    shot = threading.Event()
    running = [True]
    if hasattr(signal, "SIGUSR1"):  # `pkill -USR1 -f dashboard.py` → /tmp/dashboard.png
        signal.signal(signal.SIGUSR1, lambda *_: shot.set())
    signal.signal(signal.SIGTERM, lambda *_: running.__setitem__(0, False))

    clock = pygame.time.Clock()
    drawn = None
    last_touch = time.monotonic()

    while running[0]:
        force = False
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running[0] = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_q, pygame.K_ESCAPE):
                    running[0] = False
                elif ev.key == pygame.K_r:
                    fetcher.refresh_now()
                elif ev.key in (pygame.K_RIGHT, pygame.K_LEFT, pygame.K_SPACE):
                    step = -1 if ev.key == pygame.K_LEFT else 1
                    state.page = (state.page + step) % layout.PAGES
                    last_touch, force = time.monotonic(), True
            elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                # touchscreens send both; ignore the synthesized mouse event
                if ev.type == pygame.MOUSEBUTTONDOWN and getattr(ev, "touch", False):
                    continue
                state.page = (state.page + 1) % layout.PAGES
                last_touch, force = time.monotonic(), True

        if state.page and time.monotonic() - last_touch > PAGE_TIMEOUT:
            state.page, force = 0, True

        if reloader.check():
            force = True

        now = datetime.now().astimezone()
        # redraw on data change, page change, reload, or when the minute ticks
        key = (state.version, now.strftime("%H:%M"), state.page)
        if force or key != drawn:
            state.now = now
            with state.lock:
                try:
                    layout.draw(screen, state)
                except Exception as e:
                    _draw_error(screen, e)
            pygame.display.flip()
            drawn = key

        if shot.is_set():
            pygame.image.save(screen, "/tmp/dashboard.png")
            print("saved /tmp/dashboard.png", flush=True)
            shot.clear()

        clock.tick(10)

    pygame.quit()


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
