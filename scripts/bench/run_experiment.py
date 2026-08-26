"""Hone self-improvement loop on a Harbor benchmark dataset.

The runner executes the full experimental protocol on any local Harbor dataset
(default: the OfficeQA offline adapter):

    1. `init`    — create the experiment dir, split the dataset into training
                   batches + the final full run, stage pi container config.
    2. `batches` — per batch: run Harbor trials (pi agent + the hone extension
                   inside the sandbox, the current AGENTS.md mounted into the
                   workspace), publish each trial as a hone trace with
                   per-task feedback, then trigger the Hone optimizer and wait
                   for the updated AGENTS.md version.
    3. `final`   — one Harbor job over the complete original dataset with the
                   optimized AGENTS.md, scored exact-match, compared against a
                   baseline trials directory.

Every stage writes a report under the experiment dir and is resumable: a batch
or final run whose report already exists is skipped.

Usage:
    uv run python scripts/bench/run_experiment.py init \
        --exp experiments/officeqa-run1 \
        --dataset harbor-officeqa-offline-adapter/datasets/officeqa-offline \
        --train-count 24 --batch-size 8 --baseline pi-gpt-5.4-mini-baseline

    uv run python scripts/bench/run_experiment.py batches --exp experiments/officeqa-run1
    uv run python scripts/bench/run_experiment.py final   --exp experiments/officeqa-run1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePath

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "bench"))
from progress import batch_progress, pre_run_notes  # noqa: E402
from split_batches import build_manifest  # noqa: E402

HONE_EXT = REPO / "clients" / "pi-extensions" / "hone.ts"
DUMP_EXT = REPO / "scripts" / "bench" / "pi-extensions" / "dump-system-prompt.ts"

# Sandbox-side locations of the pi home and the agent workspace.
PI_HOME_TARGET = "/root/.pi/agent"
WORKSPACE_TARGET = "/workspace"


def log(msg: str) -> None:
    print(msg, flush=True)


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


# --------------------------------------------------------------------------- #
# Hone service HTTP client + lifecycle
# --------------------------------------------------------------------------- #

class HoneClient:
    def __init__(self, base: str, token: str) -> None:
        self.base = base.rstrip("/")
        self.token = token

    @property
    def url(self) -> str:
        return self.base

    def _open(self, path: str, *, method: str = "GET", body: bytes | None = None,
              headers: dict[str, str] | None = None, timeout: float = 30):
        req = urllib.request.Request(
            self.base + path, data=body, method=method,
            headers={"authorization": f"Bearer {self.token}", **(headers or {})},
        )
        return urllib.request.urlopen(req, timeout=timeout)

    def get_json(self, path: str) -> dict:
        with self._open(path) as res:
            return json.loads(res.read())

    def agents_md(self) -> tuple[str, str]:
        """Return (version_id, body) of the current AGENTS.md."""
        with self._open("/agents.md") as res:
            return res.headers.get("x-hone-version", "?"), res.read().decode("utf-8")

    def put_trace(self, trace_id: str, body: bytes, version_id: str) -> dict:
        with self._open(f"/api/traces/{trace_id}", method="PUT", body=body,
                        headers={"content-type": "application/x-ndjson",
                                 "x-hone-version": version_id}) as res:
            return json.loads(res.read())

    def post_json(self, path: str, payload: dict) -> dict:
        with self._open(path, method="POST", body=json.dumps(payload).encode(),
                        headers={"content-type": "application/json"}) as res:
            return json.loads(res.read())

    def state(self) -> dict:
        return self.get_json("/api/state")

    def wait_idle(self, timeout: float, poll: float = 10.0,
                  run_id: str | None = None) -> dict | None:
        """Wait until no optimizer run is active; return its final record."""
        deadline = time.time() + timeout
        last_status = ""
        while time.time() < deadline:
            run = self.state().get("run")
            if not run:
                if run_id:
                    try:
                        return self.get_json(f"/api/runs/{run_id}")
                    except urllib.error.HTTPError:
                        return None
                return None
            if run["status"] != last_status:
                last_status = run["status"]
                log(f"  [hone] run {run['id']} status: {last_status}")
            time.sleep(poll)
        raise TimeoutError(f"optimizer run still active after {timeout:.0f}s")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Service:
    """Start (or attach to) the hone API service for one experiment."""

    def __init__(self, exp: Path, env: dict[str, str], hone_config: str | None = None,
                 model: str | None = None) -> None:
        self.exp = exp
        self.dotenv = env
        self.hone_config = hone_config
        self.model = model
        self.info_path = exp / "service.json"
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.token = os.environ.get("HONE_TOKEN", "dev-token")

    def start_or_attach(self) -> HoneClient:
        info = self._read_info()
        if info and self._alive(info):
            log(f"[service] attaching to {info['url']} (pid {info['pid']})")
            self.url = info["url"]
            return HoneClient(self.url, self.token)
        if info:
            self._kill(info)
        port = free_port()
        data_dir = self.exp / "hone-data"
        data_dir.mkdir(parents=True, exist_ok=True)
        env = {
            **os.environ,
            "HONE_DATA_DIR": str(data_dir),
            "HONE_PORT": str(port),
            "HONE_TOKEN": self.token,
            "HONE_EXPOSE_WRITE_TOKEN": "0",
            "OPENAI_API_KEY": self.dotenv.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
            "OPENAI_BASE_URL": self.dotenv.get("OPENAI_BASE_URL", os.environ.get("OPENAI_BASE_URL", "")),
            "MODEL_NAME": (self.model or
                           self.dotenv.get("MODEL_NAME", os.environ.get("MODEL_NAME", "openai/gpt-5.4-mini"))),
        }
        if self.hone_config:
            env["HONE_CONFIG"] = self.hone_config
        log_file = (self.exp / "service.log").open("ab")
        self.proc = subprocess.Popen(
            ["uv", "run", "uvicorn", "hone.api:app", "--host", "127.0.0.1",
             "--port", str(port), "--log-level", "warning"],
            cwd=str(REPO), env=env, stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        url = f"http://127.0.0.1:{port}"
        client = HoneClient(url, self.token)
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"hone service exited early — see {self.exp / 'service.log'}")
            try:
                client.agents_md()
                self.url = url
                self._write_info({"url": url, "pid": self.proc.pid, "port": port})
                log(f"[service] started {url} (pid {self.proc.pid}), data at {data_dir}")
                return client
            except Exception:
                time.sleep(1)
        raise RuntimeError("hone service did not become ready in 60s")

    def stop(self) -> None:
        info = self._read_info()
        if info:
            self._kill(info)
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.info_path.exists():
            self.info_path.unlink()
        log("[service] stopped")

    def _read_info(self) -> dict | None:
        if not self.info_path.exists():
            return None
        try:
            return json.loads(self.info_path.read_text())
        except json.JSONDecodeError:
            return None

    def _alive(self, info: dict) -> bool:
        try:
            HoneClient(info["url"], self.token).agents_md()
            return True
        except Exception:
            return False

    def _kill(self, info: dict) -> None:
        try:
            os.kill(int(info["pid"]), signal.SIGTERM)
            time.sleep(1)
        except (ProcessLookupError, ValueError, KeyError):
            pass

    def _write_info(self, info: dict) -> None:
        self.info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Harbor job execution
# --------------------------------------------------------------------------- #

def write_job_yaml(path: Path, *, job_name: str, jobs_dir: Path, task_paths: list[Path],
                   model: str, mounts: list[dict], concurrency: int) -> None:
    lines = [
        f"job_name: {job_name}",
        f"jobs_dir: {jobs_dir}",
        "n_attempts: 1",
        "quiet: true",
        f"n_concurrent_trials: {concurrency}",
        "tasks:",
    ]
    for tp in task_paths:
        lines.append(f"  - path: {tp}")
    gateway_host = urllib.parse.urlparse(os.environ.get("OPENAI_BASE_URL", "")).hostname or ""
    lines += [
        "agents:",
        "  - name: pi",
        f"    model_name: {model}",
        "    extra_allowed_hosts:",
    ]
    for host in dict.fromkeys(h for h in [gateway_host, "host.docker.internal"] if h):
        lines.append(f"      - {host}")
    lines += [
        "environment:",
        "  type: docker",
        "  mounts:",
    ]
    for m in mounts:
        parts = [f"type: {m['type']}", f"source: {m['source']}", f"target: {m['target']}"]
        if m.get("read_only"):
            parts.append("read_only: true")
        lines.append("    - { " + ", ".join(parts) + " }")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_harbor(job_yaml: Path, log_path: Path, env: dict[str, str], n_tasks: int,
               concurrency: int, per_task_timeout: float = 1800.0) -> None:
    """Run one harbor job, streaming its output to log_path."""
    timeout = max(3600.0, (n_tasks / max(1, concurrency)) * per_task_timeout * 1.6 + 900)
    cmd = ["uv", "run", "harbor", "run", "--config", str(job_yaml), "-y"]
    log(f"  [harbor] {' '.join(shlex.quote(c) for c in cmd)} (timeout {timeout / 60:.0f}m)")
    with log_path.open("wb") as out:
        proc = subprocess.Popen(cmd, cwd=str(REPO), env={**os.environ, **env},
                                stdout=out, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError(f"harbor job timed out after {timeout / 60:.0f}m — see {log_path}")
    if rc != 0:
        raise RuntimeError(f"harbor job exited {rc} — see {log_path}")


def collect_trials(jobs_dir: Path, job_name: str) -> list[dict]:
    """Read every trial result under jobs_dir/job_name."""
    trials = []
    for result_path in sorted((jobs_dir / job_name).glob("*/result.json")):
        try:
            result = json.loads(result_path.read_text())
        except json.JSONDecodeError:
            continue
        trial_dir = result_path.parent
        rewards = ((result.get("verifier_result") or {}).get("rewards") or {})
        details = {}
        details_path = trial_dir / "verifier" / "details.json"
        if details_path.exists():
            try:
                details = json.loads(details_path.read_text())
            except json.JSONDecodeError:
                pass
        trials.append({
            "trial": trial_dir.name,
            "task": result.get("task_name", "").split("__")[-1] or trial_dir.name.split("__")[0],
            "reward": rewards.get("reward"),
            "ground_truth": details.get("ground_truth"),
            "predicted": details.get("predicted"),
            "exception": (result.get("exception_info") or {}).get("exception_type"),
            "pi_txt": trial_dir / "agent" / "pi.txt",
        })
    return trials


# --------------------------------------------------------------------------- #
# Trace synthesis: harbor's downloaded pi json-mode log -> hone trace JSONL
# --------------------------------------------------------------------------- #

_MAX_TOOL_RESULT_CHARS = 2000
_FINAL_TAG = re.compile(r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>", re.DOTALL)


def _clip_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f" …[clipped {len(text) - limit} chars]"


def _clip_content(content):
    if isinstance(content, str):
        return _clip_text(content, 4000)
    if not isinstance(content, list):
        return content
    out = []
    for item in content:
        if not isinstance(item, dict):
            out.append(item)
        elif item.get("type") == "text":
            out.append({**item, "text": _clip_text(item.get("text", ""), 4000)})
        elif isinstance(item.get("text"), str):
            out.append({**item, "text": _clip_text(item["text"], _MAX_TOOL_RESULT_CHARS)})
        else:
            out.append(item)
    return out


def synthesize_trace(pi_txt: Path, session_id: str, version_id: str) -> bytes | None:
    """Convert pi's --mode json event log into the pi-session JSONL hone stores."""
    if not pi_txt.exists():
        return None
    entries: list[dict] = []
    saw_header = False
    for raw in pi_txt.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")
        if kind == "session":
            header = dict(ev)
            header["id"] = session_id
            header["agents_md"] = version_id
            entries.append(header)
            saw_header = True
        elif kind == "message_end":
            msg = ev.get("message") or {}
            if msg.get("role") in ("user", "assistant", "toolResult"):
                entries.append({
                    "type": "message",
                    "message": {"role": msg["role"], "content": _clip_content(msg.get("content"))},
                })
    if not entries:
        return None
    if not saw_header:
        entries.insert(0, {
            "type": "session", "version": 3, "id": session_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cwd": WORKSPACE_TARGET, "agents_md": version_id,
        })
    return ("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n").encode("utf-8")


def _clip_entry(entry: dict) -> dict:
    """Clip oversized text/toolResult content in a session entry, in place-safe copy."""
    msg = entry.get("message")
    if isinstance(msg, dict) and "content" in msg:
        entry = dict(entry)
        entry["message"] = {**msg, "content": _clip_content(msg.get("content"))}
    return entry


def load_session_trace(trial_dir: Path, version_id: str) -> tuple[bytes, str] | None:
    """Prefer pi's real session file (harbor downloads it under agent/pi/sessions).

    Returns (trace_body, raw_session_id) with the header stamped for hone.
    """
    sessions_dir = trial_dir / "agent" / "pi" / "sessions"
    if not sessions_dir.is_dir():
        return None
    files = sorted(sessions_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    out: list[dict] = []
    session_id = ""
    for line in files[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "session":
            session_id = str(entry.get("id") or "")
            entry = dict(entry)
            entry["agents_md"] = version_id
            out.append(entry)
        elif entry.get("type") == "message":
            out.append(_clip_entry(entry))
    if not out or not session_id:
        return None
    return ("\n".join(json.dumps(e, ensure_ascii=False) for e in out) + "\n").encode("utf-8"), session_id


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").replace("$", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def feedback_for(trial: dict) -> tuple[bool, str]:
    reward = trial.get("reward")
    gt = (trial.get("ground_truth") or "").strip()
    predicted = (trial.get("predicted") or "").strip()
    m = _FINAL_TAG.search(predicted)
    got = m.group(1).strip() if m else predicted
    if reward is not None and float(reward) >= 1.0:
        return True, "Correct Answer"
    if not got and trial.get("exception"):
        return False, (f"Task errored ({trial['exception']}) — no answer produced. "
                       "| Failure class COMPLETION: always finish by writing the best-supported "
                       "final answer even when uncertain.")
    fb = f"Expected: {gt} Got: {got}"
    g_n, e_n = _num(got), _num(gt)
    if not got:
        return False, fb + (" | Failure class COMPLETION: no answer was produced — always write the "
                            "best-supported final answer before finishing.")
    if any(sym in got for sym in ("=", "×", "^")) or got.count(",") > 6:
        return False, fb + (
            " | Failure class FORMAT: the submitted final answer embeds a formula, calculation, or "
            "derivation. The final answer must contain ONLY the requested value — no equations, no "
            "labels, no explanation. The correct value is often already computed inside the "
            "derivation; extract and output exactly that value in the expected form.")
    if g_n is not None and e_n is not None and e_n != 0 and abs(g_n - e_n) / abs(e_n) < 0.05:
        return False, fb + (
            " | Failure class NEAR-MISS: the submitted value is numerically close but wrong — "
            "typically the wrong row, column, year, or unit scale was read from the source. "
            "Re-locate the exact source cell and re-check which quantity the question asks for.")
    return False, fb + (
        " | Failure class EXTRACTION: the submitted answer does not match the expected value. "
        "Verify the exact source location, the requested period or unit, and the quantity "
        "the question actually asks for; compute derived values from the exact source figures.")


# --------------------------------------------------------------------------- #
# Baseline scoring
# --------------------------------------------------------------------------- #

def score_baseline_dir(baseline: Path) -> dict | None:
    if not baseline or not baseline.is_dir():
        return None
    hits, total = 0, 0
    per_task: dict[str, float] = {}
    for p in sorted(baseline.glob("*/result.json")):
        try:
            r = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        rewards = ((r.get("verifier_result") or {}).get("rewards") or {})
        reward = rewards.get("reward")
        task = r.get("task_name", "").split("__")[-1] or p.parent.name.split("__")[0]
        total += 1
        ok = reward is not None and float(reward) >= 1.0
        hits += ok
        per_task[task] = 1.0 if ok else 0.0
    if not total:
        return None
    return {"hits": hits, "total": total, "score": hits / total, "per_task": per_task}


def summarize_trials(trials: list[dict]) -> dict:
    hits = sum(1 for t in trials if t.get("reward") is not None and float(t["reward"]) >= 1.0)
    return {"hits": hits, "total": len(trials), "score": hits / max(1, len(trials))}


# --------------------------------------------------------------------------- #
# pi-config staging (models.json, hone.json, extension) + job helpers
# --------------------------------------------------------------------------- #

def sandbox_url(url: str) -> str:
    """Rewrite a host-side service URL so containers can reach it."""
    return re.sub(r"//(127\.0\.0\.1|localhost|\[::1\])", "//host.docker.internal", url)


def stage_pi_config(exp: Path, hone_url: str, token: str, model: str, dotenv: dict[str, str]) -> Path:
    """Materialize the files bind-mounted into every task sandbox."""
    cfg_dir = exp / "pi-config"
    (cfg_dir / "extensions").mkdir(parents=True, exist_ok=True)
    provider, model_id = model.split("/", 1)
    base_url = dotenv.get("OPENAI_BASE_URL", os.environ.get("OPENAI_BASE_URL", ""))
    api_key = dotenv.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    (cfg_dir / "models.json").write_text(json.dumps({
        "providers": {
            provider: {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": api_key,
                "models": [{
                    "id": model_id,
                    "name": f"{model_id} (experiment gateway)",
                    "reasoning": True,
                    "input": ["text"],
                    "contextWindow": 272000,
                    "maxTokens": 128000,
                }],
            }
        }
    }, indent=2) + "\n", encoding="utf-8")
    (cfg_dir / "hone.json").write_text(
        json.dumps({"url": sandbox_url(hone_url), "token": token, "publish": False}) + "\n",
        encoding="utf-8")
    (cfg_dir / "extensions" / "hone.ts").write_text(
        HONE_EXT.read_text(encoding="utf-8"), encoding="utf-8")
    # Proof extension: dumps the assembled system prompt (incl. AGENTS.md) to
    # /logs/agent/system-prompt.txt, which harbor collects per trial.
    (cfg_dir / "extensions" / "dump-system-prompt.ts").write_text(
        DUMP_EXT.read_text(encoding="utf-8"), encoding="utf-8")
    return cfg_dir


def batch_mounts(cfg_dir: Path, agents_md_file: Path) -> list[dict]:
    return [
        {"type": "bind", "source": str(cfg_dir / "models.json"),
         "target": f"{PI_HOME_TARGET}/models.json", "read_only": True},
        {"type": "bind", "source": str(cfg_dir / "extensions" / "hone.ts"),
         "target": f"{PI_HOME_TARGET}/extensions/hone.ts", "read_only": True},
        {"type": "bind", "source": str(cfg_dir / "extensions" / "dump-system-prompt.ts"),
         "target": f"{PI_HOME_TARGET}/extensions/dump-system-prompt.ts", "read_only": True},
        {"type": "bind", "source": str(cfg_dir / "hone.json"),
         "target": f"{PI_HOME_TARGET}/hone.json", "read_only": True},
        {"type": "bind", "source": str(agents_md_file),
         "target": f"{WORKSPACE_TARGET}/AGENTS.md", "read_only": True},
    ]


def run_one_job(exp: Path, *, stage: str, task_paths: list[Path], agents_md_file: Path,
                cfg: dict, dotenv: dict[str, str], publish: HoneClient | None,
                version_id: str | None, feedback_notes: dict[str, str] | None = None,
                batch_note: str = "", force: bool = False) -> dict:
    """Run a harbor job over task_paths; optionally publish traces + feedback.

    ``stage`` is the run's path under the experiment dir (e.g. "epoch_01/batch_02");
    the harbor job name is its last component. ``feedback_notes`` adds a per-task
    progress note and ``batch_note`` a batch-level progress line to the feedback
    posted for the optimizer.
    """
    stage_dir = exp / stage
    job_name = PurePath(stage).name
    report_path = stage_dir / "report.json"
    if report_path.exists() and not force:
        log(f"[{stage}] report exists — skipping (pass --force to rerun)")
        return json.loads(report_path.read_text())
    if stage_dir.exists() and not report_path.exists():
        log(f"[{stage}] clearing incomplete stage artifacts before restart")
        shutil.rmtree(stage_dir)
    if force and stage_dir.exists():
        shutil.rmtree(stage_dir)

    cfg_dir = exp / "pi-config"
    jobs_dir = stage_dir / "jobs"
    job_yaml = stage_dir / "job.yaml"
    write_job_yaml(job_yaml, job_name=job_name, jobs_dir=jobs_dir, task_paths=task_paths,
                   model=cfg["model"], mounts=batch_mounts(cfg_dir, agents_md_file),
                   concurrency=cfg["concurrency"])
    env = {"OPENAI_API_KEY": dotenv.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))}
    run_harbor(job_yaml, stage_dir / "harbor.log", env, len(task_paths), cfg["concurrency"])

    trials = collect_trials(jobs_dir, job_name)
    if not trials:
        raise RuntimeError(f"[{stage}] no trial results found under {jobs_dir / job_name}")
    report: dict = {"stage": stage, "version_id": version_id, "trials": []}
    for t in trials:
        ok, fb = feedback_for(t)
        note = (feedback_notes or {}).get(t["task"])
        if note:
            fb = f"{fb}\n{note}"
        if batch_note:
            fb = f"{fb}\n{batch_note}"
        entry = {
            "task": t["task"], "trial": t["trial"], "reward": t["reward"], "ok": ok,
            "ground_truth": t["ground_truth"], "predicted": t["predicted"], "feedback": fb,
        }
        if publish is not None and version_id is not None:
            loaded = load_session_trace(t["pi_txt"].parent, version_id)
            if loaded is not None:
                body, session_id = loaded
            else:
                session_id = f"{t['task']}-{t['trial'].split('__')[-1]}"
                body = synthesize_trace(t["pi_txt"], session_id, version_id)
            if body is None:
                entry["trace_error"] = "no pi session or json log found"
            else:
                try:
                    resp = publish.put_trace(session_id, body, version_id)
                    trace_id = (resp.get("trace") or {}).get("id", "")
                    if not trace_id:
                        raise RuntimeError("service returned no trace id")
                    publish.post_json(f"/api/traces/{trace_id}/feedback", {"text": fb})
                    entry["trace_id"] = trace_id
                except Exception as exc:  # noqa: BLE001 — publishing is best-effort
                    entry["trace_error"] = str(exc)[:200]
        report["trials"].append(entry)
    report.update(summarize_trials(trials))
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log(f"[{stage}] exact-match {report['hits']}/{report['total']} = {report['score']:.1%} -> {report_path}")
    return report


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #

def do_split(exp: Path, args: argparse.Namespace) -> dict:
    """Create splits/manifest.json under the experiment dir."""
    splits = exp / "splits"
    if args.splits_manifest and Path(args.splits_manifest, "manifest.json").exists():
        shutil.copytree(args.splits_manifest, splits, dirs_exist_ok=True)
        manifest = json.loads((splits / "manifest.json").read_text())
        log(f"[init] copied splits from {args.splits_manifest}")
        return manifest
    if not args.dataset:
        raise SystemExit("init needs --dataset or --splits-manifest")
    if args.train_count is None and args.train_ratio is None:
        raise SystemExit("init needs --train-count or --train-ratio")
    manifest = build_manifest(
        Path(args.dataset).resolve(), train_count=args.train_count,
        train_ratio=args.train_ratio, batch_size=args.batch_size, seed=args.seed,
    )
    splits.mkdir(parents=True, exist_ok=True)
    (splits / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    log(f"[init] {manifest['n_tasks']} tasks · {manifest['n_train']} train in "
        f"{len(manifest['batches'])} batches of <= {args.batch_size} · final = full {manifest['n_tasks']}")
    return manifest


def stage_init(args: argparse.Namespace) -> Path:
    exp = args.exp.resolve()
    exp.mkdir(parents=True, exist_ok=True)
    do_split(exp, args)
    config = {
        "dataset": json.loads((exp / "splits" / "manifest.json").read_text())["dataset"],
        "model": args.model,
        "hone_config": str(args.hone_config.resolve()) if args.hone_config else None,
        "candidates": max(1, getattr(args, "candidates", 1) or 1),
        "concurrency": args.concurrency,
        "epochs": max(1, args.epochs),
        "baseline": str(Path(args.baseline).resolve()) if args.baseline else None,
        "optimize_timeout_s": args.optimize_timeout,
    }
    (exp / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    log(f"[init] experiment ready at {exp}")
    return exp


def snapshot_agents_md(exp: Path, client: HoneClient) -> tuple[str, Path]:
    """Persist the service's current AGENTS.md as the per-run snapshot file."""
    version_id, body = client.agents_md()
    agents_md_file = exp / "agents-md" / f"{version_id}.md"
    agents_md_file.parent.mkdir(exist_ok=True)
    agents_md_file.write_text(body, encoding="utf-8")
    return version_id, agents_md_file


def open_service(exp: Path, cfg: dict, dotenv: dict[str, str]) -> tuple[Service, HoneClient]:
    """Start/attach the hone service for the experiment and stage pi-config."""
    service = Service(exp, dotenv, hone_config=cfg.get("hone_config"), model=cfg.get("model"))
    client = service.start_or_attach()
    stage_pi_config(exp, client.url, client.token, cfg["model"], dotenv)
    return service, client


def node_snapshot(exp: Path, client: HoneClient, node_id: str) -> Path:
    """Materialize a specific AGENTS.md version (not necessarily current) to disk."""
    file = exp / "agents-md" / f"{node_id}.md"
    if not file.exists():
        for v in client.state().get("versions", []):
            if v.get("id") == node_id:
                file.parent.mkdir(exist_ok=True)
                file.write_text("\n".join(v.get("file") or []) + "\n", encoding="utf-8")
                return file
        raise RuntimeError(f"version {node_id} not found on service")
    return file


def optimize_with_candidates(exp: Path, cfg: dict, dotenv: dict[str, str], client: HoneClient, *,
                             stage: str, tasks: list[Path], trace_ids: list[str],
                             n_candidates: int) -> tuple[str | None, str, list[dict]]:
    """Run n_candidates optimizer proposals over the same batch, probe each on the
    batch tasks, and promote the best-scoring version to current."""
    scored: list[tuple[int, int, str]] = []
    detail = []
    for k in range(1, n_candidates + 1):
        if k > 1:
            client.post_json("/api/traces/reset", {"ids": trace_ids})
        run = client.post_json("/api/optimize", {"setCurrent": False})
        run_id = run.get("id")
        final = client.wait_idle(cfg["optimize_timeout_s"], run_id=run_id)
        node = (final or {}).get("resultVersionId")
        status = (final or {}).get("status", "unknown")
        if not node:
            log(f"[{stage}] candidate {k}: optimizer {status} — no version proposed")
            detail.append({"candidate": k, "status": status, "node": None})
            continue
        agents_md_file = node_snapshot(exp, client, node)
        probe = run_one_job(exp, stage=f"{stage}/probe_c{k}", task_paths=tasks,
                            agents_md_file=agents_md_file, cfg=cfg, dotenv=dotenv,
                            publish=None, version_id=node, force=True)
        log(f"[{stage}] candidate {k} @ {node}: probe {probe['hits']}/{probe['total']}")
        scored.append((probe["hits"], -k, node))
        detail.append({"candidate": k, "status": status, "node": node,
                       "probe_hits": probe["hits"], "probe_total": probe["total"]})
    if not scored:
        return None, "no candidate produced a version", detail
    scored.sort(reverse=True)
    best_hits, _, best = scored[0]
    client.post_json(f"/api/versions/{best}/current", {})
    return best, f"selected {best} (probe {best_hits}/{len(tasks)})", detail


def stage_batches(args: argparse.Namespace) -> None:
    exp = args.exp.resolve()
    cfg = json.loads((exp / "config.json").read_text())
    dotenv = load_dotenv(REPO / ".env")
    splits = json.loads((exp / "splits" / "manifest.json").read_text())
    service, client = open_service(exp, cfg, dotenv)

    epochs = getattr(args, "epochs", None) or cfg.get("epochs", 1)
    batch_names = [b["name"] for b in splits["batches"]]
    if args.only_batch:
        batch_names = [f"batch_{args.only_batch:02d}"]
    if args.limit_batches:
        batch_names = batch_names[: args.limit_batches]

    summary_path = exp / "batches-summary.json"
    history = json.loads(summary_path.read_text()) if summary_path.exists() else []
    for epoch in range(1, epochs + 1):
        for bname in batch_names:
            tasks = [Path(p) for b in splits["batches"] if b["name"] == bname for p in b["tasks"]]
            if args.limit_tasks:
                tasks = tasks[: args.limit_tasks]
            stage = f"epoch_{epoch:02d}/{bname}"
            prior_entry = next((item for item in history if item.get("stage") == stage), None)
            report_path = exp / stage / "report.json"
            terminal_optimizer_statuses = {"succeeded", "no-changes", "candidates"}
            if (
                report_path.exists()
                and not args.force
                and prior_entry
                and prior_entry.get("optimize_status") in terminal_optimizer_statuses
            ):
                log(
                    f"[{stage}] report and optimizer result exist "
                    f"({prior_entry['optimize_status']}) — skipping completed stage"
                )
                continue
            prev_report = None
            if epoch > 1:
                prev_path = exp / f"epoch_{epoch - 1:02d}" / bname / "report.json"
                if prev_path.exists():
                    prev_report = json.loads(prev_path.read_text())
                    prev_report.setdefault("epoch", epoch - 1)
            batch_note, notes = pre_run_notes(prev_report) if prev_report else ("", {})
            version_id, agents_md_file = snapshot_agents_md(exp, client)
            log(f"[{stage}] {len(tasks)} tasks · AGENTS.md @ {version_id}")
            report = run_one_job(exp, stage=stage, task_paths=tasks, agents_md_file=agents_md_file,
                                 cfg=cfg, dotenv=dotenv, publish=client, version_id=version_id,
                                 feedback_notes=notes, batch_note=batch_note, force=args.force)
            entry = {"epoch": epoch, "batch": bname, "stage": stage,
                     "version": version_id, "score": report["score"],
                     "hits": report["hits"], "total": report["total"]}
            if prev_report is not None:
                progress_line, _ = batch_progress(prev_report, report)
                log(f"[{stage}] {progress_line}")
                entry["delta_vs_prev_epoch"] = report["hits"] - prev_report["hits"]
                entry["progress"] = progress_line
            history = [h for h in history if h.get("stage") != stage]
            history.append(entry)
            summary_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")

            if args.no_optimize:
                log(f"[{stage}] --no-optimize: skipping optimizer")
                continue
            n_candidates = cfg.get("candidates", 1) or 1
            trace_ids = [t["trace_id"] for t in report["trials"] if t.get("trace_id")]
            if n_candidates > 1:
                best, note, cand_detail = optimize_with_candidates(
                    exp, cfg, dotenv, client, stage=stage, tasks=tasks,
                    trace_ids=trace_ids, n_candidates=n_candidates)
                new_version, _ = client.agents_md()
                log(f"[{stage}] candidates done: {note} · AGENTS.md now @ {new_version}")
                entry.update({"optimize_status": "candidates", "optimize_note": note,
                              "candidates": cand_detail, "version_after": new_version})
            else:
                client.post_json("/api/config", {"batchSize": min(64, max(1, len(tasks)))})
                run = client.post_json("/api/optimize", {})
                run_id = run.get("id")
                log(f"[{stage}] optimizer run {run_id} started")
                final = client.wait_idle(cfg["optimize_timeout_s"], run_id=run_id)
                status = (final or {}).get("status", "unknown")
                new_version, _ = client.agents_md()
                log(f"[{stage}] optimizer finished: {status} · AGENTS.md now @ {new_version}")
                entry.update({"optimize_status": status, "version_after": new_version})
            summary_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")

    if not args.keep_service:
        service.stop()


def stage_final(args: argparse.Namespace) -> None:
    exp = args.exp.resolve()
    cfg = json.loads((exp / "config.json").read_text())
    dotenv = load_dotenv(REPO / ".env")
    final_tasks = [Path(p) for p in
                   json.loads((exp / "splits" / "manifest.json").read_text())["final"]["tasks"]]
    if args.limit_tasks:
        final_tasks = final_tasks[: args.limit_tasks]

    service, client = open_service(exp, cfg, dotenv)
    version_id, agents_md_file = snapshot_agents_md(exp, client)
    log(f"[final] {len(final_tasks)} tasks · AGENTS.md @ {version_id}")

    report = run_one_job(exp, stage="final", task_paths=final_tasks, agents_md_file=agents_md_file,
                         cfg=cfg, dotenv=dotenv, publish=None, version_id=version_id,
                         force=args.force)

    summary: dict = {"final": {k: v for k, v in report.items() if k != "trials"},
                     "final_trials": report["trials"], "final_version": version_id}
    baseline = score_baseline_dir(Path(cfg["baseline"])) if cfg.get("baseline") else None
    if baseline:
        final_per_task = {t["task"]: float(t["ok"]) for t in report["trials"]}
        common = sorted(set(final_per_task) & set(baseline["per_task"]))
        f_hits = sum(final_per_task[t] for t in common)
        b_hits = sum(baseline["per_task"][t] for t in common)
        summary["baseline"] = {k: v for k, v in baseline.items() if k != "per_task"}
        summary["comparison"] = {
            "common_tasks": len(common),
            "final_hits": int(f_hits), "baseline_hits": int(b_hits),
            "final_score": f_hits / max(1, len(common)),
            "baseline_score": b_hits / max(1, len(common)),
            "delta": (f_hits - b_hits) / max(1, len(common)),
            "beats_baseline": f_hits > b_hits,
            "flipped_up": [t for t in common if final_per_task[t] > baseline["per_task"][t]],
            "flipped_down": [t for t in common if final_per_task[t] < baseline["per_task"][t]],
        }
    (exp / "final-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    comp = summary.get("comparison")
    if comp:
        log(f"[final] hone {comp['final_hits']}/{comp['common_tasks']} ({comp['final_score']:.1%}) "
            f"vs baseline {comp['baseline_hits']}/{comp['common_tasks']} ({comp['baseline_score']:.1%}) "
            f"· delta {comp['delta']:+.1%} · beats_baseline={comp['beats_baseline']}")
    if not args.keep_service:
        service.stop()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def add_exp_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--exp", type=Path, required=True, help="Experiment directory.")


def add_init_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dataset", type=Path, default=None, help="Harbor dataset dir (task dirs).")
    p.add_argument("--train-count", type=int, default=None)
    p.add_argument("--train-ratio", type=float, default=None)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--epochs", type=int, default=1,
                   help="Number of passes over the same batches (identical tasks each epoch).")
    p.add_argument("--candidates", type=int, default=1,
                       help="Optimizer candidates per batch; >1 probes each candidate on the batch "
                        "tasks and promotes the best score (multi-candidate selection).")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--splits-manifest", type=Path, default=None,
                   help="Reuse an existing splits/ dir instead of splitting.")
    p.add_argument("--model", default="openai/gpt-5.4-mini")
    p.add_argument("--hone-config", type=Path, default=None,
                   help="Service-wide hone.yaml; defaults to the repository configuration.")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--baseline", type=Path, default=None,
                   help="Baseline harbor trials dir with */result.json.")
    p.add_argument("--optimize-timeout", type=float, default=3600.0)


def add_run_args(p: argparse.ArgumentParser, with_epochs: bool = False) -> None:
    if with_epochs:
        p.add_argument("--epochs", type=int, default=None,
                       help="Override the configured number of epochs for this invocation.")
    p.add_argument("--only-batch", type=int, default=None, help="Run a single batch by number.")
    p.add_argument("--limit-batches", type=int, default=None)
    p.add_argument("--limit-tasks", type=int, default=None, help="Cap tasks per batch (pilot).")
    p.add_argument("--no-optimize", action="store_true", help="Skip optimizer after batches.")
    p.add_argument("--keep-service", action="store_true", help="Leave the hone service running.")
    p.add_argument("--force", action="store_true", help="Rerun stages even if reports exist.")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exp", type=Path, default=None, help="(place before the subcommand)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Create experiment dir + splits.")
    add_exp_arg(p_init)
    add_init_args(p_init)

    p_batches = sub.add_parser("batches", help="Training batches + optimization.")
    add_exp_arg(p_batches)
    add_run_args(p_batches, with_epochs=True)

    p_final = sub.add_parser("final", help="Full-dataset run + baseline comparison.")
    add_exp_arg(p_final)
    p_final.add_argument("--limit-tasks", type=int, default=None)
    p_final.add_argument("--keep-service", action="store_true")
    p_final.add_argument("--force", action="store_true")

    p_all = sub.add_parser("all", help="init + batches + final in one go.")
    add_exp_arg(p_all)
    add_init_args(p_all)
    add_run_args(p_all)

    args = ap.parse_args()
    if args.cmd in ("batches", "final") and not (args.exp / "config.json").exists():
        raise SystemExit(f"{args.exp} is not an initialized experiment — run init first")
    return args


def main() -> None:
    for key, value in load_dotenv(REPO / ".env").items():
        os.environ.setdefault(key, value)
    args = parse_args()
    if args.cmd == "init":
        stage_init(args)
    elif args.cmd == "batches":
        stage_batches(args)
    elif args.cmd == "final":
        stage_final(args)
    elif args.cmd == "all":
        stage_init(args)
        stage_batches(args)
        stage_final(args)


if __name__ == "__main__":
    main()
