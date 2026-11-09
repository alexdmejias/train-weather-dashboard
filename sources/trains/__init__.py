"""Train departure providers.

Each provider module exposes ``fetch(cfg: dict) -> list[Departure]``.
Pick one with ``[trains] provider = "..."`` in config.toml. To support a new
API, add a module here with a ``fetch`` function and register it below.
"""

from __future__ import annotations

import importlib

PROVIDERS = {
    "mock": "sources.trains.mock",
    "gtfs_rt": "sources.trains.gtfs_rt",
    "transport_rest": "sources.trains.transport_rest",
}


def get_provider(name: str):
    try:
        return importlib.import_module(PROVIDERS[name])
    except KeyError:
        raise SystemExit(f"Unknown train provider {name!r}. Choose one of: {', '.join(PROVIDERS)}")


def apply_line_colors(departures, colors: dict):
    for d in departures:
        if not d.color:
            d.color = colors.get(d.line)
    return departures
