"""Gets the 800×480 dashboard onto whatever screen is attached.

The layout always draws on an 800×480 canvas. This module rotates and scales
that canvas to the real display:

* Elecrow 5" (HDMI): already 800×480 landscape → shown as-is.
* HyperPixel 4.0 (DPI): the panel is natively 480×800 portrait. Rather than
  relying on the OS to rotate (the rotation set in the desktop's Screen
  Configuration doesn't apply to an app drawing straight to the display),
  we rotate the image ourselves.
* Anything else: scaled to fit, centred.

It also turns the backlight off/on for sleep mode where the OS allows it.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pygame


class Presenter:
    def __init__(self, screen: pygame.Surface, size=(800, 480), rotate="auto", flip=None):
        self.screen = screen
        self.flip = flip or pygame.display.flip  # framebuffer mode copies to /dev/fb0 instead
        self.canvas = pygame.Surface(size)
        sw, sh = screen.get_size()
        if rotate == "auto":
            # portrait panel, landscape layout → turn it a quarter
            rotate = 90 if (sh > sw) != (size[1] > size[0]) else 0
        self.rotate = int(rotate) % 360
        rotated = size if self.rotate in (0, 180) else (size[1], size[0])
        scale = min(sw / rotated[0], sh / rotated[1])
        self.out_size = (round(rotated[0] * scale), round(rotated[1] * scale))
        self.offset = ((sw - self.out_size[0]) // 2, (sh - self.out_size[1]) // 2)
        self.passthrough = self.rotate == 0 and self.out_size == screen.get_size()
        if self.passthrough:
            self.canvas = screen  # nothing to do: draw straight to the display

    def describe(self) -> str:
        sw, sh = self.screen.get_size()
        return f"display {sw}×{sh}, rotate {self.rotate}°" + ("" if self.passthrough else f", output {self.out_size}")

    def present(self):
        if not self.passthrough:
            img = self.canvas
            if self.rotate:
                # pygame rotates counter-clockwise; we want clockwise degrees
                img = pygame.transform.rotate(img, -self.rotate)
            if img.get_size() != self.out_size:
                img = pygame.transform.smoothscale(img, self.out_size)
            self.screen.fill((0, 0, 0))
            self.screen.blit(img, self.offset)
        self.flip()

    def to_canvas(self, pos):
        """Map a point on the physical screen back to canvas coordinates (for touch)."""
        x, y = pos[0] - self.offset[0], pos[1] - self.offset[1]
        ow, oh = self.out_size
        cw, ch = self.canvas.get_size()
        if self.rotate in (90, 270):
            sx, sy = x * ch / ow, y * cw / oh
        else:
            sx, sy = x * cw / ow, y * ch / oh
        if self.rotate == 90:
            return sy, ch - sx
        if self.rotate == 180:
            return cw - sx, ch - sy
        if self.rotate == 270:
            return cw - sy, sx
        return sx, sy


def set_backlight(on: bool) -> bool:
    """Switch the panel backlight via sysfs if the driver exposes one (HyperPixel does)."""
    ok = False
    for dev in glob.glob("/sys/class/backlight/*"):
        try:
            Path(dev, "bl_power").write_text("0" if on else "4")
            ok = True
        except OSError:
            pass
    return ok
