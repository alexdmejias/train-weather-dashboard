#!/usr/bin/env python3
"""Rebuild data/subway.json from the MTA's static subway GTFS.

    python3 tools/build_stations.py                 # downloads the official zip
    python3 tools/build_stations.py path/to/gtfs_subway.zip

The result maps every station (parent stop id, e.g. "L08") to its name and the
routes that stop there, plus each route's official colour. The dashboard uses
it to pick which real-time feeds to download and to name each train's
destination. Re-run occasionally (the MTA updates the schedule a few times a
year); the station list itself rarely changes.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip"
OUT = Path(__file__).resolve().parent.parent / "data" / "subway.json"


def rows(z: zipfile.ZipFile, name: str):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def main():
    if len(sys.argv) > 1:
        z = zipfile.ZipFile(sys.argv[1])
    else:
        print(f"downloading {URL}")
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL, timeout=120).read()))

    stations, parent_of = {}, {}
    for r in rows(z, "stops.txt"):
        if r["location_type"] == "1":
            stations[r["stop_id"]] = {"name": r["stop_name"], "lat": float(r["stop_lat"]),
                                      "lon": float(r["stop_lon"]), "routes": set()}
        elif r["parent_station"]:
            parent_of[r["stop_id"]] = r["parent_station"]

    route_of_trip = {r["trip_id"]: r["route_id"] for r in rows(z, "trips.txt")}
    for r in rows(z, "stop_times.txt"):
        parent = parent_of.get(r["stop_id"], r["stop_id"])
        route = route_of_trip.get(r["trip_id"])
        if parent in stations and route:
            stations[parent]["routes"].add(route)

    routes = {}
    for r in rows(z, "routes.txt"):
        routes[r["route_id"]] = {"name": r["route_short_name"], "color": "#" + (r["route_color"] or "808183"),
                                 "text": "#" + (r["route_text_color"] or "FFFFFF")}

    for s in stations.values():
        s["routes"] = sorted(s["routes"])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"routes": routes, "stations": stations}, separators=(",", ":"), sort_keys=True))
    print(f"wrote {OUT} — {len(stations)} stations, {len(routes)} routes")


if __name__ == "__main__":
    main()
