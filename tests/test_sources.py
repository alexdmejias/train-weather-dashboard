"""Parser tests using real-world response shapes.  Run: python3 -m pytest"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from sources import mock, weather  # noqa: E402
from sources.trains import mta_subway  # noqa: E402

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


def _feed(now):
    from google.transit import gtfs_realtime_pb2 as g
    feed = g.FeedMessage()
    feed.header.gtfs_realtime_version = "1.0"
    ts = int(now.timestamp())

    def trip(route, stops):
        e = feed.entity.add(id=str(len(feed.entity)))
        e.trip_update.trip.route_id = route
        for stop_id, mins in stops:
            u = e.trip_update.stop_time_update.add(stop_id=stop_id)
            u.arrival.time = ts + mins * 60
            u.departure.time = ts + mins * 60

    trip("A", [("A41N", 4), ("A40N", 6), ("A02N", 40)])        # northbound A to Inwood
    trip("FX", [("A41S", 9), ("F27S", 20), ("D43S", 35)])       # express F to Coney Island
    trip("C", [("A42N", 1), ("A41N", -2), ("A09N", 30)])        # already left Jay St
    trip("C", [("A45S", 2), ("A41S", 12)])                      # terminates at Jay St → not shown
    trip("R", [("R29S", 3), ("R45S", 40)])                      # different station id
    return feed.SerializeToString()


def test_mta_subway_parse():
    now = datetime(2026, 11, 9, 8, 42, tzinfo=TZ)
    deps = mta_subway.parse(_feed(now), ["A41"], now=now)
    got = sorted((d.line, d.destination, d.express, round((d.depart_at - now).total_seconds() / 60)) for d in deps)
    assert got == [("A", "Inwood-207 St", False, 4), ("F", "Coney Island-Stillwell Av", True, 9)]
    assert all(d.delay_min is None and d.color for d in deps)
    # direction + route filters
    assert [d.line for d in mta_subway.parse(_feed(now), ["A41"], directions=["S"], now=now)] == ["F"]
    assert [d.line for d in mta_subway.parse(_feed(now), ["A41"], routes=["A"], now=now)] == ["A"]


def test_mta_feed_selection():
    assert mta_subway.feeds_for(["L08"]) == [mta_subway.BASE + "-l"]
    feeds = mta_subway.feeds_for(["A41", "R29"])
    assert {f.rsplit("gtfs", 1)[1] for f in feeds} == {"-ace", "-bdfm", "-nqrw"}
    assert mta_subway.feeds_for(["A41"], routes=["F"]) == [mta_subway.BASE + "-bdfm"]


def test_mock_scenarios_render_data():
    now = datetime(2026, 11, 9, 8, 42, tzinfo=TZ)
    for s in ("normal", "evening", "rain", "night", "snow"):
        assert mock.trains(now, s)
        w = mock.weather(now, s)
        assert len(w.hourly) >= 5 and len(w.daily) == 7


def test_defaults_work_without_config_file(tmp_path):
    cfg = config.load(tmp_path / "missing.toml")
    assert cfg["weather"]["zip"] == "11106"
    lat, lon, name = config.place(cfg)
    assert name == "Astoria" and 40.7 < lat < 40.8
    ids = mta_subway.resolve_stations(cfg["subway"]["stations"], (lat, lon))
    assert ids == ["G19", "R05"]  # Steinway St (M/R) and the Astoria Broadway (N/W), not the G's


def test_config_file_overrides_only_what_it_sets(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[subway]\nwalk_minutes = { "Steinway St" = 7 }\n[display]\nclock = "24h"\n')
    cfg = config.load(f)
    assert cfg["subway"]["walk_minutes"] == {"Steinway St": 7}
    assert cfg["display"]["clock"] == "24h"
    assert cfg["subway"]["stations"] == ["Steinway St", "Broadway"]  # untouched default


def test_station_names_resolve_by_proximity():
    jay = (40.6924, -73.9874)
    assert mta_subway.resolve_stations(["Broadway"], jay) == ["G30"]          # Williamsburg G
    assert set(mta_subway.resolve_stations(["Jay St-MetroTech"], jay)) == {"A41", "R29"}  # whole complex
