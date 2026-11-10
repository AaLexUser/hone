"""A scripted stand-in for the in-sandbox MAJICS driver.

A run that uses `Director.executor` goes through Hone's own `start_run`,
`_drive_run` and `MajicsPipeline`. Only the Harbor job is replaced. The
executor posts the driver's event stream through `Hone.record_pipeline_event`
and writes the `review.json` and `proposal.json` artifacts where the pipeline
collects them. Run records, events, the report, the experience log and the
AGENTS.md commit all come from Hone's code.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
import types
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import db as db_mod
from .. import logedits
from .. import service as service_mod
from ..config import HoneConfig
from ..majics.runtime import AGENT_IMPORT_PATH
from ..store import DataDirs
from .stories import Ask, Finding, Proposal, Story

if TYPE_CHECKING:
    from ..service import Hone

AGENT_COLORS = ["#2fbcb0", "#d99a3c", "#b06ee8", "#4aa3f0", "#e5736e"]
TRACE_REF = re.compile(r"@([tx]\d+)")


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #


class Clock:
    """In a build, a virtual clock that jumps, stamped into service time and
    git dates. In a replay, wall time, with script time slept at `speed`x."""

    def __init__(self, *, start_ms: int | None = None, speed: float = 1.0) -> None:
        self.virtual = start_ms is not None
        self.speed = 1.0 if self.virtual else speed
        self._now = start_ms or 0

    def now_ms(self) -> int:
        if not self.virtual:
            return int(time.time() * 1000)
        # Code takes time to run, so back to back service events get distinct stamps.
        self._now += 1
        return self._now

    def set(self, ms: int) -> None:
        assert self.virtual and ms >= self._now, "the virtual clock only moves forward"
        self._now = ms
        self._stamp_git()

    async def sleep(self, script_ms: int) -> None:
        if script_ms <= 0:
            return
        if self.virtual:
            self.set(self._now + script_ms)
        else:
            await asyncio.sleep(script_ms / self.speed / 1000)

    def span(self, script_ms: int) -> int:
        """A duration as the run's own clock measures it."""
        return round(script_ms / self.speed)

    def _stamp_git(self) -> None:
        stamp = f"@{self._now // 1000} +0000"
        os.environ["GIT_AUTHOR_DATE"] = stamp
        os.environ["GIT_COMMITTER_DATE"] = stamp

    def install(self) -> None:
        """Route Hone's clocks through this one. It patches module globals, so
        only a throwaway build process may call it."""
        assert self.virtual
        self._stamp_git()
        service_mod._now_ms = self.now_ms
        shim = types.SimpleNamespace(time=lambda: self._now / 1000)
        logedits.time = shim  # type: ignore[assignment]
        db_mod.time = shim  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Driver emulation, the event stream majics.ts posts for one stage
# --------------------------------------------------------------------------- #


def summarize(value: str) -> str:
    """One line of at most 120 chars, as summarizeArgs in majics.ts."""
    one = re.sub(r"\s+", " ", value).strip()
    return one[:119] + "…" if len(one) > 120 else one


class Timeline:
    def __init__(self) -> None:
        self.items: list[tuple[int, int, dict[str, Any]]] = []

    def add(self, t: int, event: dict[str, Any]) -> None:
        self.items.append((t, len(self.items), event))

    def events(self) -> list[tuple[int, dict[str, Any]]]:
        return [(t, ev) for t, _, ev in sorted(self.items, key=lambda x: (x[0], x[1]))]


class Seat:
    """One pi session in the panel. Its events carry the agentSink fields."""

    def __init__(self, tl: Timeline, rng: random.Random, key: str, model: str, role: str, stage: str) -> None:
        self.tl, self.rng = tl, rng
        self.key, self.model, self.role, self.stage = key, model, role, stage
        self.t = self.t0 = 0

    def _add(self, event: dict[str, Any]) -> None:
        self.tl.add(self.t, {**event, "agent": self.key, "model": self.model, "role": self.role, "stage": self.stage})

    def start(self, t: int) -> Seat:
        self.t = self.t0 = t
        self._add({"kind": "agent_start"})
        return self

    def tool(self, name: str, args: str | None, think: tuple[int, int] = (4000, 16000),
             ms: tuple[int, int] = (40, 600)) -> None:
        self.t += self.rng.randint(*think)
        event: dict[str, Any] = {"kind": "tool", "name": name}
        detail = summarize(args) if args else None
        if detail:
            event["detail"] = detail
        self._add(event)
        self.t += self.rng.randint(*ms)
        done: dict[str, Any] = {"kind": "tool_result", "name": name}
        if detail:
            done["detail"] = detail[:160]
        self._add(done)

    def say(self, text: str, think: tuple[int, int] = (3000, 9000)) -> None:
        self.t += self.rng.randint(*think)
        self._add({"kind": "message", "text": text[:4000]})

    def retry(self) -> None:
        self.t += self.rng.randint(20_000, 45_000)
        self._add({"kind": "retry", "reason": "transient model transport error", "attempt": 1})

    def end(self, error: str | None = None) -> None:
        self.t += self.rng.randint(150, 600)
        event: dict[str, Any] = {"kind": "agent_end", "status": "error" if error else "done",
                                 "durationMs": self.t - self.t0}
        if error:
            event["error"] = error
        self._add(event)


@dataclass
class StageScript:
    boot_ms: int                                    # Harbor build and container start
    events: list[tuple[int, dict[str, Any]]]
    artifacts: dict[str, str]
    teardown_ms: int


@dataclass
class Cast:
    """The story bound to the run's frozen batch. `ids` maps the story's
    trace keys to trace ids, plus `xN` for every session the story does not
    know (a visitor's live chat), whose findings are `extra`."""
    story: Story
    ids: dict[str, str]
    batch: list[str]
    extra: tuple[Finding, ...]
    rng: random.Random
    roster: dict[str, Any]

    @property
    def findings(self) -> tuple[Finding, ...]:
        return self.story.findings + self.extra

    def text(self, value: str) -> str:
        return TRACE_REF.sub(lambda m: self.ids[m.group(1)], value)

    def traces(self, keys: tuple[str, ...]) -> list[str]:
        return [self.ids[k] for k in keys]

    def key_of(self, trace_id: str) -> str:
        return next(k for k, v in self.ids.items() if v == trace_id)


def extra_finding(key: str, feedback: str | None) -> Finding:
    if feedback:
        end = "" if feedback.rstrip()[-1:] in ".!?" else "."
        return Finding(None, (f"@{key} joined this batch from a live chat with the feedback '{feedback}'{end}",),
                       (key,), "medium", "feedback")
    return Finding("OUTCOME_UNKNOWN", ((f"@{key} joined this batch from a live chat without feedback, so its "
                                       "outcome is unknown."),), (key,), "medium", "feedback")


def roster_payload(roster: dict[str, Any]) -> list[dict[str, Any]]:
    """The seats from the materialized majics.json, as rosterPayload in majics.ts."""
    label = lambda spec: f"{spec['id']}@{spec['reasoning']}"
    agents = [{"key": f"review-{i + 1}", "model": label(s), "role": "reviewer", "stage": "review",
               "color": AGENT_COLORS[i % len(AGENT_COLORS)]} for i, s in enumerate(roster["reviewModels"])]
    agents.append({"key": "review-judge", "model": label(roster["reviewJudge"]), "role": "judge",
                   "stage": "review", "color": "#6672e0"})
    agents += [{"key": f"propose-{i + 1}", "model": label(s), "role": "proposer", "stage": "propose",
                "color": AGENT_COLORS[(i + 2) % len(AGENT_COLORS)]} for i, s in enumerate(roster["proposeModels"])]
    agents.append({"key": "propose-judge", "model": label(roster["proposeJudge"]), "role": "judge",
                   "stage": "propose", "color": "#6672e0"})
    return agents


def py(body: str) -> str:
    return f"python3 - <<'EOF'\n{body}\nEOF"


def reviewer_findings(cast: Cast, index: int) -> list[Finding]:
    story = cast.story.findings
    # The third reviewer misses the story's last finding.
    kept = [f for j, f in enumerate(story) if not (index == 2 and len(story) > 2 and j == len(story) - 1)]
    return kept + list(cast.extra)


def reviewer_commands(cast: Cast, index: int) -> list[str]:
    """One reviewer's research path through workspace files, inventory, deep reads and cross checks."""
    rng = cast.rng
    batch = cast.batch
    order = batch[index % len(batch):] + batch[:index % len(batch)]
    grep_style = index % 3 == 1
    commands = [
        "sed -n '1,200p' /app/workspace/agents.md" if grep_style else "cat agents.md",
        py("import json\nev = json.load(open('evidence.json'))\nprint(ev['batch'])\nfor t in ev['traces']:\n"
           "    print(t['id'], t['feedbackPresent'], t['metrics'], [s['code'] for s in t['signals']])"),
        ("python3 -c \"import json; log = json.load(open('log_edits.json')); print(len(log['entries'])); "
        "[print(e['id'], e['outcome'], e['title'], e['signal'][:80]) for e in log['entries']]\""),
        py("import json, glob, collections\nfor p in sorted(glob.glob('traces/*.jsonl')):\n"
           "    rows = [json.loads(l) for l in open(p)]\n    head = rows[0]\n    tools = collections.Counter(\n"
           "        b['name'] for r in rows for b in (r.get('message') or {}).get('content') or []\n"
           "        if isinstance(b, dict) and b.get('type') == 'toolCall')\n"
           "    errors = sum(1 for r in rows if (r.get('message') or {}).get('isError'))\n"
           "    print(p[7:-6], len(rows), dict(tools), errors, (head.get('feedback') or '')[:90])"),
    ]
    findings = reviewer_findings(cast, index)
    for tid in order:
        key = cast.key_of(tid)
        commands.append(py(f"import json\nrows = [json.loads(l) for l in open('traces/{tid}.jsonl')]\n"
                           "print('feedback:', rows[0].get('feedback'))\nfor i, r in enumerate(rows):\n"
                           "    m = r.get('message') or {}\n    if m.get('role') == 'user':\n"
                           "        print(i, [b.get('text') for b in m['content']])"))
        commands.append(py(f"import json\nfor i, line in enumerate(open('traces/{tid}.jsonl')):\n"
                           "    m = json.loads(line).get('message') or {}\n    for b in m.get('content') or []:\n"
                           "        if isinstance(b, dict) and b.get('type') == 'toolCall':\n"
                           "            print(i, b['name'], json.dumps(b['arguments'])[:140])"))
        for f in findings:
            if key not in f.traces:
                continue
            if grep_style:
                commands.append(f"grep -n -o -E '{f.probe}' traces/{tid}.jsonl | sort | uniq -c | head -20")
            else:
                commands.append(py(f"import json, re\nfor i, line in enumerate(open('traces/{tid}.jsonl')):\n"
                                   "    m = json.loads(line).get('message') or {}\n"
                                   "    for b in m.get('content') or []:\n"
                                   f"        for hit in re.findall(r'{f.probe}', json.dumps(b, ensure_ascii=False)):\n"
                                   "            print(i, m.get('role'), hit)"))
        if rng.random() < 0.6:
            commands.append(py(f"import json\nrows = [json.loads(l) for l in open('traces/{tid}.jsonl')]\n"
                               "last = [r['message'] for r in rows if (r.get('message') or {}).get('role') == "
                               "'assistant'][-1]\nprint([b.get('text') for b in last['content'] if b.get('type') "
                               "== 'text'])"))
    for f in findings:
        if len(f.traces) > 1:
            commands.append(py("import glob, re\nfor p in sorted(glob.glob('traces/*.jsonl')):\n"
                               f"    print(p[7:-6], len(re.findall(r'{f.probe}', open(p).read())))"))
    return commands


def reviewer_report(cast: Cast, index: int) -> str:
    story = cast.story
    findings = reviewer_findings(cast, index)
    lines = ["### Verdict", story.verdicts[index % len(story.verdicts)], "", "### Coverage",
             (f"Mode: full. Deep-read: {', '.join(cast.batch)}. Counterexamples sampled: none (every trace "
             "assigned). Inventory-only: none."), "", "### Findings"]
    for n, f in enumerate(findings, 1):
        label = f"{f.label}: " if f.label else ""
        lines.append(f"{n}. {label}{cast.text(f.texts[index % len(f.texts)])} "
                     f"Traces: {', '.join(cast.traces(f.traces))}. Confidence: {f.confidence}.")
    lines += ["", "### Hypotheses"]
    weak_seat = 1 % max(1, len(cast.roster["reviewModels"]))
    for statement, _, confidence, contra in story.hypotheses:
        if confidence == "low" and story.weak_claim and index != weak_seat:
            continue
        needed = (cast.text(" ".join(contra)) if contra
                  else "a later session where the rule is present and the behavior repeats")
        lines.append(f"- {cast.text(statement)} ({confidence}, would disprove it: {needed})")
    if story.weak_claim and index == weak_seat:
        lines.append(f"- {cast.text(story.weak_claim)}")
    lines += ["", "### Failure taxonomy"]
    labels: dict[str, list[str]] = {}
    for f in findings:
        if f.label:
            labels.setdefault(f.label, []).extend(cast.traces(f.traces))
    lines += [f"- {label}: {', '.join(dict.fromkeys(ids_))}" for label, ids_ in labels.items()] or ["- none observed"]
    lines += ["", "### Tool waste and better paths", f"- {cast.text(story.waste[index % len(story.waste)])}",
              "", "### Candidate directions"]
    lines += [f"- {cast.text(d)}" for d in story.directions] or ["- None. No instruction change is supported."]
    lines += ["", "### Unresolved"]
    lines += [f"- {cast.text(u)}" for u in story.unresolved] or ["- none"]
    return "\n".join(lines)


def ask_panel(judge: Seat, panel: list[Seat], asks: tuple[Ask, ...], cast: Cast, stage: str,
              judge_label: str, tl: Timeline) -> None:
    """The judge's single ask_panel call. Parallel reruns, then analytics, then the tool result."""
    rng = cast.rng
    judge.t += rng.randint(25_000, 60_000)
    called = judge.t
    asked: dict[str, tuple[Seat, Ask]] = {}
    for ask in asks:
        worker = panel[ask.seat % len(panel)]
        asked.setdefault(worker.key, (worker, ask))
    judge.tl.add(called, {"kind": "tool", "name": "ask_panel", "agent": judge.key, "model": judge.model,
                          "role": judge.role, "stage": judge.stage,
                          "queries": [{"role": key, "question": cast.text(ask.question)} for key, (_, ask) in asked.items()]})
    finished = called
    timed_out: list[str] = []
    for worker, ask in asked.values():
        worker.start(called + rng.randint(120, 400))
        if ask.timeout:
            worker.tool("bash", "python3 - <<'EOF'\nimport json\nfor l in open('agents.md'): print(l.rstrip())\nEOF",
                        think=(9000, 14000))
            worker.t = worker.t0 + 60_000 + rng.randint(5, 40)
            worker.end(error="model turn timeout after 60s")
            timed_out.append(worker.key)
        else:
            if rng.random() < 0.5:
                worker.tool("bash", f"grep -c -E '{cast.story.findings[0].probe}' traces/*.jsonl", think=(3000, 9000))
            worker.say(cast.text(ask.answer), think=(9000, 30_000))
            worker.end()
        finished = max(finished, worker.t)
    judge.t = finished + rng.randint(20, 80)
    tl.add(judge.t, {
        "kind": "analytics", "name": "ask_panel", "stage": stage, "agent": f"{stage}-judge", "model": judge_label,
        "role": "judge", "workersAsked": len(asked), "workersTimedOut": len(timed_out), "timedOutRoles": timed_out,
        "queriesAsked": len(asked), "queriesTimedOut": len(timed_out), "timeoutMs": 60_000,
        "durationMs": judge.t - called, "text": f"ask_panel: {len(timed_out)} worker timeout(s)",
        "detail": ", ".join(timed_out) if timed_out else "none",
    })
    judge.t += rng.randint(5, 30)
    judge.tl.add(judge.t, {"kind": "tool_result", "name": "ask_panel", "agent": judge.key, "model": judge.model,
                           "role": judge.role, "stage": judge.stage})


def review_script(cast: Cast) -> StageScript:
    story, rng, roster = cast.story, cast.rng, cast.roster
    tl = Timeline()
    tl.add(0, {"kind": "pipeline", "attempt": 1, "agents": roster_payload(roster)})
    tl.add(6, {"kind": "stage", "stage": "review", "status": "start"})
    panel = [Seat(tl, rng, f"review-{i + 1}", f"{s['id']}@{s['reasoning']}", "reviewer", "review")
             for i, s in enumerate(roster["reviewModels"])]
    for i, seat in enumerate(panel):
        seat.start(rng.randint(1200, 2800))
        commands = reviewer_commands(cast, i)
        for n, command in enumerate(commands):
            seat.tool("bash", command, ms=(15, 60) if command.startswith(("cat", "sed", "grep")) else (60, 700))
            if n == 3 and i % 2 == 0:
                seat.say(f"Inventory done: {len(cast.batch)} traces, all in full coverage. Deep-reading each.")
            if story.transport_retry and i == 1 % len(panel) and n == len(commands) // 2:
                seat.retry()
        seat.say(reviewer_report(cast, i), think=(35_000, 80_000))
        seat.end()
    judge_spec = roster["reviewJudge"]
    judge_label = f"{judge_spec['id']}@{judge_spec['reasoning']}"
    judge = Seat(tl, rng, "review-judge", judge_label, "judge", "review")
    judge.start(max(s.t for s in panel) + rng.randint(900, 1800))
    judge.tool("bash", py(f"import json\nfor tid in {cast.batch!r}:\n    h = json.loads(open(f'traces/{{tid}}.jsonl')"
                          ".readline())\n    print(tid, (h.get('feedback') or '')[:100])"), think=(20_000, 40_000))
    for f in story.findings:
        if len(f.traces) == 1:
            judge.tool("bash", f"grep -n -o -E '{f.probe}' traces/{cast.ids[f.traces[0]]}.jsonl | head -12",
                       think=(8000, 20_000), ms=(15, 50))
    if story.review_asks:
        ask_panel(judge, panel, story.review_asks, cast, "review", judge_label, tl)
    review = {
        "version": 1,
        "summary": cast.text(story.summary),
        "findings": [{"statement": cast.text(f.texts[0]), "traceIds": cast.traces(f.traces),
                      "confidence": f.confidence} for f in cast.findings],
        "hypotheses": [{"statement": cast.text(s), "traceIds": cast.traces(t), "confidence": c,
                        **({"contradictions": [cast.text(x) for x in contra]} if contra else {})}
                       for s, t, c, contra in story.hypotheses],
        "directions": [cast.text(d) for d in story.directions],
        "unresolved": [cast.text(u) for u in story.unresolved],
    }
    judge.tool("submit_review", review["summary"], think=(50_000, 95_000), ms=(4, 20))
    judge.say("Review submitted.", think=(2000, 4000))
    judge.end()
    text = json.dumps(review, ensure_ascii=False, indent=2) + "\n"
    t = judge.t + rng.randint(30, 120)
    tl.add(t, {"kind": "stage", "stage": "review", "status": "end", "durationMs": t})
    tl.add(t + rng.randint(5, 20), {"kind": "report", "bytes": len(text.encode("utf-8")),
                                    "title": review["summary"][:120]})
    return StageScript(rng.randint(38_000, 75_000), tl.events(),
                       {"review.json": text, "driver-error.txt": ""}, rng.randint(5000, 12_000))


def proposal_payload(cast: Cast, proposal: Proposal) -> dict[str, Any]:
    return {"edits": [{"oldText": e.old, "newText": e.new, "rationale": cast.text(e.rationale),
                       "evidence": cast.traces(e.evidence)} for e in proposal.edits],
            "note": cast.text(proposal.note)}


def propose_script(cast: Cast, attempt: int) -> StageScript:
    story, rng, roster = cast.story, cast.rng, cast.roster
    failing = attempt <= story.failed_propose_attempts
    tl = Timeline()
    tl.add(0, {"kind": "pipeline", "attempt": attempt, "agents": roster_payload(roster)})
    tl.add(5, {"kind": "stage", "stage": "propose", "status": "start"})
    panel = [Seat(tl, rng, f"propose-{i + 1}", f"{s['id']}@{s['reasoning']}", "proposer", "propose")
             for i, s in enumerate(roster["proposeModels"])]
    submitted: list[Proposal] = []
    for i, seat in enumerate(panel):
        proposal = story.proposals[i % len(story.proposals)]
        seat.start(rng.randint(1200, 2600))
        seat.tool("bash", "cat agents.md", ms=(10, 40))
        seat.tool("bash", "python3 -c \"import json; log = json.load(open('log_edits.json')); "
                          "[print(e['id'], e['outcome'], e['commit'], e['title']) for e in log['entries'][:5]]\"")
        if failing and i == len(panel) - 1:
            seat.tool("bash", py("import json\nr = json.load(open('review.json'))\nfor f in r['findings']:\n"
                                 "    print(f['confidence'], f['traceIds'], f['statement'][:100])"))
            seat.t += rng.randint(40_000, 70_000)
            seat.end(error="did not complete cleanly (stopReason: error): 503 upstream overloaded")
            continue
        for e in proposal.edits[:3]:
            tid = cast.ids[e.evidence[0]]
            seat.tool("bash", py(f"import json\nfor i, line in enumerate(open('traces/{tid}.jsonl')):\n"
                                 "    m = json.loads(line).get('message') or {}\n    if m.get('role') == "
                                 "'toolResult':\n        print(i, m['toolName'], m['content'][0]['text'][:160])"))
        anchors = [e.old for e in proposal.edits if e.old]
        if anchors:
            seat.tool("bash", py(f"text = open('agents.md').read()\nfor a in {[a[:60] for a in anchors]!r}:\n"
                                 "    print(text.count(a), a)"))
        payload = proposal_payload(cast, proposal)
        seat.tool("submit_proposal", payload["note"], think=(35_000, 75_000), ms=(3, 15))
        count = len(proposal.edits)
        seat.say(f"Proposal submitted: {count} edit{'s' if count != 1 else ''}.", think=(1500, 3500))
        seat.end()
        submitted.append(proposal)
    if failing:
        failed = panel[-1]
        message = f"{failed.model}: did not complete cleanly (stopReason: error): 503 upstream overloaded"
        stack = (f"Error: {message}\n    at runPanel (file:///app-driver/majics.ts:490:11)\n"
                 "    at async proposeStage (file:///app-driver/majics.ts:813:17)\n"
                 "    at async main (file:///app-driver/majics.ts:918:22)\n")
        return StageScript(rng.randint(30_000, 60_000), tl.events(), {"driver-error.txt": stack},
                           rng.randint(4000, 9000))
    t = max(s.t for s in panel) + rng.randint(40, 160)
    for seat, proposal in zip(panel, submitted, strict=True):
        payload = proposal_payload(cast, proposal)
        tl.add(t, {"kind": "proposal", "agent": seat.key, "count": len(proposal.edits),
                   "note": payload["note"][:200],
                   "edits": [{"oldText": e["oldText"][:160], "newText": e["newText"][:240],
                              "rationale": e["rationale"][:240], "evidence": e["evidence"]}
                             for e in payload["edits"]]})
        t += rng.randint(8, 30)
    judge_spec = roster["proposeJudge"]
    judge_label = f"{judge_spec['id']}@{judge_spec['reasoning']}"
    judge = Seat(tl, rng, "propose-judge", judge_label, "judge", "propose")
    judge.start(t + rng.randint(900, 1700))
    anchors = sorted({e.old[:60] for p in submitted for e in p.edits if e.old})
    if anchors:
        judge.tool("bash", py(f"text = open('agents.md').read()\nfor a in {anchors!r}:\n    print(text.count(a), a)"),
                   think=(15_000, 30_000))
    if story.propose_asks:
        ask_panel(judge, panel, story.propose_asks, cast, "propose", judge_label, tl)
    final = proposal_payload(cast, story.final)
    judge.tool("submit_proposal", final["note"], think=(45_000, 80_000), ms=(3, 15))
    count = len(story.final.edits)
    judge.say(f"Submitted the fused proposal: {count} edit{'s' if count != 1 else ''}, commit "
              f"'{story.commit_title}'.", think=(1500, 3500))
    judge.end()
    t = judge.t + rng.randint(30, 120)
    tl.add(t, {"kind": "stage", "stage": "propose", "status": "end", "durationMs": t})
    tl.add(t + rng.randint(5, 20), {"kind": "commit", "title": story.commit_title, "body": story.commit_body})
    artifact = {"edits": final["edits"], "note": final["note"], "commit_title": story.commit_title,
                "commit_body": story.commit_body}
    return StageScript(rng.randint(25_000, 50_000), tl.events(),
                       {"proposal.json": json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                        "driver-error.txt": ""}, rng.randint(5000, 11_000))


# --------------------------------------------------------------------------- #
# Director and executor
# --------------------------------------------------------------------------- #


class Director:
    """Plays one story's stage scripts for one run. `ids` maps the story's
    trace keys to the trace ids of the prepared sessions."""

    def __init__(self, hone: Hone, clock: Clock, story: Story, ids: dict[str, str], seed: int) -> None:
        self.hone = hone
        self.clock = clock
        self.story = story
        self.ids = ids
        self.seed = seed

    def executor(self, settings: HoneConfig, dirs: DataDirs, run_id: str,
                 emit: Callable[..., Any]) -> ScriptedExecutor:
        """An `ExecutorFactory` for `Hone.start_run`."""
        return ScriptedExecutor(self, dirs, run_id, emit)

    def cast(self, run_id: str, task_dir: Path, stage: str, attempt: int) -> Cast:
        run = self.hone.db.run(run_id)
        assert run is not None
        batch: list[str] = run["trace_ids"]
        ids = {k: self.ids[k] for k in self.story.batch}
        missing = [k for k, tid in ids.items() if tid not in batch]
        if missing:
            raise RuntimeError(f"run {run_id} did not freeze the prepared sessions {missing}")
        known = set(ids.values())
        extra: list[Finding] = []
        for n, tid in enumerate((t for t in batch if t not in known), 1):
            key = f"x{n}"
            ids[key] = tid
            row = self.hone.db.one("SELECT feedback FROM traces WHERE session_id = ?", (tid,))
            extra.append(extra_finding(key, (row or {}).get("feedback")))
        environment = task_dir / "environment"
        return Cast(
            story=self.story,
            ids=ids,
            batch=batch,
            extra=tuple(extra),
            rng=random.Random(f"{self.seed}:{self.story.key}:{stage}:{attempt}"),
            roster=json.loads((environment / "config" / "majics.json").read_text(encoding="utf-8")),
        )

    async def play(self, run_id: str, script: StageScript) -> None:
        await self.clock.sleep(script.boot_ms)
        last = 0
        for t, event in script.events:
            await self.clock.sleep(t - last)
            last = t
            if "durationMs" in event:
                event = {**event, "durationMs": self.clock.span(event["durationMs"])}
            await self.hone.record_pipeline_event(run_id, event)
        await self.clock.sleep(script.teardown_ms)


class ScriptedExecutor:
    """The `HarborMajicsExecutor` contract with the in-sandbox driver replaced
    by a scripted event stream."""

    def __init__(self, director: Director, dirs: DataDirs, run_id: str, emit: Callable[..., Any]) -> None:
        self.director = director
        self.dirs = dirs
        self.run_id = run_id
        self.emit = emit

    async def run(self, stage: str, task_dir: Path, attempt: int) -> Path:
        jobs_dir = self.dirs.run_dir(self.run_id) / "majics" / f"{stage}-a{attempt}" / "jobs"
        job_dir = jobs_dir / f"{self.run_id}-{stage}-a{attempt}"
        self.emit("log", icon="read", text=f"{stage} job: launching Harbor",
                  detail=f"custom agent · {AGENT_IMPORT_PATH}")
        cast = self.director.cast(self.run_id, task_dir, stage, attempt)
        script = review_script(cast) if stage == "review" else propose_script(cast, attempt)
        await self.director.play(self.run_id, script)
        token = "".join(cast.rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
                        for _ in range(7))
        artifacts = job_dir / f"task__{token}" / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        for name, text in script.artifacts.items():
            (artifacts / name).write_text(text, encoding="utf-8")
        return job_dir
