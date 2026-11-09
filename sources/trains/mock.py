"""Fake departures for designing offline (``provider = "mock"``)."""

from __future__ import annotations

from datetime import datetime

from .. import mock


def fetch(cfg: dict):
    return mock.trains(datetime.now().astimezone(), cfg.get("mock_scenario", "normal"))
