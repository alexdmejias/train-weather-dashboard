"""Realistic fake data so the dashboard can be designed offline.

Weather is produced as an Open-Meteo-shaped response and run through the real
parser, so mock mode exercises the same code path as live mode.
Scenarios: "normal", "evening", "rain", "night", "snow".
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .models import Departure
from .trains import mta_subway
from .weather import parse as parse_weather

# (route, destination, minutes away, station, direction) — Steinway St (M/R)
# and Broadway (N/W) in Astoria, the default stations
STEINWAY, BROADWAY = "Steinway St", "Broadway"
TO_CITY = [
    ("N", "Coney Island-Stillwell Av", 2, BROADWAY, "S"),
    ("R", "Bay Ridge-95 St", 4, STEINWAY, "S"),
    ("W", "Whitehall St-South Ferry", 6, BROADWAY, "S"),
    ("M", "Middle Village-Metropolitan Av", 8, STEINWAY, "S"),
    ("N", "Coney Island-Stillwell Av", 11, BROADWAY, "S"),
]
TO_QUEENS = [
    ("W", "Astoria-Ditmars Blvd", 3, BROADWAY, "N"),
    ("M", "Forest Hills-71 Av", 5, STEINWAY, "N"),
    ("N", "Astoria-Ditmars Blvd", 9, BROADWAY, "N"),
    ("R", "Forest Hills-71 Av", 12, STEINWAY, "N"),
]
TRAINS = {
    "normal": TO_CITY + TO_QUEENS,
    "evening": [
        ("W", "Whitehall St-South Ferry", 0, BROADWAY, "S"),
        ("R", "Bay Ridge-95 St", 4, STEINWAY, "S"),
        ("N", "Coney Island-Stillwell Av", 7, BROADWAY, "S"),
        ("N", "Astoria-Ditmars Blvd", 1, BROADWAY, "N"),
        ("R", "Forest Hills-71 Av", 3, STEINWAY, "N"),
        ("W", "Astoria-Ditmars Blvd", 6, BROADWAY, "N"),
    ],
    "night": [
        ("N", "Coney Island-Stillwell Av", 6, BROADWAY, "S"),
        ("R", "Bay Ridge-95 St", 9, STEINWAY, "S"),
        ("E", "Jamaica Center-Parsons/Archer", 4, STEINWAY, "N"),
        ("N", "Astoria-Ditmars Blvd", 15, BROADWAY, "N"),
    ],
}
TRAINS["rain"] = TRAINS["normal"]
TRAINS["snow"] = TRAINS["evening"]

# (base temp °F, daytime code, night code, rain hours from now)
WEATHER = {
    "normal": (54, 2, 1, ()),
    "evening": (61, 1, 0, ()),
    "rain":   (49, 3, 3, (2, 3, 4, 5)),
    "night":  (43, 0, 0, ()),
    "snow":   (28, 73, 71, ()),
}


def trains(now: datetime, scenario: str = "normal") -> list[Departure]:
    routes = mta_subway.data()["routes"]
    out = []
    for route, dest, mins, station, direction in TRAINS.get(scenario, TRAINS["normal"]):
        out.append(Departure(
            line=route.rstrip("X") if len(route) == 2 else route, destination=dest,
            depart_at=now + timedelta(minutes=mins, seconds=20),
            color=routes.get(route, {}).get("color"), express=route.endswith("X"),
            station=station, direction=direction,
        ))
    return out


def weather(now: datetime, scenario: str = "normal"):
    base, day_code, night_code, rain = WEATHER.get(scenario, WEATHER["normal"])
    offset = int(now.utcoffset().total_seconds()) if now.utcoffset() else 0
    start = now.replace(minute=0, second=0, microsecond=0)

    def temp_at(t):  # gentle daily curve peaking mid-afternoon
        return base + 8 * math.sin((t.hour - 9) / 24 * 2 * math.pi)

    def is_day(t):
        return 7 <= t.hour < 18

    hours = [start + timedelta(hours=h) for h in range(0, 30)]
    hourly = {
        "time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
        "temperature_2m": [round(temp_at(h), 1) for h in hours],
        "weather_code": [61 if i in rain else (day_code if is_day(h) else night_code)
                         for i, h in enumerate(hours)],
        "precipitation_probability": [80 if i in rain else (35 if i - 1 in rain else 5)
                                      for i in range(len(hours))],
        "is_day": [int(is_day(h)) for h in hours],
    }
    week_codes = [day_code, 61, 3, 0, 1, 80, 2] if scenario != "snow" else [73, 71, 3, 0, 1, 75, 2]
    week_shift = [0, -4, -2, 3, 5, 1, -1]
    daily = {
        "time": [(now.date() + timedelta(days=d)).isoformat() for d in range(7)],
        "weather_code": week_codes,
        "temperature_2m_max": [base + 8 + s for s in week_shift],
        "temperature_2m_min": [base - 8 + s - (d % 3) for d, s in enumerate(week_shift)],
        "precipitation_probability_max": [80 if rain else 10, 70, 25, 0, 5, 60, 15],
    }
    t = temp_at(now)
    data = {
        "utc_offset_seconds": offset,
        "current_units": {"wind_speed_10m": "mph"},
        "current": {
            "temperature_2m": round(t, 1),
            "apparent_temperature": round(t - 3, 1),
            "weather_code": hourly["weather_code"][0],
            "is_day": int(is_day(now)),
            "wind_speed_10m": 9,
        },
        "hourly": hourly,
        "daily": daily,
    }
    return parse_weather(data, now=now)
