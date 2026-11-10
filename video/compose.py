"""Builds a video from a timeline and its captured footage.

python3 compose.py <timeline.json> <footage dir> <out.mp4>

The footage dir holds <clip>.mkv recordings with wall clock timestamps and <clip>.json logs
(marks and cursor events in wall clock seconds), written by the capture scripts.
A timeline of cards only needs no footage. Writes <out.mp4> and the captions next to it as .srt.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
from bisect import bisect_right

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 30
OW, OH = 1920, 1080
SRC_SCALE = 1.5  # device pixels per CSS pixel in the recordings
SW, SH = int(OW * SRC_SCALE), int(OH * SRC_SCALE)


def ease(u):
    u = min(1.0, max(0.0, u))
    return 4 * u * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


class Clip:
    def __init__(self, footage, name):
        self.path = os.path.join(footage, name + ".mkv")
        log = json.load(open(os.path.join(footage, name + ".json")))
        self.marks = log["marks"]
        self.data = log["data"]
        self.cursor = log["cursor"]
        self.move_t = [e["t"] for e in self.cursor]
        out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0", self.path])
        self.start = float(out)

    def at(self, ref):
        name, _, off = ref.partition("@")
        return self.marks[name] + float(off or 0)

    def cursor_at(self, t):
        """Cursor position, visibility and click progress at wall time t."""
        i = bisect_right(self.move_t, t) - 1
        if i < 0:
            return None
        visible = True
        for e in self.cursor[: i + 1]:
            if e["e"] == "hide":
                visible = False
            elif e["e"] == "show":
                visible = True
        if not visible:
            return None
        a, b = self.cursor[i], self.cursor[i + 1] if i + 1 < len(self.cursor) else None
        x, y = a["x"], a["y"]
        if b and b["t"] - a["t"] < 0.1:
            u = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
            x, y = x + (b["x"] - x) * u, y + (b["y"] - y) * u
        click = None
        for e in reversed(self.cursor[: i + 1]):
            if e["e"] == "down":
                if t - e["t"] < 0.45:
                    click = (t - e["t"]) / 0.45
                break
        return x, y, click


def camera_at(shot, t):
    """Crop rectangle (x, y, zoom) in CSS pixels at shot time t."""
    keys = shot.get("camera") or [[0, OW / 2, OH / 2, 1]]
    if t <= keys[0][0]:
        k = keys[0][1:]
    elif t >= keys[-1][0]:
        k = keys[-1][1:]
    else:
        j = max(i for i, key in enumerate(keys) if key[0] <= t)
        a, b = keys[j], keys[j + 1]
        u = ease((t - a[0]) / (b[0] - a[0]))
        za, zb = math.log(a[3]), math.log(b[3])
        k = [a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u, math.exp(za + (zb - za) * u)]
    cx, cy, z = k
    w, h = OW / z, OH / z
    x = min(max(cx - w / 2, 0), OW - w)
    y = min(max(cy - h / 2, 0), OH - h)
    return x, y, z


def probe_duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out)


def resolve(timeline, clips):
    shots, t = [], 0.0
    for s in timeline["shots"]:
        s = dict(s)
        if "clip" in s:
            clip = clips[s["clip"]]
            s["src0"] = clip.at(s["from"])
            s.setdefault("speed", 1.0)
            if "to" in s:
                span = clip.at(s["to"]) - s["src0"]
                if "dur" in s:
                    s["speed"] = span / s["dur"]
                else:
                    s["dur"] = span / s["speed"]
            if s.get("badge"):
                s["badge"] = {k: v.replace("{speed}", f"{s['speed']:.0f}") for k, v in s["badge"].items()}
        elif "video" in s:
            s.setdefault("dur", probe_duration(s["video"]))
        s["t0"] = t
        s["n"] = round(s["dur"] * FPS)
        t += s["n"] / FPS
        shots.append(s)
    return shots, t


def captions_of(shots):
    caps = []
    for s in shots:
        for c in s.get("captions", []):
            caps.append({"t0": s["t0"] + c["at"], "t1": s["t0"] + c["to"], "text": c["text"], "pos": c.get("pos", s.get("captionPos", "bottom")), "band": c.get("band", True)})
    for c in caps:
        if any(ch in c["text"] for ch in ":;\u2013\u2014"):
            sys.exit(f"caption has a colon, semicolon or dash: {c['text']!r}")
    for a, b in zip(caps, caps[1:]):
        if b["t0"] < a["t1"]:
            sys.exit(f"captions overlap at {b['t0']:.2f}s: {a['text']!r} and {b['text']!r}")
    return caps


def states_for(shots, clips, caps):
    states = []
    for s in shots:
        for i in range(s["n"]):
            t = i / FPS
            g = s["t0"] + t
            st = {}
            if "card" in s:
                st["card"] = {"kind": s["card"], "t": round(t, 3), "dur": s["dur"], **{k: s[k] for k in ("text", "out") if k in s}}
            elif "clip" in s:
                clip = clips[s["clip"]]
                x0, y0, z = camera_at(s, t)
                hls = []
                for h in s.get("highlights", []):
                    if h["at"] <= t < h["to"]:
                        rx, ry, rw, rh = h["rect"]
                        hls.append({"x": round((rx - x0) * z, 1), "y": round((ry - y0) * z, 1), "w": round(rw * z, 1), "h": round(rh * z, 1), "tone": h.get("tone", "indigo"), "t": round(t - h["at"], 3), "left": round(h["to"] - t, 3)})
                if hls:
                    st["highlights"] = hls
                if s.get("badge"):
                    b = s["badge"]
                    st["badge"] = {"big": b["big"], "small": b["small"], "t": round(t, 3), "left": round(s["dur"] - t, 3)}
                if s["speed"] <= 3 and not s.get("noCursor"):
                    c = clip.cursor_at(s["src0"] + t * s["speed"])
                    if c:
                        cx, cy, click = c
                        st["cursor"] = {"x": round((cx - x0) * z, 1), "y": round((cy - y0) * z, 1), "s": round(z, 3), "a": 1, "click": None if click is None else round(click, 3)}
            active = [{"text": c["text"], "pos": c["pos"], "t": round(g - c["t0"], 3), "left": round(c["t1"] - g, 3)} for c in caps if c["band"] and c["t0"] <= g < c["t1"]]
            if active:
                st["captions"] = active
            states.append(st)
    return states


def read_frames(cmd, w, h, n):
    """n raw frames from an ffmpeg command, holding the last one if the source runs short."""
    p = subprocess.Popen(cmd + ["-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:"], stdout=subprocess.PIPE)
    last = None
    for _ in range(n):
        buf = p.stdout.read(w * h * 3)
        if len(buf) == w * h * 3:
            last = Image.frombuffer("RGB", (w, h), buf)
        yield last
    p.stdout.close()
    p.wait()


def footage_frames(clip, shot):
    span = shot["n"] / FPS * shot["speed"] + 1
    ss = shot["src0"] - clip.start
    return read_frames(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", clip.path, "-t", f"{span:.3f}",
                        "-vf", f"setpts=(PTS-STARTPTS)/{shot['speed']:.5f},fps={FPS}"], SW, SH, shot["n"])


def video_frames(shot):
    """A rendered 1920 by 1080 video, frame for frame."""
    return read_frames(["ffmpeg", "-v", "error", "-i", shot["video"], "-vf", f"fps={FPS}"], OW, OH, shot["n"])


def write_srt(caps, path):
    def ts(x):
        ms = round(x * 1000)
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    with open(path, "w") as f:
        for i, c in enumerate(caps, 1):
            text = c["text"].replace("*", "").replace(" / ", "\n")
            f.write(f"{i}\n{ts(c['t0'])} --> {ts(c['t1'])}\n{text}\n\n")


def compose(timeline, footage, out_mp4):
    clips = {name: Clip(footage, name) for name in {s["clip"] for s in timeline["shots"] if "clip" in s}}
    shots, total = resolve(timeline, clips)
    caps = captions_of(shots)
    for s in shots:
        extra = f" speed {s['speed']:.2f}x" if "clip" in s else ""
        print(f"{s['id']:<14} {s['t0']:6.2f}s  {s['dur']:5.2f}s{extra}")
    print(f"total {total:.2f}s")
    write_srt(caps, os.path.splitext(out_mp4)[0] + ".srt")

    with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(out_mp4))) as tmp:
        ov_dir = os.path.join(tmp, "overlay")
        states_file = os.path.join(tmp, "states.json")
        json.dump(states_for(shots, clips, caps), open(states_file, "w"))
        subprocess.run(["node", os.path.join(HERE, "render_overlay.cjs"), states_file, ov_dir], check=True)
        index = json.load(open(os.path.join(ov_dir, "index.json")))
        encode(shots, clips, ov_dir, index, out_mp4, tuple(timeline.get("background", (0, 0, 0))))
    print("wrote", out_mp4)


def encode(shots, clips, ov_dir, index, out_mp4, background):
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", str(FPS), "-i", "pipe:",
                            "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            out_mp4], stdin=subprocess.PIPE)
    frame_no, base, prev_final = 0, Image.new("RGB", (OW, OH), background), None
    ov_cache = (None, None)
    for s in shots:
        frames = footage_frames(clips[s["clip"]], s) if "clip" in s else video_frames(s) if "video" in s else None
        fade_n = round(s.get("fade", 0) * FPS)
        if frames is None and prev_final is not None:
            base = prev_final  # a card fades in over the frame before it
        for i in range(s["n"]):
            if "video" in s:
                base = next(frames)
            elif frames is not None:
                src = next(frames)
                x0, y0, z = camera_at(s, i / FPS)
                box = (x0 * SRC_SCALE, y0 * SRC_SCALE, (x0 + OW / z) * SRC_SCALE, (y0 + OH / z) * SRC_SCALE)
                base = src.resize((OW, OH), Image.LANCZOS, box=box)
            name = index[frame_no]
            if ov_cache[0] != name:
                ov_cache = (name, Image.open(os.path.join(ov_dir, name)).convert("RGBA"))
            final = base.convert("RGBA")
            final.alpha_composite(ov_cache[1])
            final = final.convert("RGB")
            if i < fade_n and prev_final is not None:
                final = Image.blend(prev_final, final, ease((i + 1) / (fade_n + 1)))
            enc.stdin.write(final.tobytes())
            frame_no += 1
        prev_final = final
        print("composited", s["id"])
    enc.stdin.close()
    if enc.wait() != 0:
        sys.exit("ffmpeg failed to encode " + out_mp4)


def main():
    timeline_file, footage, out_mp4 = sys.argv[1:4]
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    compose(json.load(open(timeline_file)), footage, out_mp4)


if __name__ == "__main__":
    main()
