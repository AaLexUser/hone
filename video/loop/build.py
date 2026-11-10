"""Builds the booth loop.

python3 build.py clip <scenario> <work dir>
    Renders <work dir>/<scenario>/<scenario>.mp4 and its contact sheet from <scenario>/timeline.json
    and the footage in <work dir>/<scenario>/footage.
python3 build.py loop <work dir>
    Joins every rendered scenario clip in loop.json order into <work dir>/hone-loop.mp4, each after a
    two second chip with its name. The Hone title card opens the cycle and the results card closes it.
    Copies loop.html next to it.
    A scenario with no rendered clip yet is left out.
"""

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = os.path.dirname(HERE)
sys.path.insert(0, VIDEO)
import compose  # noqa: E402

BACKGROUND = (249, 250, 251)  # --bg of overlay.html, as rendered


def contact_sheet(mp4, png):
    subprocess.run(["sh", os.path.join(VIDEO, "contact_sheet.sh"), mp4, png], check=True)


def build_clip(scenario, work):
    out_dir = os.path.join(work, scenario)
    mp4 = os.path.join(out_dir, scenario + ".mp4")
    timeline = json.load(open(os.path.join(HERE, scenario, "timeline.json")))
    compose.compose(timeline, os.path.join(out_dir, "footage"), mp4)
    contact_sheet(mp4, os.path.join(out_dir, "contact-sheet.png"))


def build_loop(work):
    spec = json.load(open(os.path.join(HERE, "loop.json")))
    shots = [{"id": "title", "card": "title", **spec["title"]}]
    for sc in spec["scenarios"]:
        mp4 = os.path.join(work, sc["dir"], sc["dir"] + ".mp4")
        if not os.path.exists(mp4):
            print("not rendered yet, left out", sc["dir"])
            continue
        shots.append({"id": "chip " + sc["dir"], "card": "chip", "dur": spec["chipDur"], "text": {"title": sc["title"], "sub": sc.get("sub")}})
        shots.append({"id": sc["dir"], "video": mp4})
    if len(shots) == 1:
        sys.exit("no rendered clips in " + work)
    shots.append({"id": "result", "card": "result", "fade": 0.2, "out": True, **spec["result"]})
    out = os.path.join(work, "hone-loop.mp4")
    # The results card ends on the background the title card fades in over, so the cut back to the start is clean.
    compose.compose({"shots": shots, "background": BACKGROUND}, work, out)
    shutil.copy(os.path.join(HERE, "loop.html"), os.path.join(work, "loop.html"))
    contact_sheet(out, os.path.join(work, "contact-sheet.png"))


if __name__ == "__main__":
    if sys.argv[1] == "clip":
        build_clip(sys.argv[2], os.path.abspath(sys.argv[3]))
    elif sys.argv[1] == "loop":
        build_loop(os.path.abspath(sys.argv[2]))
    else:
        sys.exit(__doc__)
