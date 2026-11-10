"""Draw to the Linux framebuffer (/dev/fb0) and read touch input from evdev.

Used on the Pi instead of SDL's kmsdrm driver, which needs a working
EGL/OpenGL stack and fails on some Pi + OS combinations ("EGL not
initialized", e.g. Debian trixie). pygame runs headless
(SDL_VIDEODRIVER=dummy); each frame is converted to the framebuffer's pixel
format and copied in. No GPU needed.
"""

from __future__ import annotations

import fcntl
import mmap
import os
import struct
import threading
from pathlib import Path

import pygame

KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0, 1


def available(dev: str = "/dev/fb0") -> bool:
    return Path(dev).exists()


class Framebuffer:
    def __init__(self, dev: str = "/dev/fb0", sysfs: str | None = None):
        sys_dir = Path(sysfs or f"/sys/class/graphics/{Path(dev).name}")
        self.w, self.h = (int(v) for v in (sys_dir / "virtual_size").read_text().split(","))
        self.bpp = int((sys_dir / "bits_per_pixel").read_text())
        stride_file = sys_dir / "stride"
        self.stride = int(stride_file.read_text()) if stride_file.exists() else self.w * self.bpp // 8
        if self.bpp not in (16, 32):
            raise RuntimeError(f"{dev}: unsupported {self.bpp} bits per pixel")
        self.size = self.stride * self.h
        self._fd = os.open(dev, os.O_RDWR)
        self._mem = mmap.mmap(self._fd, self.size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)
        masks = (0xF800, 0x07E0, 0x001F, 0) if self.bpp == 16 else (0xFF0000, 0xFF00, 0xFF, 0)
        self._out = pygame.Surface((self.w, self.h), 0, self.bpp, masks)  # fb's native format

    def show(self, screen: pygame.Surface):
        """Copy a surface of the framebuffer's size (hardware.display.Presenter
        has already rotated/scaled it) onto the screen."""
        self._out.blit(screen, (0, 0))
        pitch = self._out.get_pitch()
        raw = self._out.get_buffer().raw
        if pitch == self.stride:
            self._mem[: self.size] = raw[: self.size]
        else:
            row = self.w * self.bpp // 8
            for y in range(self.h):
                self._mem[y * self.stride: y * self.stride + row] = raw[y * pitch: y * pitch + row]

    def close(self):
        self._mem.close()
        os.close(self._fd)


class Console:
    """Put the text console in graphics mode so its cursor and login prompt
    don't draw over the dashboard. Needs CAP_SYS_TTY_CONFIG (see the service);
    harmless if it isn't allowed."""

    def __init__(self, tty: str = "/dev/tty0"):
        self._fd = None
        try:
            self._fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY)
            fcntl.ioctl(self._fd, KDSETMODE, KD_GRAPHICS)
        except OSError as e:
            print(f"[display] can't hide the console ({e}); text may show through", flush=True)
            if self._fd is not None:
                os.close(self._fd)
            self._fd = None

    def restore(self):
        if self._fd is not None:
            try:
                fcntl.ioctl(self._fd, KDSETMODE, KD_TEXT)
            finally:
                os.close(self._fd)
                self._fd = None


# ── touch ─────────────────────────────────────────────────────────────────

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y = 0, 1
BTN_TOUCH = 0x14A
EVENT = struct.Struct("llHHi")     # struct input_event (native long = kernel long)
ABSINFO = struct.Struct("6i")


def _eviocgabs(axis: int) -> int:
    return (2 << 30) | (ABSINFO.size << 16) | (ord("E") << 8) | (0x40 + axis)


def _bits(words: str) -> int:
    n = struct.calcsize("l") * 8
    value = 0
    for w in words.split():
        value = (value << n) | int(w, 16)
    return value


def touch_devices(proc: str = "/proc/bus/input/devices") -> list[str]:
    """/dev/input/eventN for every device with absolute X/Y and BTN_TOUCH."""
    found = []
    try:
        blocks = Path(proc).read_text().split("\n\n")
    except OSError:
        return found
    for block in blocks:
        info = {}
        for line in block.splitlines():
            if line.startswith("B: "):
                k, _, v = line[3:].partition("=")
                info[k] = v
            elif line.startswith("H: Handlers="):
                info["handlers"] = line.split("=", 1)[1].split()
        absb, keyb = _bits(info.get("ABS", "0")), _bits(info.get("KEY", "0"))
        if absb & (1 << ABS_X) and absb & (1 << ABS_Y) and keyb & (1 << BTN_TOUCH):
            found += [f"/dev/input/{h}" for h in info.get("handlers", []) if h.startswith("event")]
    return found


class Touch(threading.Thread):
    """Turns taps into pygame MOUSEBUTTONDOWN events at physical screen
    coordinates (the dashboard maps them through Presenter.to_canvas)."""

    def __init__(self, dev: str, screen_size, swap_xy=False, invert_x=False, invert_y=False):
        super().__init__(daemon=True)
        self.dev, self.screen_size = dev, screen_size
        self.swap_xy, self.invert_x, self.invert_y = swap_xy, invert_x, invert_y

    def run(self):
        try:
            fd = os.open(self.dev, os.O_RDONLY)
            ranges = {}
            for axis in (ABS_X, ABS_Y):
                buf = fcntl.ioctl(fd, _eviocgabs(axis), bytes(ABSINFO.size))
                _, lo, hi, *_ = ABSINFO.unpack(buf)
                ranges[axis] = (lo, hi)
        except OSError as e:
            print(f"[touch] {self.dev}: {e}", flush=True)
            return
        print(f"[touch] using {self.dev} (x {ranges[ABS_X]}, y {ranges[ABS_Y]})", flush=True)
        raw = {ABS_X: 0, ABS_Y: 0}
        tapped = False
        while True:
            data = os.read(fd, EVENT.size * 64)
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, typ, code, value = EVENT.unpack_from(data, i)
                if typ == EV_ABS and code in raw:
                    raw[code] = value
                elif typ == EV_KEY and code == BTN_TOUCH and value == 1:
                    tapped = True
                elif typ == EV_SYN and tapped:  # coordinates for this report are complete
                    tapped = False
                    pygame.event.post(pygame.event.Event(
                        pygame.MOUSEBUTTONDOWN, pos=self._map(raw, ranges), button=1, touch=False))

    def _map(self, raw, ranges):
        fx, fy = ((raw[a] - lo) / max(1, hi - lo) for a, (lo, hi) in ranges.items())
        if self.swap_xy:
            fx, fy = fy, fx
        if self.invert_x:
            fx = 1 - fx
        if self.invert_y:
            fy = 1 - fy
        return (int(fx * self.screen_size[0]), int(fy * self.screen_size[1]))
