"""Plain data types shared by the data sources and the layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Departure:
    line: str                      # short label shown in the badge, e.g. "A" or "S8"
    destination: str               # where the train is heading
    depart_at: datetime | None     # expected (real-time) departure, timezone aware
    delay_min: int = 0             # minutes late; 0 = on time, negative = early
    platform: str | None = None    # track / platform, if the feed provides it
    cancelled: bool = False
    color: str | None = None       # badge colour override, "#RRGGBB"


@dataclass
class HourForecast:
    time: datetime
    temp: float
    code: int                      # WMO weather code
    precip_prob: int
    is_day: bool


@dataclass
class DayForecast:
    day: date
    code: int
    high: float
    low: float
    precip_prob: int


@dataclass
class Weather:
    temp: float
    feels_like: float
    code: int
    is_day: bool
    wind: float
    high: float
    low: float
    hourly: list[HourForecast] = field(default_factory=list)
    daily: list[DayForecast] = field(default_factory=list)
    unit: str = "°"
    wind_unit: str = "mph"
