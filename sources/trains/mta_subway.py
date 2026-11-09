"""NYC Subway departures from the MTA's GTFS-realtime feeds (no API key needed).

Configured in the [subway] section (see config.py for defaults):

    [subway]
    stations = ["Steinway St", "Broadway"]   # names or ids (tools/find_station.py)
    directions = ["S"]                       # "N", "S" or both
    routes = []                              # only these lines, e.g. ["N", "W"]

Only the feeds for lines that actually stop at your station(s) are fetched.
Each train's destination is the last stop in its real-time trip.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from ..models import Departure

BASE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs"
FEEDS = {
    "": ["1", "2", "3", "4", "5", "6", "6X", "7", "7X", "GS"],
    "-ace": ["A", "C", "E", "H", "FS"],
    "-bdfm": ["B", "D", "F", "FX", "M"],
    "-g": ["G"],
    "-jz": ["J", "Z"],
    "-nqrw": ["N", "Q", "R", "W"],
    "-l": ["L"],
    "-si": ["SI"],
}
FEED_FOR_ROUTE = {r: BASE + suffix for suffix, routes in FEEDS.items() for r in routes}

_data = None


def data() -> dict:
    """Bundled station/route table (built by tools/build_stations.py)."""
    global _data
    if _data is None:
        path = Path(__file__).resolve().parents[2] / "data" / "subway.json"
        _data = json.loads(path.read_text())
    return _data


def station_name(stop_id: str) -> str:
    st = data()["stations"].get(stop_id.rstrip("NS")) or data()["stations"].get(stop_id)
    return st["name"] if st else stop_id


def resolve_stations(entries: list[str], near: tuple[float, float] | None = None) -> list[str]:
    """Turn station names and/or ids into ids.

    A name that matches several stations ("Broadway") resolves to the one
    nearest ``near`` (the configured zip code).
    """
    from config import distance_km

    stations = data()["stations"]
    ids = []
    for entry in entries:
        if entry in stations:
            ids.append(entry)
            continue
        key = _norm(entry)
        matches = [sid for sid, st in stations.items() if _norm(st["name"]) == key]
        if not matches:
            raise ValueError(f"No subway station called {entry!r} — try: python3 tools/find_station.py {entry!r}")
        if len(matches) > 1:
            if near is None:
                raise ValueError(f"{entry!r} matches several stations ({', '.join(matches)}) — use an id")
            # a complex (same name, a few metres apart) keeps every id; otherwise nearest wins
            matches.sort(key=lambda sid: distance_km(near, (stations[sid]["lat"], stations[sid]["lon"])))
            best = stations[matches[0]]
            matches = [sid for sid in matches
                       if distance_km((best["lat"], best["lon"]), (stations[sid]["lat"], stations[sid]["lon"])) < 0.3]
        ids.extend(m for m in matches if m not in ids)
    return ids


def _norm(name: str) -> str:
    return " ".join(name.lower().replace("–", "-").replace("street", "st").replace("avenue", "av").split())


def feeds_for(stations: list[str], routes: list[str] | None = None) -> list[str]:
    served = set()
    for s in stations:
        if s not in data()["stations"]:
            raise ValueError(f"Unknown station id {s!r} — look it up with tools/find_station.py")
        served.update(data()["stations"][s]["routes"])
    if routes:
        served &= {r for r in FEED_FOR_ROUTE if r.rstrip("X") in routes or r in routes}
    return sorted({FEED_FOR_ROUTE[r] for r in served if r in FEED_FOR_ROUTE})


def fetch(opts: dict, near: tuple[float, float] | None = None) -> list[Departure]:
    """``opts`` is the [subway] config section."""
    stations = resolve_stations(opts["stations"], near)
    urls = feeds_for(stations, opts.get("routes"))

    def get(url):
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.content

    with ThreadPoolExecutor(max_workers=len(urls) or 1) as pool:
        blobs = list(pool.map(get, urls))

    out = []
    for blob in blobs:
        out.extend(parse(blob, stations, opts.get("directions"), opts.get("routes")))
    return out


def parse(blob: bytes, stations, directions=None, routes=None, now=None) -> list[Departure]:
    try:
        from google.transit import gtfs_realtime_pb2
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("needs gtfs-realtime-bindings — see README") from e

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(blob)
    now = now or datetime.now(timezone.utc)
    want = {s + d for s in stations for d in (directions or ["N", "S"])}
    route_info = data()["routes"]
    out = []

    for ent in feed.entity:
        if not ent.HasField("trip_update"):
            continue
        tu = ent.trip_update
        route = tu.trip.route_id
        if routes and route not in routes and route.rstrip("X") not in routes:
            continue
        stus = tu.stop_time_update
        if not stus:
            continue
        terminal = stus[-1].stop_id
        for stu in stus:
            if stu.stop_id not in want:
                continue
            ev = stu.departure if stu.HasField("departure") and stu.departure.time else stu.arrival
            if not ev.time:
                continue
            at = datetime.fromtimestamp(ev.time, timezone.utc)
            if at < now or stu.stop_id == terminal:  # skip past trains and trains ending here
                continue
            info = route_info.get(route, {})
            label = info.get("name", route)
            out.append(Departure(
                line=label[:-1] if route.endswith("X") and label.endswith("X") else label,
                destination=station_name(terminal),
                depart_at=at,
                delay_min=None,  # the MTA feed doesn't report lateness
                color=info.get("color"),
                express=route.endswith("X"),
                station=station_name(stu.stop_id),
            ))
    return out
