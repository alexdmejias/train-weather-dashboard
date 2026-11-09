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
    assert {d.line: d.direction for d in deps} == {"A": "N", "F": "S"}
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


def test_rows_split_between_directions():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import layout
    assert layout._allocate([5, 4], 5) == [3, 2]      # Manhattan-bound gets more
    assert layout._allocate([1, 4], 5) == [1, 4]      # unused rows go to the other side
    assert layout._allocate([6, 0], 5) == [5, 0]
    assert layout._allocate([2], 5) == [2]


# ── alerts ────────────────────────────────────────────────────────────────

def _alerts_feed(now):
    from google.transit import gtfs_realtime_pb2 as g
    feed = g.FeedMessage()
    feed.header.gtfs_realtime_version = "1.0"
    ts = int(now.timestamp())

    def alert(header, routes=(), stops=(), periods=((None, None),)):
        a = feed.entity.add(id=str(len(feed.entity))).alert
        for r in routes:
            a.informed_entity.add(agency_id="MTASBWY", route_id=r)
        for st in stops:
            a.informed_entity.add(agency_id="MTASBWY", stop_id=st)
        for s, e in periods:
            p = a.active_period.add()
            if s is not None:
                p.start = ts + s * 3600
            if e is not None:
                p.end = ts + e * 3600
        a.header_text.translation.add(text=header, language="en")
        a.header_text.translation.add(text=f"<p>{header}</p>", language="en-html")
        a.description_text.translation.add(text="Details here.", language="en")

    alert("[N] [W] delays", routes=["N", "W"], periods=((-1, None),))           # now
    alert("[R] skips stops", routes=["R"], periods=((3, 6),))                   # starts in 3 h
    alert("[M] weekend work", routes=["M"], periods=((48, 60),))                # too far ahead
    alert("[7] delays", routes=["7"])                                           # not our line
    alert("Steinway St elevator", stops=["G19N"])                               # our station
    alert("[N] old problem", routes=["N"], periods=((-5, -1),))                 # already over
    return feed.SerializeToString()


def test_subway_alerts_filtered_to_our_lines_and_time():
    from sources import alerts
    now = datetime(2026, 11, 9, 8, 17, tzinfo=TZ)
    got = alerts.parse_subway(_alerts_feed(now), ["G19", "R05"], now=now)
    titles = {a.title: a for a in got}
    assert set(titles) == {"[N] [W] delays", "[R] skips stops", "Steinway St elevator"}
    assert titles["[N] [W] delays"].routes == ["N", "W"] and titles["[N] [W] delays"].level == "warning"
    assert titles["[R] skips stops"].level == "info" and not titles["[R] skips stops"].active(now)
    assert titles["[N] [W] delays"].body == "Details here."
    # a routes filter drops lines you don't ride
    got = alerts.parse_subway(_alerts_feed(now), ["G19", "R05"], route_filter=["N", "W"], now=now)
    assert {a.title for a in got} == {"[N] [W] delays", "Steinway St elevator"}


def test_nws_alerts():
    from sources import alerts
    now = datetime(2026, 11, 9, 8, 17, tzinfo=TZ)
    data = {"features": [
        {"properties": {"status": "Actual", "messageType": "Alert", "event": "Flood Advisory",
                        "severity": "Moderate", "description": "Minor  flooding.", "instruction": "Avoid roads.",
                        "onset": "2026-11-09T07:00:00-05:00", "ends": "2026-11-09T13:00:00-05:00"}},
        {"properties": {"status": "Actual", "messageType": "Update", "event": "Wind Warning",
                        "severity": "Severe", "expires": "2026-11-09T20:00:00-05:00"}},
        {"properties": {"status": "Test", "event": "Test Message", "severity": "Minor"}},
        {"properties": {"status": "Actual", "messageType": "Alert", "event": "Old Advisory",
                        "severity": "Minor", "ends": "2026-11-09T06:00:00-05:00"}},
    ]}
    got = alerts.parse_nws(data, now=now)
    assert [(a.title, a.level) for a in got] == [("Flood Advisory", "warning"), ("Wind Warning", "severe")]
    assert got[0].body == "Minor flooding. Avoid roads."
    # severe weather outranks everything else
    assert alerts.ordered(got, now)[0].title == "Wind Warning"
