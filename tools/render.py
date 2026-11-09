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
from dashboard import State  # noqa: E402
from sources import mock  # noqa: E402

# (scenario, page, time of day, file name)
SHOTS = [
    ("normal", 0, (8, 42), "overview.png"),
    ("rain", 0, (8, 17), "overview-rain.png"),
    ("delays", 0, (17, 51), "overview-delays.png"),
    ("night", 0, (22, 6), "overview-night.png"),
    ("normal", 1, (8, 42), "forecast.png"),
    ("snow", 0, (7, 33), "overview-snow.png"),
]


def render(scenario, page, hm, out: Path, scale=1, offline=False):
    now = datetime.now().astimezone().replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
    state = State(
        now=now, station="Harbor Street", location="Brooklyn", page=page,
        departures=mock.trains(now, scenario), weather=mock.weather(now, scenario),
        trains_updated=now - timedelta(seconds=20), weather_updated=now - timedelta(minutes=4),
    )
    if offline:
        state.trains_error = "timeout"
        state.trains_updated = now - timedelta(minutes=6)
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
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    if args.scenario:
        hm = tuple(int(x) for x in args.time.split(":"))
        out = args.out or ROOT / "docs" / "screenshots" / f"{args.scenario}-{args.page}.png"
        render(args.scenario, args.page, hm, out, args.scale, args.offline)
    else:
        outdir = args.out or ROOT / "docs" / "screenshots"
        for scenario, page, hm, name in SHOTS:
            render(scenario, page, hm, outdir / name, args.scale)


if __name__ == "__main__":
    main()
