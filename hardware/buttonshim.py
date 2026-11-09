"""Pimoroni Button SHIM driver: 5 buttons (A–E) + 1 RGB LED.

Why not the official ``buttonshim`` library? It always uses I2C bus 1, which
is unavailable when a HyperPixel 4.0 is fitted — the HyperPixel uses the
normal I2C pins (BCM 2/3) for the display. On a HyperPixel the SHIM has to be
wired to the HyperPixel's spare I2C header (BCM 10/11), which shows up as a
different bus number. This driver speaks the same protocol (TCA9554 I/O
expander at 0x3F, APA102 LED bit-banged through it) but lets you pick the bus,
or finds it automatically.

Button presses are delivered as pygame events (``BUTTON_EVENT``) so the main
loop handles them exactly like key presses.
"""

from __future__ import annotations

import glob
import queue
import re
import threading
import time

ADDR = 0x3F
REG_INPUT, REG_OUTPUT, REG_POLARITY, REG_CONFIG = 0x00, 0x01, 0x02, 0x03
LED_DATA, LED_CLOCK = 7, 6
NAMES = ["A", "B", "C", "D", "E"]


def _open_bus(n: int):
    try:
        from smbus2 import SMBus
    except ImportError:
        from smbus import SMBus  # python3-smbus on Raspberry Pi OS
    return SMBus(n)


def find_bus() -> int | None:
    """Return the first I2C bus with a Button SHIM on it."""
    for path in sorted(glob.glob("/dev/i2c-*"), key=lambda p: int(re.sub(r"\D", "", p) or 0)):
        n = int(path.rsplit("-", 1)[1])
        try:
            bus = _open_bus(n)
        except Exception:
            continue
        try:
            bus.read_byte_data(ADDR, REG_CONFIG)
            return n
        except OSError:
            pass
        finally:
            bus.close()
    return None


class ButtonShim(threading.Thread):
    """Polls the buttons in the background and calls ``on_press(name)``."""

    POLL_HZ = 40

    def __init__(self, on_press, bus=None, brightness: float = 0.15):
        super().__init__(daemon=True)
        self.on_press = on_press
        self.brightness = brightness
        self._bus = bus
        self._led = queue.Queue()
        self._last_color = None
        self.running = False

    # ── public ──

    @classmethod
    def connect(cls, on_press, bus_number="auto", brightness=0.15):
        """Open the SHIM, or return None (with a reason printed) if it isn't there."""
        try:
            n = find_bus() if bus_number == "auto" else int(bus_number)
        except ImportError:
            print("[buttons] smbus not installed — sudo apt install python3-smbus2", flush=True)
            return None
        if n is None:
            print("[buttons] no Button SHIM found on any I2C bus — see README (HyperPixel wiring)", flush=True)
            return None
        try:
            bus = _open_bus(n)
            bus.write_byte_data(ADDR, REG_CONFIG, 0b00011111)    # pins 0–4 inputs, 6–7 outputs (LED)
            bus.write_byte_data(ADDR, REG_POLARITY, 0b00000000)
            bus.write_byte_data(ADDR, REG_OUTPUT, 0b00000000)
        except OSError as e:
            print(f"[buttons] Button SHIM on bus {n} not responding: {e}", flush=True)
            return None
        print(f"[buttons] Button SHIM ready on I2C bus {n}", flush=True)
        shim = cls(on_press, bus, brightness)
        shim.start()
        return shim

    def set_color(self, rgb):
        """Set the LED; repeated identical colours are ignored."""
        if rgb != self._last_color:
            self._last_color = rgb
            self._led.put(_led_frames(rgb, self.brightness))

    # ── internals ──

    def run(self):
        self.running = True
        last = 0b00011111   # buttons are active-low: 1 = released
        errors = 0
        while self.running:
            try:
                while not self._led.empty():
                    frames = self._led.get_nowait()
                    for i in range(0, len(frames), 32):
                        self._bus.write_i2c_block_data(ADDR, REG_OUTPUT, frames[i:i + 32])
                state = self._bus.read_byte_data(ADDR, REG_INPUT)
                errors = 0
            except OSError as e:
                errors += 1
                if errors == 10:
                    print(f"[buttons] I2C errors, retrying: {e}", flush=True)
                time.sleep(1)
                continue
            for name in pressed(last, state):
                self.on_press(name)
            last = state
            time.sleep(1 / self.POLL_HZ)


def pressed(last: int, state: int) -> list[str]:
    """Buttons that went from released (1) to pressed (0)."""
    return [NAMES[i] for i in range(5) if (last >> i) & 1 and not (state >> i) & 1]


def _led_frames(rgb, brightness) -> list[int]:
    """Output-register values that clock one APA102 colour out on pins 6/7."""
    r, g, b = (int(max(0, min(255, c)) * brightness) for c in rgb)
    frames, reg = [], 0
    for byte in (0, 0, 0b11101111, b, g, r, 0, 0):
        for _ in range(8):
            reg &= ~(1 << LED_CLOCK)
            reg = (reg | (1 << LED_DATA)) if byte & 0x80 else (reg & ~(1 << LED_DATA))
            frames.append(reg)
            reg |= 1 << LED_CLOCK
            frames.append(reg)
            byte = (byte << 1) & 0xFF
    return frames
