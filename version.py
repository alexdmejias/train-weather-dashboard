"""Which build is on screen, and whether it's the latest one.

The build is the git commit the dashboard started from (the Pi runs a clone
of the `deploy` branch, see docs/remote-updates.md). "Latest" comes from the
auto-updater: deploy/update.sh runs `git fetch origin deploy` every ~5 min,
which leaves the newest tested commit in .git/FETCH_HEAD, so comparing that
to the running commit needs no network access of our own.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass
class Build:
    sha: str              # full commit hash
    number: int | None    # commits since the start of the repo: grows with every release
    date: datetime | None
    subject: str = ""     # first line of the commit message

    @property
    def short(self) -> str:
        return self.sha[:7]

    @property
    def label(self) -> str:
        return f"Build {self.number}" if self.number else self.short


@dataclass
class UpdateStatus:
    state: str                     # "latest", "pending", "failed", "unknown" or "dev"
    latest: str | None = None      # newest commit the updater has seen
    checked: datetime | None = None  # when the updater last looked

    @property
    def message(self) -> str:
        return {
            "latest": "Up to date",
            "pending": f"Update {self.latest[:7] if self.latest else ''} installing soon",
            "failed": f"Update {self.latest[:7] if self.latest else ''} failed · rolled back",
            "unknown": "Auto-update hasn't checked yet",
            "dev": "Development copy · no auto-update",
        }[self.state]


def _git(*args, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          timeout=10, check=True).stdout.strip()


def current(root: Path = ROOT) -> Build | None:
    """The commit this process is running. Read once at start-up: the updater
    restarts the dashboard after checking out a new commit."""
    if not (root / ".git").exists():
        return None
    try:
        sha, ts, subject = _git("log", "-1", "--format=%H%n%ct%n%s", root=root).split("\n", 2)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    try:
        number = int(_git("rev-list", "--count", "HEAD", root=root))
    except (OSError, subprocess.SubprocessError, ValueError):
        number = None
    return Build(sha=sha, number=number, date=datetime.fromtimestamp(int(ts)).astimezone(), subject=subject)


def update_status(build: Build | None, root: Path = ROOT) -> UpdateStatus:
    """Compare the running build with what the auto-updater last fetched.
    Only reads two small files, so it's cheap to call every so often."""
    git = root / ".git"
    if build is None:
        return UpdateStatus("dev")
    fetch_head = git / "FETCH_HEAD"
    try:
        latest = fetch_head.read_text().split(None, 1)[0]
        checked = datetime.fromtimestamp(fetch_head.stat().st_mtime).astimezone()
    except (OSError, IndexError):
        return UpdateStatus("unknown")
    if latest == build.sha:
        return UpdateStatus("latest", latest, checked)
    try:
        bad = (git / "update-bad-rev").read_text().strip()
    except OSError:
        bad = ""
    return UpdateStatus("failed" if bad == latest else "pending", latest, checked)


def local_ip() -> str | None:
    """This device's address on the local network (for ssh). Sends nothing:
    connecting a UDP socket only picks the outgoing interface."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))   # TEST-NET address, never actually contacted
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
