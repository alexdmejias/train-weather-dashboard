"""Departures from a GTFS-realtime TripUpdates feed (most transit agencies).

Needs:  pip install gtfs-realtime-bindings   (see README for the Pi)

Example config:

    [trains]
    provider = "gtfs_rt"

    [trains.gtfs_rt]
    feed_urls = ["https://example-agency.org/gtfs-rt/tripupdates"]
    stop_ids  = ["123N", "123S"]           # both platforms of your station
    headers   = { "x-api-key" = "..." }     # only if your agency needs a key

    # Feeds rarely include a destination name, so label each stop/platform:
    [trains.gtfs_rt.destinations]
    "123N" = "Uptown"
    "123S" = "Downtown"
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..models import Departure


def fetch(cfg: dict) -> list[Departure]:
    try:
        from google.transit import gtfs_realtime_pb2
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("gtfs_rt provider needs: pip install gtfs-realtime-bindings") from e

    opts = cfg["gtfs_rt"]
    stops = set(opts["stop_ids"])
    labels = opts.get("destinations", {})
    now = datetime.now(timezone.utc)
    out = []

    for url in opts["feed_urls"]:
        resp = requests.get(url, headers=opts.get("headers", {}), timeout=15)
        resp.raise_for_status()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(resp.content)

        for ent in feed.entity:
            if not ent.HasField("trip_update"):
                continue
            tu = ent.trip_update
            cancelled = tu.trip.schedule_relationship == tu.trip.CANCELED
            for stu in tu.stop_time_update:
                if stu.stop_id not in stops:
                    continue
                ev = stu.departure if stu.HasField("departure") else stu.arrival
                if not ev.time:
                    continue
                at = datetime.fromtimestamp(ev.time, timezone.utc)
                if at < now:
                    continue
                out.append(Departure(
                    line=tu.trip.route_id,
                    destination=labels.get(stu.stop_id, stu.stop_id),
                    depart_at=at,
                    delay_min=round(ev.delay / 60) if ev.HasField("delay") else 0,
                    cancelled=cancelled or stu.schedule_relationship == stu.SKIPPED,
                ))
    return out
