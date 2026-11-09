"""Departures from a transport.rest / HAFAS-style API (Germany, much of Europe).

Example config:

    [trains]
    provider = "transport_rest"

    [trains.transport_rest]
    base_url = "https://v6.db.transport.rest"
    stop_id = "8011160"          # Berlin Hbf — look yours up via /locations?query=...
    products = ["suburban", "regional"]   # optional filter
"""

from __future__ import annotations

from datetime import datetime

import requests

from ..models import Departure


def fetch(cfg: dict) -> list[Departure]:
    opts = cfg["transport_rest"]
    base = opts.get("base_url", "https://v6.db.transport.rest").rstrip("/")
    params = {"duration": opts.get("duration", 90), "results": 20, "remarks": "false"}
    for p in opts.get("products", []):
        params[p] = "true"
    if opts.get("products"):
        # transport.rest enables every product by default; switch off the rest
        for p in ("nationalExpress", "national", "regionalExpress", "regional",
                  "suburban", "bus", "ferry", "subway", "tram", "taxi"):
            params.setdefault(p, "false")
    resp = requests.get(f"{base}/stops/{opts['stop_id']}/departures", params=params, timeout=15)
    resp.raise_for_status()
    return parse(resp.json())


def parse(data) -> list[Departure]:
    rows = data["departures"] if isinstance(data, dict) else data
    out = []
    for d in rows:
        when = d.get("when") or d.get("plannedWhen")
        out.append(Departure(
            line=(d.get("line") or {}).get("name", "?"),
            destination=d.get("direction") or "",
            depart_at=datetime.fromisoformat(when) if when else None,
            delay_min=round((d.get("delay") or 0) / 60),
            platform=d.get("platform") or d.get("plannedPlatform"),
            cancelled=bool(d.get("cancelled")),
        ))
    return out
