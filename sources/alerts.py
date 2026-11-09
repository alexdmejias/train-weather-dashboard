"""Service alerts (MTA) and weather alerts (National Weather Service).

Both are free and need no API key.

* Subway: the MTA's GTFS-realtime alerts feed — delays, suspensions,
  planned work. Filtered to the lines that stop at your stations (and any
  alert naming one of your stations directly).
* Weather: api.weather.gov active alerts for your location — advisories,
  watches and warnings (US only).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

from .models import Alert

SUBWAY_FEED = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/camsys%2Fsubway-alerts"
NWS = "https://api.weather.gov/alerts/active"
# api.weather.gov asks every client to identify itself with a User-Agent
HEADERS = {"User-Agent": "train-weather-dashboard/1.0",
           "Accept": "application/geo+json"}

LEVEL_ORDER = {"severe": 0, "warning": 1, "info": 2}


# ── subway ────────────────────────────────────────────────────────────────

def fetch_subway(station_ids: list[str], route_filter: list[str] | None = None,
                 upcoming_hours: float = 12) -> list[Alert]:
    r = requests.get(SUBWAY_FEED, timeout=20)
    r.raise_for_status()
    return parse_subway(r.content, station_ids, route_filter, upcoming_hours)


def parse_subway(blob: bytes, station_ids, route_filter=None, upcoming_hours=12, now=None) -> list[Alert]:
    from google.transit import gtfs_realtime_pb2

    from .trains import mta_subway

    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(hours=upcoming_hours)
    data = mta_subway.data()
    names = {rid: info["name"] for rid, info in data["routes"].items()}

    # lines that matter: every route stopping at our stations (minus filtered-out ones)
    ours = set()
    for sid in station_ids:
        ours.update(data["stations"].get(sid, {}).get("routes", []))
    if route_filter:
        ours = {r for r in ours if r in route_filter or r.rstrip("X") in route_filter}

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(blob)
    out = []
    for ent in feed.entity:
        if not ent.HasField("alert"):
            continue
        a = ent.alert

        affected, hits_station = set(), False
        for ie in a.informed_entity:
            if ie.route_id and ie.route_id in ours:
                affected.add(_line_name(ie.route_id, names))
            if ie.stop_id and ie.stop_id.rstrip("NS") in station_ids:
                hits_station = True
        if not affected and not hits_station:
            continue

        # the period that is current, or the next one to start soon
        period = _relevant_period(a.active_period, now, horizon)
        if period is False:
            continue
        starts, ends = period

        title = _translation(a.header_text)
        if not title:
            continue
        out.append(Alert(
            source="subway",
            title=title,
            body=_translation(a.description_text),
            level="warning" if starts is None or starts <= now else "info",
            routes=sorted(affected, key=_route_sort),
            starts=starts, ends=ends,
        ))
    return _dedupe(out)


def _line_name(route_id, names):
    n = names.get(route_id, route_id)
    return n[:-1] if route_id.endswith("X") and n.endswith("X") else n


def _relevant_period(periods, now, horizon):
    """(starts, ends) of the current/next period, None for open ends, or False if not relevant."""
    if not periods:
        return None, None
    best = None
    for p in periods:
        s = datetime.fromtimestamp(p.start, timezone.utc) if p.start else None
        e = datetime.fromtimestamp(p.end, timezone.utc) if p.end else None
        if e is not None and e <= now:
            continue
        if s is not None and s > horizon:
            continue
        if best is None or (s or now) < (best[0] or now):
            best = (s, e)
    return best if best else False


def _translation(ts) -> str:
    """Plain-English text from a GTFS-rt TranslatedString (skip the HTML variant)."""
    plain = [t.text for t in ts.translation if t.language in ("", "en")]
    text = plain[0] if plain else (ts.translation[0].text if ts.translation else "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _route_sort(name):
    return (not name.isdigit(), name)


def _dedupe(alerts):
    seen, out = set(), []
    for a in alerts:
        if a.title not in seen:
            seen.add(a.title)
            out.append(a)
    return out


# ── weather ───────────────────────────────────────────────────────────────

def fetch_weather(lat: float, lon: float) -> list[Alert]:
    r = requests.get(NWS, params={"point": f"{lat:.4f},{lon:.4f}"}, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return parse_nws(r.json())


def parse_nws(data: dict, now: datetime | None = None) -> list[Alert]:
    now = now or datetime.now(timezone.utc)
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        if p.get("status") != "Actual" or p.get("messageType") == "Cancel":
            continue
        ends = _iso(p.get("ends")) or _iso(p.get("expires"))
        if ends and ends <= now:
            continue
        severity = p.get("severity", "Unknown")
        level = "severe" if severity in ("Extreme", "Severe") else "warning" if severity == "Moderate" else "info"
        body = " ".join(x for x in (p.get("description"), p.get("instruction")) if x)
        out.append(Alert(
            source="weather",
            title=p.get("event") or p.get("headline") or "Weather alert",
            body=re.sub(r"\s+", " ", body).strip(),
            level=level,
            starts=_iso(p.get("onset")) or _iso(p.get("effective")),
            ends=ends,
        ))
    return _dedupe(out)


def _iso(s):
    return datetime.fromisoformat(s) if s else None


def ordered(alerts: list[Alert], now: datetime) -> list[Alert]:
    """Most important first: severe weather, then current problems, then upcoming."""
    return sorted(alerts, key=lambda a: (LEVEL_ORDER.get(a.level, 3), not a.active(now), a.source != "weather"))
