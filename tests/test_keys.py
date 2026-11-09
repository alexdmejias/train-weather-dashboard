"""Key mapping: names, modifiers, config overrides.  Run: python3 -m pytest"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

import config  # noqa: E402
import dashboard  # noqa: E402

pygame.display.init()


def media(scancode):  # SDL keycode for keys pygame has no constant for
    return scancode | (1 << 30)


def test_defaults():
    km = config.load(Path("/nonexistent"))["keys"]
    look = lambda k, m=0: dashboard.lookup_key(km, k, m)
    assert look(pygame.K_SPACE) == ("space", "next_page")
    assert look(media(258)) == ("audionext", "next_page")     # knob / media remote
    assert look(media(128)) == ("volumeup", "next_page")      # volume knob
    assert look(pygame.K_SPACE, pygame.KMOD_LSHIFT) == ("shift+space", "next_page")
    assert look(pygame.K_1) == ("1", "button_a")
    assert look(pygame.K_LCTRL, pygame.KMOD_LCTRL)[1] == ""   # lone modifier: ignored quietly
    assert look(pygame.K_F13) == ("f13", None)                # unmapped → reported


def test_config_overrides_and_combos(tmp_path):
    f = tmp_path / "config.toml"
    f.write_text('[keys]\n"Ctrl+C" = "next_page"\n"ctrl+v" = "refresh"\nf13 = "sleep"\nq = ""\n')
    km = config.load(f)["keys"]
    look = lambda k, m=0: dashboard.lookup_key(km, k, m)
    assert look(pygame.K_c, pygame.KMOD_LCTRL) == ("ctrl+c", "next_page")   # macro pad default
    assert look(pygame.K_v, pygame.KMOD_RCTRL) == ("ctrl+v", "refresh")
    assert look(pygame.K_F13) == ("f13", "sleep")
    assert look(pygame.K_q) == ("q", "")                     # unmapped on purpose
    assert look(pygame.K_SPACE) == ("space", "next_page")     # defaults survive


def test_normalize():
    assert config.normalize_key("Shift + Ctrl + Page Down") == "ctrl+shift+pagedown"
