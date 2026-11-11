#!/bin/sh
set -eu
# Pi is the only provider and offers one model. Later changes made in Settings are kept.
settings="$T3CODE_HOME/userdata/settings.json"
if [ ! -f "$settings" ]; then
  mkdir -p "$(dirname "$settings")"
  pi --list-models | python3 /opt/hone-deploy/settings.py > "$settings.tmp"
  mv "$settings.tmp" "$settings"
fi
# Pi runs through the turn cache wrapper, which passes everything on when no recording matches.
python3 /opt/hone-deploy/settings.py --pi-wrapper "$settings"
# The demo chats and the demo project use the configured model, not Pi's default entry.
HONE_DEMO_MODEL="$(python3 -c 'import json; p = json.load(open("/opt/hone-deploy/pi-settings.json")); print(p["defaultProvider"] + "/" + p["defaultModel"])')"
export HONE_DEMO_MODEL
cd /opt/t3code/apps/server
exec node src/bin.ts serve --host 0.0.0.0 --port 3773 "$@"
