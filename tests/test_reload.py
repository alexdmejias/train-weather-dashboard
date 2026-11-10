"""Picking up code changes while running.  Run: python3 -m pytest"""

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import dashboard  # noqa: E402

ROOT = dashboard.ROOT


def touch(path: Path, text: str, bump: int):
    path.write_text(text)
    t = path.stat().st_mtime + bump   # file systems with coarse timestamps: make the change visible
    os.utime(path, (t, t))


def test_watches_every_project_module():
    files = dashboard.project_files()
    for name in ("dashboard.py", "layout.py", "config.py", "sources/models.py", "sources/weather.py"):
        assert ROOT / name in files
    assert all(f.is_relative_to(ROOT) for f in files)     # not pygame, requests, the stdlib…


def test_drawing_modules_reload_others_restart(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    hot, data = tmp_path / "reload_hot_mod.py", tmp_path / "reload_data_mod.py"
    hot.write_text("VALUE = 1\n")
    data.write_text("FIELDS = ['wind']\n")
    importlib.invalidate_caches()
    import reload_hot_mod
    try:
        r = dashboard.Reloader([reload_hot_mod], watch=[data])
        r.INTERVAL = 0
        assert r.check() is None

        # a drawing module: reloaded in place, once its file has settled
        touch(hot, "VALUE = 2\n", 10)
        assert r.check() is None
        assert r.check() == "reload"
        assert reload_hot_mod.VALUE == 2
        assert r.check() is None

        # e.g. sources/models.py gained a field the new layout reads: restart
        touch(data, "FIELDS = ['wind', 'wind_dir']\n", 10)
        touch(hot, "VALUE = 3\n", 20)
        assert r.check() is None
        assert r.check() == "restart"
        assert reload_hot_mod.VALUE == 2      # not half-applied
    finally:
        sys.modules.pop("reload_hot_mod", None)


def test_waits_for_files_to_settle(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    data = tmp_path / "settle_mod.py"
    data.write_text("A = 1\n")
    r = dashboard.Reloader([], watch=[data])
    r.INTERVAL = 0
    for i in range(1, 4):                 # still being written
        touch(data, f"A = {i + 1}\n", 10 * i)
        assert r.check() is None
    assert r.check() == "restart"


def test_deleted_file_counts_as_a_change(tmp_path):
    gone = tmp_path / "gone_mod.py"
    gone.write_text("")
    r = dashboard.Reloader([], watch=[gone])
    r.INTERVAL = 0
    gone.unlink()
    assert r.check() is None
    assert r.check() == "restart"
