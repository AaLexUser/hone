#!/bin/sh
# One frame per second of a video, ten to a row, each stamped with its second.
#   sh contact_sheet.sh <video> <out.png>
set -eu
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$1")
ROWS=$(python3 -c "import math; print(max(1, math.ceil($DUR / 10)))")
ffmpeg -y -v error -i "$1" \
  -vf "fps=1,scale=480:270,drawtext=text='%{eif\:t\:d}s':x=8:y=8:fontsize=26:fontcolor=white:box=1:boxcolor=black@0.6,tile=10x$ROWS:padding=4" \
  -frames:v 1 "$2"
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate,pix_fmt,codec_name -of compact "$1"
