"""Plain data types shared by the data sources and the layout."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Departure:
    line: str                      # short label shown in the badge, e.g. "A" or "S8"
    destination: str               # where the train is heading
    depart_at: datetime | None     # expected (real-time) departure, timezone aware
    delay_min: int | None = None   # minutes late; None = feed doesn't say (NYC Subway)
    platform: str | None = None    # track / platform, if the feed provides it
    cancelled: bool = False
    color: str | None = None       # badge colour, "#RRGGBB"
    express: bool = False          # drawn as a diamond badge
    station: str | None = None     # which of your stations it leaves from
    direction: str | None = None   # "N" or "S" (MTA platform direction)


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
    # extra detail for the Today card (None = the feed didn't say)
    humidity: int | None = None    # %
    wind_dir: int | None = None    # degrees the wind blows FROM (0 = north)
    uv_max: float | None = None    # today's peak UV index
    sunrise: datetime | None = None
    sunset: datetime | None = None
    precip_prob: int | None = None # today's highest chance of rain/snow, %


@dataclass
class Alert:
    source: str                    # "subway" or "weather"
    title: str                     # one line; may contain [N]-style route tokens
    body: str = ""                 # longer description
    level: str = "warning"         # "severe" (red), "warning" (amber) or "info"
    routes: list[str] = field(default_factory=list)   # affected lines (subway)
    starts: datetime | None = None
    ends: datetime | None = None

    def active(self, now: datetime) -> bool:
        return (self.starts is None or self.starts <= now) and (self.ends is None or now < self.ends)
