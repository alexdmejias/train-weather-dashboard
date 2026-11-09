#!/usr/bin/env python3
"""Find NYC Subway station ids for config.toml.

    python3 tools/find_station.py bedford
    python3 tools/find_station.py "jay st"
"""

import json
import sys
from pathlib import Path

data = json.loads((Path(__file__).resolve().parent.parent / "data" / "subway.json").read_text())
query = " ".join(sys.argv[1:]).lower().replace("street", "st").replace("avenue", "av")
if not query:
    sys.exit(__doc__)

hits = [(sid, s) for sid, s in data["stations"].items() if query in s["name"].lower()]
if not hits:
    sys.exit(f"No station matching {query!r}")
hits.sort(key=lambda h: h[1]["name"])
for sid, s in hits:
    names = (data["routes"].get(r, {}).get("name", r) for r in s["routes"])
    lines = " ".join(dict.fromkeys(n[:-1] if n.endswith("X") else n for n in names))
    print(f'{sid:<6} {s["name"]:<36} {lines}')
print('\nPut the id(s) in config.toml, e.g.  stations = ["%s"]' % hits[0][0])
print("A station complex can have several ids (one per line group) — list them all.")
