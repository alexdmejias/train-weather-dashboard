"""Settings: built-in defaults, optionally overridden by config.toml.

The dashboard works with no config file at all. To change something, create
config.toml with only the keys you want to override, e.g.

    [weather]
    zip = "11101"

See config.example.toml for every option.
"""

from __future__ import annotations

import copy
import json
import math
import tomllib
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CACHE = Path.home() / ".cache" / "train-weather-dashboard" / "places.json"

DEFAULTS: dict = {
    "display": {
        "clock": "12h",               # "12h" or "24h"
        "units": "fahrenheit",        # "fahrenheit" or "celsius"
        "location_name": None,        # weather card label; default: neighbourhood of the zip
    },
    "weather": {
        "zip": "11106",               # US zip code …
        "latitude": None,             # … or exact coordinates (these win if set)
        "longitude": None,
        "refresh_minutes": 15,
    },
    "subway": {
        # Station names or ids (python3 tools/find_station.py <name>). Names
        # that exist more than once ("Broadway") pick the one nearest the zip.
        "stations": ["Steinway St", "Broadway"],
        "directions": ["S", "N"],     # sections, in display order; the first gets more rows
        "direction_labels": {         # section titles: "To Manhattan" / "To Queens"
            "S": "Manhattan",         # S = southbound platforms (Manhattan-bound from Astoria)
            "N": "Queens",            # N = northbound (Astoria-Ditmars, Forest Hills, Jamaica)
        },
        "routes": [],                 # only these lines, e.g. ["N", "W", "R"]; [] = all
        "walk_minutes": 0,            # hide trains you can't catch: 5, or {"Steinway St" = 6, "Broadway" = 4}
        "title": None,                # departures card title; default: the station names
        "max_rows": 5,
        "refresh_seconds": 30,
    },
    "alerts": {
        "subway": True,               # MTA delays, suspensions and planned work on your lines
        "weather": True,              # National Weather Service advisories/watches/warnings
        "upcoming_hours": 12,         # also show planned work starting within this many hours
        "rotate_seconds": 8,          # header banner cycles through alerts this often
    },
}

# Zips known offline so the defaults work before the network is up.
KNOWN_ZIPS = {
    "11106": (40.7621, -73.9319, "Astoria"),
}


def load(path: Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = path or ROOT / "config.toml"
    if path.exists():
        with open(path, "rb") as f:
            _merge(cfg, tomllib.load(f), path.name)
    return cfg


def _merge(base: dict, override: dict, where: str, prefix=""):
    for key, value in override.items():
        name = f"{prefix}{key}"
        if key not in base:
            print(f"{where}: ignoring unknown setting {name!r}")
        elif isinstance(base[key], dict) and isinstance(value, dict) and key != "walk_minutes":
            _merge(base[key], value, where, name + ".")
        else:
            base[key] = value


# ── location ──────────────────────────────────────────────────────────────

_place = None


def place(cfg: dict) -> tuple[float, float, str]:
    """(latitude, longitude, neighbourhood name) for the configured location.

    Unknown zips are looked up once with Open-Meteo's geocoder and cached on
    disk. Raises if that lookup fails (e.g. no network yet) — callers retry.
    """
    global _place
    if _place:
        return _place
    w = cfg["weather"]
    if w.get("latitude") is not None and w.get("longitude") is not None:
        _place = (float(w["latitude"]), float(w["longitude"]), "")
        return _place

    zip_code = str(w["zip"]).strip()
    if zip_code in KNOWN_ZIPS:
        _place = KNOWN_ZIPS[zip_code]
        return _place

    cache = _read_cache()
    if zip_code not in cache:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": zip_code, "count": 1, "countryCode": "US"}, timeout=15)
        r.raise_for_status()
        hits = r.json().get("results") or []
        if not hits:
            raise ValueError(f"Couldn't find zip code {zip_code} — set weather.latitude/longitude instead")
        cache[zip_code] = (hits[0]["latitude"], hits[0]["longitude"], hits[0].get("name", ""))
        _write_cache(cache)
    _place = tuple(cache[zip_code])
    return _place


def _read_cache() -> dict:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _write_cache(data: dict):
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data))
    except OSError:
        pass


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))
