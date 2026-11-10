"""Write t3code's first settings.json, with Pi as the only provider and one visible model.

Reads `pi --list-models` on stdin and hides every Pi model except Pi's default and the
model in pi-settings.json, so the model picker offers only that model.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
settings = json.loads((HERE / "settings.json").read_text())
pi = json.loads((HERE / "pi-settings.json").read_text())
keep = {"default", f"{pi['defaultProvider']}/{pi['defaultModel']}"}

rows = [line.split() for line in sys.stdin.read().splitlines()[1:]]
models = [f"{row[0]}/{row[1]}" for row in rows if len(row) >= 2]
if f"{pi['defaultProvider']}/{pi['defaultModel']}" not in models:
    sys.exit(f"pi --list-models does not offer {pi['defaultProvider']}/{pi['defaultModel']}")

settings["providerModelPreferences"] = {
    "pi": {"hiddenModels": [m for m in models if m not in keep], "modelOrder": []},
}
json.dump(settings, sys.stdout, indent=2)
