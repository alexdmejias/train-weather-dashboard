"""Button SHIM + display rotation logic (no hardware needed).  Run: python3 -m pytest"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from hardware import buttonshim  # noqa: E402
from hardware.display import Presenter  # noqa: E402


def test_press_edges():
    assert buttonshim.pressed(0b11111, 0b11101) == ["B"]        # B went low = pressed
    assert buttonshim.pressed(0b11101, 0b11101) == []           # still held: no repeat
    assert buttonshim.pressed(0b11101, 0b11111) == []           # release isn't a press
    assert buttonshim.pressed(0b11111, 0b01110) == ["A", "E"]


def test_led_frames_match_official_encoding():
    # same bit-bang sequence as Pimoroni's buttonshim.set_pixel (8 bytes × 8 bits × 2 clock edges)
    frames = buttonshim._led_frames((255, 0, 0), 1.0)
    assert len(frames) == 8 * 8 * 2
    def byte_at(i):  # read back the data bit on each rising clock edge
        bits = [(frames[(i * 8 + b) * 2 + 1] >> buttonshim.LED_DATA) & 1 for b in range(8)]
        return int("".join(map(str, bits)), 2)
    assert [byte_at(i) for i in range(8)] == [0, 0, 0b11101111, 0, 0, 255, 0, 0]  # B, G, R order


class FakeBus:
    def __init__(self, states):
        self.states, self.writes = list(states), []

    def read_byte_data(self, addr, reg):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def write_i2c_block_data(self, addr, reg, data):
        self.writes.append(list(data))


def test_shim_thread_reports_presses():
    import time
    got = []
    shim = buttonshim.ButtonShim(got.append, FakeBus([0b11111, 0b11011, 0b11011, 0b11111]))
    shim.set_color((0, 255, 0))
    shim.start()
    time.sleep(0.3)
    shim.running = False
    assert got == ["C"]
    assert shim._bus.writes  # LED frames were sent


def test_presenter_rotates_for_portrait_panel():
    pygame.display.init()
    screen = pygame.Surface((480, 800))
    p = Presenter(screen, (800, 480), "auto")
    assert p.rotate == 90 and not p.passthrough
    # a mark at the canvas's top-left corner ends up top-right on the panel
    p.canvas.fill((0, 0, 0))
    p.canvas.fill((255, 0, 0), pygame.Rect(0, 0, 20, 20))
    p.screen = screen
    img = pygame.transform.rotate(p.canvas, -90)
    assert img.get_at((470, 5))[:3] == (255, 0, 0)
    # taps map back to canvas coordinates
    for rot in (90, 180, 270):
        q = Presenter(screen if rot != 180 else pygame.Surface((800, 480)), (800, 480), rot)
        for pt in ((10, 20), (790, 470), (400, 240)):
            # forward-map the point the same way pygame rotates, then invert
            cw, ch = 800, 480
            fwd = {90: (ch - pt[1], pt[0]), 180: (cw - pt[0], ch - pt[1]), 270: (pt[1], cw - pt[0])}[rot]
            back = q.to_canvas(fwd)
            assert abs(back[0] - pt[0]) < 1.5 and abs(back[1] - pt[1]) < 1.5


def test_elecrow_is_passthrough():
    screen = pygame.Surface((800, 480))
    assert Presenter(screen, (800, 480), "auto").passthrough
