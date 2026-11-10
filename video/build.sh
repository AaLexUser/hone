#!/bin/sh
# Rebuilds the demo video from captured footage.
#   sh build.sh <footage dir> <out dir>
# Writes <out dir>/hone-demo.mp4, hone-demo.srt and contact-sheet.png (one frame per second).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
FOOTAGE=$(cd "$1" && pwd)
mkdir -p "$2"
OUT=$(cd "$2" && pwd)
python3 "$HERE/compose.py" "$HERE/timeline.json" "$FOOTAGE" "$OUT/hone-demo.mp4"
sh "$HERE/contact_sheet.sh" "$OUT/hone-demo.mp4" "$OUT/contact-sheet.png"
