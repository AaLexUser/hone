"""Write t3code's first settings.json, with Pi as the only provider and one visible model.

Reads `pi --list-models` on stdin and hides every Pi model except the one in
pi-settings.json. Pi's `default` entry is hidden too, since the demo chats name that model
directly, so the model picker offers exactly one entry.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
settings = json.loads((HERE / "settings.json").read_text())
pi = json.loads((HERE / "pi-settings.json").read_text())
keep = f"{pi['defaultProvider']}/{pi['defaultModel']}"

rows = [line.split() for line in sys.stdin.read().splitlines()[1:]]
models = [f"{row[0]}/{row[1]}" for row in rows if len(row) >= 2]
if keep not in models:
    sys.exit(f"pi --list-models does not offer {pi['defaultProvider']}/{pi['defaultModel']}")

settings["providerModelPreferences"] = {
    "pi": {"hiddenModels": ["default", *(m for m in models if m != keep)], "modelOrder": [keep]},
}
json.dump(settings, sys.stdout, indent=2)
