#!/usr/bin/env python3
"""Render the dashboard to PNG without a screen — for previews and docs.

    python3 tools/render.py                         # all scenarios → docs/screenshots/
    python3 tools/render.py --scenario rain --page 1 --out /tmp/x.png
    python3 tools/render.py --scale 2               # 1600×960 for crisp previews
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

import pygame  # noqa: E402

pygame.display.init()
pygame.font.init()
pygame.display.set_mode((1, 1))

import layout  # noqa: E402
import theme  # noqa: E402
import version  # noqa: E402
from dashboard import State  # noqa: E402
from sources import mock  # noqa: E402

# (scenario, page, time of day, file name[, extra State fields])
SHOTS = [
    ("normal", 0, (8, 42), "overview.png"),
    ("rain", 0, (8, 17), "overview-rain.png"),
    ("evening", 0, (17, 51), "overview-evening.png"),
    ("night", 0, (22, 6), "overview-night.png"),
    ("normal", 1, (8, 42), "forecast.png"),
    ("snow", 0, (7, 33), "overview-snow.png"),
    ("alerts", 0, (8, 17), "overview-alerts.png"),
    ("alerts", 2, (8, 17), "alerts.png"),
    ("normal", 2, (8, 42), "system.png"),
]


def render(scenario, page, hm, out: Path, scale=1, offline=False, toast=None, **extra):
    now = datetime.now().astimezone().replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    state = State(
        now=now, station="Steinway St & Broadway", location="Astoria", multi_station=True,
        direction_labels={"S": "Manhattan", "N": "Queens"}, page=page,
        departures=mock.trains(now, scenario), weather=mock.weather(now, scenario),
        subway_alerts=mock.subway_alerts(now, scenario), weather_alerts=mock.weather_alerts(now, scenario),
        updated={"trains": now - timedelta(seconds=20), "weather": now - timedelta(minutes=4)},
        walk_minutes=5,   # mock trains are bunched up close; 5 shows a "too soon" one per direction
        # a fixed, made-up build so screenshots don't change with every commit
        build=version.Build("29c57b7" + "0" * 33, 214, now - timedelta(hours=20),
                            "Departures fill the screen; Forecast shows today in detail + 3 days"),
        update=version.UpdateStatus("latest", "29c57b7", now - timedelta(minutes=3)),
        started=now - timedelta(hours=19, minutes=40), ip="192.168.1.42",
        **extra,
    )
    state.page_progress = 0.4  # auto-advance countdown, part way through
    if toast:
        state.toast = (toast, 0)
    if offline:
        state.errors["trains"] = "timeout"
        state.updated["trains"] = now - timedelta(minutes=6)
    surf = pygame.Surface((theme.W, theme.H))
    layout.draw(surf, state)
    if scale != 1:
        surf = pygame.transform.smoothscale(surf, (theme.W * scale, theme.H * scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surf, str(out))
    print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--time", default="08:42")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--toast", help="show a button-press confirmation, e.g. 'B · Forecast'")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    if args.scenario:
        hm = tuple(int(x) for x in args.time.split(":"))
        out = args.out or ROOT / "docs" / "screenshots" / f"{args.scenario}-{args.page}.png"
        render(args.scenario, args.page, hm, out, args.scale, args.offline, args.toast)
    else:
        outdir = args.out or ROOT / "docs" / "screenshots"
        for scenario, page, hm, name, *extra in SHOTS:
            render(scenario, page, hm, outdir / name, args.scale, **(extra[0] if extra else {}))


if __name__ == "__main__":
    main()
