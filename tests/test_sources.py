"""Parser tests using trimmed real-world response shapes.  Run: python3 -m pytest"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sources import mock, weather  # noqa: E402
from sources.trains import transport_rest  # noqa: E402

TZ = timezone(timedelta(hours=-5))


def test_open_meteo_parse():
    data = {
        "utc_offset_seconds": -18000,
        "current_units": {"wind_speed_10m": "mp/h"},
        "current": {"temperature_2m": 51.3, "apparent_temperature": 48.0,
                    "weather_code": 2, "is_day": 1, "wind_speed_10m": 7.4},
        "hourly": {
            "time": ["2026-11-09T07:00", "2026-11-09T08:00", "2026-11-09T09:00"],
            "temperature_2m": [48.0, 50.1, 52.2],
            "weather_code": [1, 2, 61],
            "precipitation_probability": [0, 10, None],
            "is_day": [1, 1, 1],
        },
        "daily": {
            "time": ["2026-11-09", "2026-11-10"],
            "weather_code": [2, 61],
            "temperature_2m_max": [60.0, 55.0],
            "temperature_2m_min": [44.0, 41.0],
            "precipitation_probability_max": [10, 70],
        },
    }
    w = weather.parse(data, now=datetime(2026, 11, 9, 8, 30, tzinfo=TZ))
    assert w.wind_unit == "mph"
    assert (w.high, w.low) == (60.0, 44.0)
    # 07:00 is fully in the past and dropped; the current hour (08:00) stays
    assert [h.time.hour for h in w.hourly] == [8, 9]
    assert w.hourly[1].precip_prob == 0  # None → 0
    assert w.daily[1].precip_prob == 70


def test_transport_rest_parse():
    data = {"departures": [
        {"when": "2026-11-09T08:44:00+01:00", "plannedWhen": "2026-11-09T08:40:00+01:00",
         "delay": 240, "platform": "3", "direction": "Spandau", "line": {"name": "S5"}},
        {"when": None, "plannedWhen": "2026-11-09T08:50:00+01:00", "delay": None,
         "cancelled": True, "plannedPlatform": "4", "direction": "Ostkreuz", "line": {"name": "S7"}},
    ]}
    a, b = transport_rest.parse(data)
    assert (a.line, a.destination, a.delay_min, a.platform) == ("S5", "Spandau", 4, "3")
    assert b.cancelled and b.platform == "4" and b.depart_at.minute == 50


def test_mock_scenarios_render_data():
    now = datetime(2026, 11, 9, 8, 42, tzinfo=TZ)
    for s in ("normal", "delays", "rain", "night", "snow"):
        assert mock.trains(now, s)
        w = mock.weather(now, s)
        assert len(w.hourly) >= 5 and len(w.daily) == 7
