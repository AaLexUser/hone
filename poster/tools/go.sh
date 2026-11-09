cd "$(dirname "$0")/.."; python3 tools/build.py && DSF=0.6 node tools/render.cjs index.html out | head -40
