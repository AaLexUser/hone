#!/bin/sh
# Rebuilds the demo video from captured footage.
#   sh build.sh <footage dir> <out dir>
# Writes <out dir>/hone-demo.mp4, hone-demo.srt and contact-sheet.png (one frame per second).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
FOOTAGE=$(cd "$1" && pwd)
mkdir -p "$2"
OUT=$(cd "$2" && pwd)
python3 "$HERE/compose.py" "$FOOTAGE" "$OUT"
rm -rf "$OUT/overlay" "$OUT/states.json"
ffmpeg -y -v error -i "$OUT/hone-demo.mp4" \
  -vf "fps=1,scale=480:270,drawtext=text='%{eif\:t\:d}s':x=8:y=8:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.6,tile=6x14:padding=4" \
  -frames:v 1 "$OUT/contact-sheet.png"
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate,pix_fmt,codec_name -of compact "$OUT/hone-demo.mp4"
