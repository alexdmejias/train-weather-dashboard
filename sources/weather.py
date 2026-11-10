"""Weather from Open-Meteo (https://open-meteo.com) — free, no API key."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import requests

from .models import DayForecast, HourForecast, Weather

API = "https://api.open-meteo.com/v1/forecast"


def fetch(latitude: float, longitude: float, units: str = "fahrenheit") -> Weather:
    imperial = units == "fahrenheit"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m,"
                   "wind_direction_10m,relative_humidity_2m",
        "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "uv_index_max,sunrise,sunset",
        "forecast_days": 7,
        "timezone": "auto",
        "temperature_unit": "fahrenheit" if imperial else "celsius",
        "wind_speed_unit": "mph" if imperial else "kmh",
    }
    resp = requests.get(API, params=params, timeout=15)
    resp.raise_for_status()
    return parse(resp.json())


def parse(data: dict, now: datetime | None = None) -> Weather:
    """Turn an Open-Meteo response into a Weather object."""
    tz = timezone(timedelta(seconds=data.get("utc_offset_seconds", 0)))
    now = now or datetime.now(tz)
    cur, hourly, daily = data["current"], data["hourly"], data["daily"]

    hours = []
    for i, t in enumerate(hourly["time"]):
        ts = datetime.fromisoformat(t).replace(tzinfo=tz)
        if ts + timedelta(hours=1) <= now:
            continue  # already past
        hours.append(HourForecast(
            time=ts,
            temp=hourly["temperature_2m"][i],
            code=hourly["weather_code"][i],
            precip_prob=hourly["precipitation_probability"][i] or 0,
            is_day=bool(hourly["is_day"][i]),
        ))

    days = [
        DayForecast(
            day=date.fromisoformat(d),
            code=daily["weather_code"][i],
            high=daily["temperature_2m_max"][i],
            low=daily["temperature_2m_min"][i],
            precip_prob=daily["precipitation_probability_max"][i] or 0,
        )
        for i, d in enumerate(daily["time"])
    ]

    def today(key):   # today's value of an optional daily field
        values = daily.get(key) or [None]
        return values[0]

    def clock(value):
        return datetime.fromisoformat(value).replace(tzinfo=tz) if value else None

    units = data.get("current_units", {})
    return Weather(
        temp=cur["temperature_2m"],
        feels_like=cur["apparent_temperature"],
        code=cur["weather_code"],
        is_day=bool(cur["is_day"]),
        wind=cur["wind_speed_10m"],
        high=days[0].high if days else cur["temperature_2m"],
        low=days[0].low if days else cur["temperature_2m"],
        hourly=hours,
        daily=days,
        # Open-Meteo reports mph as "mp/h"
        wind_unit=units.get("wind_speed_10m", "mph").replace("mp/h", "mph"),
        humidity=cur.get("relative_humidity_2m"),
        wind_dir=cur.get("wind_direction_10m"),
        uv_max=today("uv_index_max"),
        sunrise=clock(today("sunrise")),
        sunset=clock(today("sunset")),
        precip_prob=days[0].precip_prob if days else None,
    )
