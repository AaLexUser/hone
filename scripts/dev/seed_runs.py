"""Seed a Hone data dir with a realistic demo history, or replay a run live.

The demo persona is Mei, an HR coordinator who asks her Pi agent every working
day to fill the offer-letter template from employee_data.json, and who leaves
short feedback on the result. `seed` writes her sessions as Pi session JSONL
and runs three optimizer runs over them (two commits and one no-change run);
`live` replays a fourth run against a running Hone service so the run page
animates exactly as it does for a real run.

Nothing here writes Hone's files by hand. Both commands drive the service's
own `Hone.start_run` -> `_drive_run` -> `MajicsPipeline`, and replace only the
Harbor executor: a scripted executor plays the MAJICS driver's event stream
through `Hone.record_pipeline_event` and writes the `review.json` /
`proposal.json` artifacts where the pipeline collects them. Run records,
events.jsonl, report.html, result.json, evidence.json, task bundles,
log_edits.json and the AGENTS.md commits all come from Hone's code.

Usage:
    uv run python scripts/dev/seed_runs.py seed --data-dir /tmp/hone-seed \\
        [--reviewers 3] [--proposers 3] [--seed 7] [--end 2026-11-02] [--force]

    # with a service running on the dir, e.g.
    #   HONE_CONFIG=/tmp/hone-seed/hone.yaml HONE_PORT=8090 uvicorn hone.api:app --port 8090
    uv run python scripts/dev/seed_runs.py live --data-dir /tmp/hone-seed \\
        [--speed 11] [--service http://127.0.0.1:8090] [--rewind]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import functools
import json
import os
import random
import re
import shutil
import sys
import time
import types
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from hone import db as db_mod
from hone import ids, logedits
from hone import service as service_mod
from hone.config import HoneConfig
from hone.majics import pipeline as pipeline_mod
from hone.majics.runtime import AGENT_IMPORT_PATH
from hone.service import Hone

REPO = Path(__file__).resolve().parents[2]
DAY_MS = 86_400_000
LIVE_RUN_ID = "r_1cd0"

# --------------------------------------------------------------------------- #
# Roster and config
# --------------------------------------------------------------------------- #

# (alias, provider, model id, display name)
MODELS = [
    ("deepseek-v4.1-flash", "opencode-go", "deepseek-v4.1-flash", "DeepSeek V4.1 Flash"),
    ("glm-5.2", "opencode-go", "glm-5.2", "GLM 5.2"),
    ("mimo-v2.5-pro", "opencode-go", "mimo-v2.5-pro", "MiMo V2.5 Pro"),
    ("minimax-m3", "opencode-go", "minimax-m3", "MiniMax M3"),
    ("kimi-k2.6", "opencode-go", "kimi-k2.6", "Kimi K2.6"),
    ("gpt-5.4-mini", "openai", "gpt-5.4-mini", "GPT-5.4 mini"),
]
REVIEW_PANEL = ["deepseek-v4.1-flash", "glm-5.2", "mimo-v2.5-pro", "minimax-m3", "kimi-k2.6"]
PROPOSE_PANEL = ["glm-5.2", "deepseek-v4.1-flash", "minimax-m3", "kimi-k2.6", "mimo-v2.5-pro"]
JUDGE = "gpt-5.4-mini"
AGENT_COLORS = ["#2fbcb0", "#d99a3c", "#b06ee8", "#4aa3f0", "#e5736e"]


def config_raw(reviewers: int, proposers: int) -> dict[str, Any]:
    """The hone.yaml document for the seeded dir; data_dir is the file's own dir."""
    seat = lambda alias: {"model": alias, "reasoning": "high"}  # noqa: E731
    return {
        "version": 1,
        "service": {
            "data_dir": ".",
            "token": "dev-token",
            "host": "127.0.0.1",
            "port": 8090,
            "ui_dir": str(REPO / "apps" / "web" / "dist"),
        },
        "target": {"model": "openai/gpt-5.4-mini"},
        "optimization": {"max_attempts": 3, "stage_timeout_s": 3600},
        "majics": {
            "providers": {
                "opencode-go": {"name": "OpenCode Go", "base_url": "https://opencode.ai/zen/go/v1",
                                "api_key_env": "OPENCODE_API_KEY"},
                "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1",
                           "api_key_env": "OPENAI_API_KEY"},
            },
            "models": {
                alias: {"provider": provider, "id": model_id, "name": name, "reasoning": True,
                        "input": ["text"], "context_window": 272000, "max_tokens": 128000}
                for alias, provider, model_id, name in MODELS
            },
            "review": {"panel": [seat(REVIEW_PANEL[i % len(REVIEW_PANEL)]) for i in range(reviewers)],
                       "judge": seat(JUDGE)},
            "propose": {"panel": [seat(PROPOSE_PANEL[i % len(PROPOSE_PANEL)]) for i in range(proposers)],
                        "judge": seat(JUDGE)},
        },
    }


def settings_for(data_dir: Path, raw: dict[str, Any]) -> HoneConfig:
    config = HoneConfig.model_validate(raw)
    return config.model_copy(update={
        "service": config.service.model_copy(update={"data_dir": data_dir.resolve()}),
    })


def load_seeded_settings(data_dir: Path) -> HoneConfig:
    path = data_dir / "hone.yaml"
    if not (path.exists() and (data_dir / "app.sqlite").exists()):
        raise SystemExit(f"{data_dir} is not a seeded dir (run `seed` first)")
    return settings_for(data_dir, yaml.safe_load(path.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# Clock
# --------------------------------------------------------------------------- #


class Clock:
    """Seed mode: a virtual clock that jumps, stamped into service time and git
    dates. Live mode: wall time, with script time slept at `speed`x."""

    def __init__(self, *, start_ms: int | None = None, speed: float = 1.0) -> None:
        self.virtual = start_ms is not None
        self.speed = speed if not self.virtual else 1.0
        self._now = start_ms or 0
        if self.virtual:
            self._stamp_git()

    def now_ms(self) -> int:
        if not self.virtual:
            return int(time.time() * 1000)
        # Code takes time to run: back-to-back service events get distinct stamps.
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
        """Route Hone's clocks through this one (seed mode only)."""
        if not self.virtual:
            return
        service_mod._now_ms = self.now_ms
        shim = types.SimpleNamespace(time=lambda: self._now / 1000)
        logedits.time = shim
        db_mod.time = shim


def iso(ms: int) -> str:
    stamp = dt.datetime.fromtimestamp(ms / 1000, dt.UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def ms_at(end: dt.date, day: int, hhmm: str) -> int:
    hh, mm = (int(x) for x in hhmm.split(":"))
    when = dt.datetime.combine(end - dt.timedelta(days=day), dt.time(hh, mm), dt.UTC)
    return int(when.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# Persona: Mei's offer-letter sessions
# --------------------------------------------------------------------------- #

CWD = "/Users/mei/Documents/HR/Offers"
COMPANY = "Kestrel Analytics Ltd"

US_DATES = "us_dates"              # month-first dates
OLD_NAMES = "old_names"            # Offer_Letter_First_Last.docx
NO_PDF = "no_pdf"
RELOC_GAP = "reloc_gap"            # strips IF markers, leaves heading + empty paragraph
INVENTED_MANAGER = "invented_manager"
PDF_FALLBACK = "pdf_fallback"      # docx2pdf missing -> reportlab re-types the text
COLLAPSED_RUNS = "collapsed_runs"  # paragraph text written into the first run
ZERO_ROWS = "zero_rows"            # prints £0 / 0 shares rows


@dataclass(frozen=True)
class Hire:
    key: str
    day: int        # days before --end
    clock: str      # session start, UTC
    first: str
    last: str
    position: str
    department: str
    street: str
    city: str
    postcode: str
    salary: str
    bonus: str
    equity: str
    relocation: str | None   # amount when the package applies
    manager: str | None      # None: employee_data.json has no MANAGER_NAME
    ask: str
    flaws: frozenset[str] = frozenset()
    feedback: str | None = None
    answer: str | None = None  # Mei's reply when the agent asks for the manager


V0 = frozenset({US_DATES, OLD_NAMES, NO_PDF})
HIRES = [
    Hire("t01", 14, "09:42", "Sarah", "Chen", "Senior Data Engineer", "Data Platform",
         "14 Albion Road", "London", "N16 9JS", "78,000", "5,000", "1,500", "8,000", "Tom Becker",
         "New hire today: please prepare the offer letter from employee_data.json. Keep your reply short.",
         V0, "Write dates like 1 December 2026, as all our letters do"),
    Hire("t02", 13, "10:15", "Tomás", "Herrera", "Product Designer", "Design",
         "3 Cotham Hill", "Bristol", "BS6 6LA", "64,000", "3,000", "800", None, "Grace Holt",
         "Offer letter for Tomás please, data's in employee_data.json, template as usual.",
         V0 | {RELOC_GAP, COLLAPSED_RUNS}, "There's a big empty gap where the relocation part was"),
    Hire("t03", 12, "14:03", "Aisha", "Okafor", "Machine Learning Engineer", "Applied ML",
         "27 Marchmont Road", "Edinburgh", "EH9 1HX", "82,000", "6,000", "2,000", "6,500", "Tom Becker",
         "Can you do the offer letter for today's new hire? employee_data.json is updated.",
         V0, "I need a PDF too; name it Offer_Lastname_Firstname"),
    Hire("t04", 11, "09:58", "Daniel", "Novak", "Account Executive", "Sales",
         "8 Wilmslow Road", "Manchester", "M14 5TP", "58,000", "4,000", "600", "4,000", None,
         "Please prepare Daniel Novak's offer letter from the template and employee_data.json.",
         V0 | {INVENTED_MANAGER}, "Don't make up the manager, ask me"),
    Hire("t05", 10, "11:20", "Lena", "Fischer", "Data Analyst", "Analytics",
         "41 Hyde Park Road", "Leeds", "LS6 1AF", "52,000", "2,500", "500", "5,000", "Priya Shah",
         "New hire today: please prepare the offer letter from employee_data.json.",
         feedback="Perfect, that's exactly it"),
    Hire("t06", 7, "10:05", "Wei", "Zhang", "Backend Engineer", "Platform",
         "19 Mill Road", "Cambridge", "CB1 2AD", "74,000", "5,000", "1,200", "9,000", "Tom Becker",
         "Offer letter for the new backend engineer please, employee_data.json has everything.",
         feedback="For this candidate write Zhang Wei, family name first"),
    Hire("t07", 6, "15:40", "Priya", "Raman", "Finance Analyst", "Finance",
         "5 Jesmond Road", "Newcastle", "NE2 1NL", "55,000", "3,000", "400", None, "Owen Price",
         "Can you prepare Priya's offer letter? employee_data.json is ready.",
         frozenset({PDF_FALLBACK}), "Keep the template formatting; the salary line lost its bold"),
    Hire("t08", 5, "09:30", "Jonas", "Berg", "Site Reliability Engineer", "Infrastructure",
         "12 Gloucester Road", "Bristol", "BS7 8AE", "76,000", "5,000", "1,000", "7,500", "Sam Okoro",
         "New hire today: please prepare the offer letter from employee_data.json. Keep your reply short.",
         frozenset({COLLAPSED_RUNS}),
         "The deadline line lost its bold and underline. Please keep the template formatting exactly."),
    Hire("t09", 4, "13:12", "Hana", "Sato", "UX Researcher", "Design",
         "30 Clarendon Road", "London", "W11 3AD", "61,000", "3,000", "700", None, "Grace Holt",
         "Offer letter for Hana please, data's in employee_data.json.",
         feedback="Perfect, that's exactly it"),
    Hire("t10", 3, "10:48", "Marco", "Bianchi", "Solutions Engineer", "Sales",
         "2 Deansgate", "Manchester", "M3 2BW", "66,000", "4,000", "900", "3,000", None,
         "Please prepare Marco Bianchi's offer letter from the template and employee_data.json.",
         answer="Rachel Moore"),
    Hire("t11", 0, "09:25", "Olivia", "Grant", "Office Manager", "Operations",
         "9 Grove Lane", "London", "SE5 8SY", "46,000", "0", "400", None, "Nadia Wells",
         "New hire today: please prepare the offer letter from employee_data.json.",
         frozenset({ZERO_ROWS}),
         "There's a '£0' sign-on bonus line. If there's no bonus, just leave the line out."),
    Hire("t12", 0, "11:40", "Yusuf", "Demir", "Data Scientist", "Applied ML",
         "16 Bath Street", "Glasgow", "G2 4JR", "71,000", "3,000", "0", "6,000", "Tom Becker",
         "Offer letter for Yusuf please, employee_data.json is updated.",
         frozenset({ZERO_ROWS}),
         "Same thing with equity: '0 shares' looks odd, drop the line when there's none."),
    Hire("t13", 0, "14:55", "Chloé", "Martin", "Marketing Lead", "Marketing",
         "22 Princess Street", "Manchester", "M1 4LG", "69,000", "4,000", "800", "5,500", "Nadia Wells",
         "Can you do the offer letter for today's new hire? employee_data.json is ready.",
         feedback="Perfect, that's exactly it"),
]

TEMPLATE_DUMP = """\
'EMPLOYMENT OFFER'
'{{COMPANY_NAME}}'
''
'Date: {{DATE}}'
''
'{{CANDIDATE_FULL_NAME}}'
'{{STREET_ADDRESS}}'
'{{CITY}} {{POSTCODE}}'
''
'RE: Offer of Employment - {{POSITION}}'
''
'Dear {{CANDIDATE_FIRST_NAME}},'
''
'We are pleased to offer you the position of {{POSITION}} in our {{DEPARTMENT}} team, starting on {{START_DATE}}.'
''
'Relocation Assistance:'
'{{IF_RELOCATION}}You are eligible for a relocation package of £{{RELOCATION_AMOUNT}}, covering moving expenses and temporary housing for {{RELOCATION_DAYS}} days.{{END_IF_RELOCATION}}'
''
'You will receive {{PTO_DAYS}} days of annual leave.'
''
'Please respond by {{RESPONSE_DEADLINE}}.'
''
'Kind regards,'
''
'{{HR_NAME}}'
'{{HR_TITLE}}'
'{{COMPANY_NAME}}'
TABLE
 ['Position:', '{{POSITION}}']
 ['Department:', '{{DEPARTMENT}}']
 ['Start Date:', '{{START_DATE}}']
 ['Reports To:', '{{MANAGER_NAME}}']
 ['Base Salary:', '£{{BASE_SALARY}} per year']
 ['Sign-on Bonus:', '£{{SIGNING_BONUS}}']
 ['Equity Grant:', '{{EQUITY_SHARES}} shares']
HEADER ['Document ID: {{DOC_ID}}']
FOOTER ['Confidential - {{COMPANY_NAME}}']
"""

DUMP_COMMAND = """\
cd __CWD__ && python3 -c "
from docx import Document
d = Document('offer_letter_template.docx')
for p in d.paragraphs: print(repr(p.text))
print('TABLE')
for t in d.tables:
    for r in t.rows: print('', [c.text for c in r.cells])
s = d.sections[0]
print('HEADER', [p.text for p in s.header.paragraphs])
print('FOOTER', [p.text for p in s.footer.paragraphs])
\""""

FILL_SCRIPT = """\
import datetime, json
from docx import Document

data = json.load(open('employee_data.json'))
data.setdefault('MANAGER_NAME', __MANAGER__)
for key in ('DATE', 'START_DATE', 'RESPONSE_DEADLINE'):
    d = datetime.date.fromisoformat(data[key])
    data[key] = __DATE_EXPR__
values = {'{{' + k + '}}': str(v) for k, v in data.items()}
reloc = data.get('RELOCATION_PACKAGE') == 'Yes'


def paragraphs(container):
    yield from getattr(container, 'paragraphs', [])
    for table in getattr(container, 'tables', []):
        for row in table.rows:
            for cell in row.cells:
                yield from paragraphs(cell)


def fill(p):
    text = ''.join(r.text for r in p.runs)
    if '{{' not in text:
        return
__FILL_BODY__

doc = Document('offer_letter_template.docx')
sections = [doc] + [s.header for s in doc.sections] + [s.footer for s in doc.sections]
for part in sections:
    for p in list(paragraphs(part)):
__CONDITIONAL__
        fill(p)
doc.save('__OUT__')
left = [p.text for part in sections for p in paragraphs(part) if '{{' in p.text]
print('wrote __OUT__')
print('unresolved:', left)
"""

FILL_COLLAPSE = """\
    for key, value in values.items():
        text = text.replace(key, value)
    p.runs[0].text = text
    for r in p.runs[1:]:
        r.text = ''"""

FILL_RUN_AWARE = """\
    # placeholders can be split across runs: merge each one into the run
    # where it starts so every other run keeps its own formatting
    runs = p.runs
    i = 0
    while i < len(runs):
        if '{{' in runs[i].text and '}}' not in runs[i].text.split('{{', 1)[1]:
            j = i + 1
            while j < len(runs) and '}}' not in runs[i].text.split('{{')[-1]:
                runs[i].text += runs[j].text
                runs[j].text = ''
                j += 1
        for key, value in values.items():
            runs[i].text = runs[i].text.replace(key, value)
        i += 1"""

COND_STRIP = """\
        if '{{IF_RELOCATION}}' in p.text and not reloc:
            for r in p.runs:
                r.text = ''
            continue
        for r in p.runs:
            r.text = r.text.replace('{{IF_RELOCATION}}', '').replace('{{END_IF_RELOCATION}}', '')"""

COND_DELETE = """\
        if '{{IF_RELOCATION}}' in p.text:
            if not reloc:
                heading = p._p.getprevious()
                p._p.getparent().remove(p._p)
                if heading is not None and 'Relocation Assistance' in ''.join(heading.itertext()):
                    heading.getparent().remove(heading)
                continue
            for r in p.runs:
                r.text = r.text.replace('{{IF_RELOCATION}}', '').replace('{{END_IF_RELOCATION}}', '')"""

REPORTLAB_SCRIPT = """\
from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

doc = Document('__DOCX__')
pdf = canvas.Canvas('__PDF__', pagesize=A4)
y = 800
for p in doc.paragraphs:
    pdf.drawString(60, y, p.text)
    y -= 16
for t in doc.tables:
    for row in t.rows:
        pdf.drawString(60, y, '  '.join(c.text for c in row.cells))
        y -= 16
pdf.save()
print('wrote __PDF__')
"""

SYSTEM_SECTIONS = {
    "preamble": "You are a coding assistant running inside pi, a coding agent harness. "
                "Help users inspect files, run commands, and modify code.",
    "tools": "<tools>\n- read: Read file contents\n- bash: Execute bash commands (ls, grep, find, etc.)\n"
             "- edit: Make precise file edits with exact text replacement, including multiple disjoint "
             "edits in one call\n- write: Create or overwrite files\n\nAdditional tools may be available.\n</tools>",
    "rules": "<rules>\n- Use bash for file operations like ls, rg, find\n- Use read to examine files instead "
             "of cat or sed.\n- You can inspect PI_* environment variables for current model and session "
             "details.\n- Use edit for targeted changes. Batch changes to one file in a single call.\n"
             "- Each edits[].oldText must exactly and uniquely match the original file. Keep matches short "
             "and non-overlapping; merge nearby changes without including large unchanged regions.\n"
             "- Use write only for new files or complete rewrites.\n- Be concise in your responses\n"
             "- Show file paths clearly when working with files\n</rules>",
    "docs": "<docs>\nPi documentation (read only when the user asks about the harness itself, its SDK, "
            "extensions, themes, skills, or TUI):\n- Main documentation: "
            "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/README.md\n</docs>",
}
TOOLS_ADDED = [
    {"name": "read", "description": "Read the contents of a file. Supports text files and images."},
    {"name": "bash", "description": "Execute a bash command in the current working directory."},
    {"name": "edit", "description": "Edit a file using exact text replacement."},
    {"name": "write", "description": "Write content to a file. Creates the file if it doesn't exist."},
]


def fmt_date(d: dt.date, us: bool) -> str:
    return f"{d:%B} {d.day}, {d.year}" if us else f"{d.day} {d:%B} {d.year}"


def hire_dates(h: Hire, end: dt.date) -> tuple[dt.date, dt.date, dt.date]:
    letter = end - dt.timedelta(days=h.day)
    start = letter + dt.timedelta(days=28)
    start += dt.timedelta(days=(7 - start.weekday()) % 7)  # first Monday on or after
    return letter, start, letter + dt.timedelta(days=7)


def out_name(h: Hire, ext: str) -> str:
    stem = f"Offer_Letter_{h.first}_{h.last}" if OLD_NAMES in h.flaws else f"Offer_{h.last}_{h.first}"
    return f"{stem}.{ext}"


def employee_data(h: Hire, n: int, end: dt.date) -> dict[str, str]:
    letter, start, deadline = hire_dates(h, end)
    data = {
        "DOC_ID": f"OFFER-{letter.year}-{214 + n:04d}",
        "COMPANY_NAME": COMPANY,
        "DATE": letter.isoformat(),
        "CANDIDATE_FIRST_NAME": h.first,
        "CANDIDATE_LAST_NAME": h.last,
        "CANDIDATE_FULL_NAME": f"{h.first} {h.last}",
        "STREET_ADDRESS": h.street,
        "CITY": h.city,
        "POSTCODE": h.postcode,
        "POSITION": h.position,
        "DEPARTMENT": h.department,
        "START_DATE": start.isoformat(),
        "MANAGER_NAME": h.manager or "",
        "BASE_SALARY": h.salary,
        "SIGNING_BONUS": h.bonus,
        "EQUITY_SHARES": h.equity,
        "RELOCATION_PACKAGE": "Yes" if h.relocation else "No",
        "RELOCATION_AMOUNT": h.relocation or "",
        "RELOCATION_DAYS": "30" if h.relocation else "",
        "PTO_DAYS": "25",
        "RESPONSE_DEADLINE": deadline.isoformat(),
        "HR_NAME": "Mei Lin",
        "HR_TITLE": "HR Coordinator",
    }
    if h.manager is None:
        del data["MANAGER_NAME"]
    return data


def letter_text(h: Hire, end: dt.date, manager: str) -> str:
    letter, start, deadline = hire_dates(h, end)
    us = US_DATES in h.flaws
    lines = [
        "EMPLOYMENT OFFER", COMPANY, "", f"Date: {fmt_date(letter, us)}", "",
        f"{h.first} {h.last}", h.street, f"{h.city} {h.postcode}", "",
        f"RE: Offer of Employment - {h.position}", "", f"Dear {h.first},", "",
        f"We are pleased to offer you the position of {h.position} in our {h.department} team, "
        f"starting on {fmt_date(start, us)}.", "",
    ]
    if h.relocation:
        lines += ["Relocation Assistance:",
                  f"You are eligible for a relocation package of £{h.relocation}, covering moving "
                  "expenses and temporary housing for 30 days.", ""]
    elif RELOC_GAP in h.flaws:
        lines += ["Relocation Assistance:", "", ""]
    lines += ["You will receive 25 days of annual leave.", "",
              f"Please respond by {fmt_date(deadline, us)}.", "", "Kind regards,", "",
              "Mei Lin", "HR Coordinator", COMPANY, "---",
              f"Position: | {h.position}", f"Department: | {h.department}",
              f"Start Date: | {fmt_date(start, us)}", f"Reports To: | {manager}",
              f"Base Salary: | £{h.salary} per year"]
    if h.bonus != "0" or ZERO_ROWS in h.flaws:
        lines.append(f"Sign-on Bonus: | £{h.bonus}")
    if h.equity != "0" or ZERO_ROWS in h.flaws:
        lines.append(f"Equity Grant: | {h.equity} shares")
    return "\n".join(lines) + "\n"


def uuid7(ms: int, rng: random.Random) -> str:
    tail = rng.getrandbits(74)
    hexed = f"{ms:012x}"
    a = (tail >> 62) & 0xFFF
    b = 0x8000 | ((tail >> 48) & 0x3FFF)
    c = tail & ((1 << 48) - 1)
    return f"{hexed[:8]}-{hexed[8:]}-7{a:03x}-{b:04x}-{c:012x}"


class PiSession:
    """Pi's session JSONL: a header, then a parent-linked entry chain."""

    def __init__(self, rng: random.Random, session_id: str, start_ms: int, title: str, agents_md: str) -> None:
        self.rng = rng
        self.t = start_ms
        self.parent: str | None = None
        self.cache = 14_336
        self.entries: list[dict[str, Any]] = [
            {"type": "session", "version": 3, "id": session_id, "timestamp": iso(self.t), "cwd": CWD},
        ]
        self._node("model_change", provider="openai", modelId="gpt-5.4-mini")
        self._node("thinking_level_change", thinkingLevel="medium")
        self.t += rng.randint(90, 180)
        self._node("session_info", name=title[:50] + "...")
        context = (
            "<project_context>\nProject-specific instructions and guidelines:\n\n"
            f'<project_instructions path="{CWD}/AGENTS.md">\n{agents_md}\n</project_instructions>\n'
            "</project_context>"
        )
        self._message({
            "role": "system", "content": "",
            "sections": {**SYSTEM_SECTIONS, "project_context": context, "cwd": f"<cwd>\n{CWD}\n</cwd>"},
            "timestamp": self.t, "toolsAdded": TOOLS_ADDED,
        })

    def _hex(self, n: int) -> str:
        return f"{self.rng.getrandbits(4 * n):0{n}x}"

    def _node(self, kind: str, **fields: Any) -> None:
        entry = {"type": kind, "id": self._hex(8), "parentId": self.parent, "timestamp": iso(self.t), **fields}
        self.parent = entry["id"]
        self.entries.append(entry)

    def _message(self, message: dict[str, Any]) -> None:
        self._node("message", message=message)

    def user(self, text: str, delay_ms: int = 12) -> None:
        self.t += delay_ms
        self._message({"role": "user", "content": [{"type": "text", "text": text}], "timestamp": self.t})

    def assistant(self, *, thinking: str | None = None, calls: list[tuple[str, dict]] = (),
                  text: str | None = None) -> list[str]:
        rng = self.rng
        started = self.t + rng.randint(5, 30)
        duration = rng.randint(1800, 9000) + (len(text or "") * 6)
        self.t = started + duration
        content: list[dict[str, Any]] = []
        if thinking:
            content.append({"type": "thinking", "thinking": thinking, "thinkingSignature": "reasoning_content"})
        call_ids = []
        for name, arguments in calls:
            call_id = "call_" + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(24))
            call_ids.append(call_id)
            content.append({"type": "toolCall", "id": call_id, "name": name, "arguments": arguments})
        if text:
            content.append({"type": "text", "text": text})
        inp, out = rng.randint(240, 2600), rng.randint(60, 420) + len(text or "") // 3
        reasoning = rng.randint(0, out // 3)
        cost = {"input": inp * 2.5e-7, "output": out * 2e-6, "cacheRead": self.cache * 2.5e-8, "cacheWrite": 0}
        cost["total"] = sum(cost.values())
        cost["totalFromProvider"] = False
        usage = {"input": inp, "output": out, "cacheRead": self.cache, "cacheWrite": 0, "reasoning": reasoning,
                 "totalTokens": inp + out + self.cache, "cost": cost}
        self.cache += 512 * rng.randint(1, 4)
        self._message({
            "role": "assistant", "content": content, "api": "openai-completions", "provider": "openai",
            "model": "gpt-5.4-mini", "usage": usage, "stopReason": "toolUse" if calls else "stop",
            "timestamp": started, "responseId": "chatcmpl-" + self._hex(24),
            "rawStopReason": "tool_calls" if calls else "stop", "durationMs": duration, "thinkingLevel": "medium",
        })
        return call_ids

    def result(self, call_id: str, name: str, text: str, *, error: bool = False, ms: int | None = None) -> None:
        ms = ms if ms is not None else self.rng.randint(8, 420)
        self.t += ms
        self._message({"role": "toolResult", "toolCallId": call_id, "toolName": name,
                       "content": [{"type": "text", "text": text}], "isError": error, "durationMs": ms,
                       "timestamp": self.t})

    def body(self) -> bytes:
        return ("\n".join(json.dumps(e, ensure_ascii=False) for e in self.entries) + "\n").encode("utf-8")


def bash(command: str) -> tuple[str, dict]:
    return "bash", {"command": command, "timeout": None}


def offer_session(h: Hire, n: int, session_id: str, start_ms: int, agents_md: str,
                  folder: list[str], end: dt.date, rng: random.Random) -> PiSession:
    """One working session: read the data, fill the template, export, verify."""
    s = PiSession(rng, session_id, start_ms, h.ask, agents_md)
    s.user(h.ask)
    rules = "## Offer letters" in agents_md
    run_by_run = "run by run" in agents_md
    letter, _, _ = hire_dates(h, end)

    [c] = s.assistant(thinking="Let me look at the files.", calls=[bash("ls -la")])
    stamp = f"{letter:%b} {letter.day:2d} {h.clock}"
    listing = ["total 412", f"drwxr-xr-x  {len(folder) + 6:2d} mei  staff   {64 * (len(folder) + 6)} {stamp} .",
               "drwxr-xr-x   7 mei  staff    224 Sep 30 16:02 ..",
               f"-rw-r--r--   1 mei  staff  {len(agents_md.encode()):5d} {stamp} AGENTS.md"]
    listing += [f"-rw-r--r--   1 mei  staff  {38_400 + 37 * i:5d} Oct  2 11:17 {name}" for i, name in enumerate(folder)]
    listing += [f"-rw-r--r--   1 mei  staff    {812 + n:3d} {stamp} employee_data.json",
                "-rw-r--r--   1 mei  staff  38686 Sep 30 16:05 offer_letter_template.docx"]
    s.result(c, "bash", "\n".join(listing) + "\n")

    data = employee_data(h, n, end)
    [c] = s.assistant(calls=[("read", {"path": f"{CWD}/employee_data.json", "offset": None, "limit": None})])
    s.result(c, "read", json.dumps(data, indent=4, ensure_ascii=False) + "\n")
    [c] = s.assistant(thinking="Dump the template so I can see every placeholder, including tables and header.",
                      calls=[bash(DUMP_COMMAND.replace("__CWD__", CWD))])
    s.result(c, "bash", TEMPLATE_DUMP, ms=rng.randint(180, 420))

    manager = h.manager or ""
    if h.manager is None and INVENTED_MANAGER in h.flaws:
        manager = "Rachel Moore"
        [c] = s.assistant(
            thinking="MANAGER_NAME is missing from employee_data.json. Offer_Letter_Ben_Harris.docx is "
                     "another Sales hire; reuse the manager from that letter.",
            calls=[bash(f"cd {CWD} && python3 -c \"from docx import Document; d = Document("
                        "'Offer_Letter_Ben_Harris.docx'); [print([c.text for c in r.cells]) for t in "
                        "d.tables for r in t.rows]\"")])
        s.result(c, "bash", "['Position:', 'Account Executive']\n['Department:', 'Sales']\n"
                            "['Start Date:', 'October 26, 2026']\n['Reports To:', 'Rachel Moore']\n"
                            "['Base Salary:', '£56,000 per year']\n")
    elif h.manager is None:
        s.assistant(text=f"`employee_data.json` has no `MANAGER_NAME`. Who will {h.first} report to?")
        manager = h.answer or ""
        s.user(manager, delay_ms=rng.randint(40_000, 95_000))

    docx = out_name(h, "docx")
    date_expr = "f\"{d:%B} {d.day}, {d.year}\"" if US_DATES in h.flaws else "f\"{d.day} {d:%B} {d.year}\""
    script = (FILL_SCRIPT
              .replace("__FILL_BODY__", FILL_COLLAPSE if COLLAPSED_RUNS in h.flaws else FILL_RUN_AWARE)
              .replace("__CONDITIONAL__", COND_DELETE if rules else COND_STRIP)
              .replace("__MANAGER__", repr(manager))
              .replace("__DATE_EXPR__", date_expr)
              .replace("__OUT__", docx))
    thinking = ("Placeholders are split across runs in the XML; fill per paragraph and keep the "
                "conditional relocation block handling.")
    if rules:
        thinking = ("Follow AGENTS.md: day month year dates, drop blocks that do not apply, "
                    f"save as {docx[:-5]}.docx and .pdf.")
    [c] = s.assistant(thinking=thinking, calls=[("write", {"path": "/tmp/fill_offer.py", "content": script})])
    s.result(c, "write", f"Successfully wrote {len(script.encode())} bytes to /tmp/fill_offer.py", ms=4)
    [c] = s.assistant(calls=[bash(f"cd {CWD} && python3 /tmp/fill_offer.py")])
    s.result(c, "bash", f"wrote {docx}\nunresolved: []\n", ms=rng.randint(300, 700))

    pdf = out_name(h, "pdf")
    if PDF_FALLBACK in h.flaws:
        [c] = s.assistant(calls=[bash(f"cd {CWD} && python3 -c \"from docx2pdf import convert; convert('{docx}')\"")])
        s.result(c, "bash", "Traceback (most recent call last):\n  File \"<string>\", line 1, in <module>\n"
                            "ModuleNotFoundError: No module named 'docx2pdf'\n\n\nCommand exited with code 1",
                 error=True, ms=90)
        pdf_script = REPORTLAB_SCRIPT.replace("__DOCX__", docx).replace("__PDF__", pdf)
        [c] = s.assistant(thinking="docx2pdf is not installed. reportlab is; draw the letter text into a PDF.",
                          calls=[("write", {"path": "/tmp/make_pdf.py", "content": pdf_script})])
        s.result(c, "write", f"Successfully wrote {len(pdf_script.encode())} bytes to /tmp/make_pdf.py", ms=3)
        [c] = s.assistant(calls=[bash(f"cd {CWD} && python3 /tmp/make_pdf.py")])
        s.result(c, "bash", f"wrote {pdf}\n", ms=rng.randint(400, 900))
    elif NO_PDF not in h.flaws:
        [c] = s.assistant(calls=[bash(f"cd {CWD} && soffice --headless --convert-to pdf --outdir . {docx}")])
        s.result(c, "bash", f"convert {CWD}/{docx} -> {CWD}/{pdf} using filter : writer_pdf_Export\n",
                 ms=rng.randint(2600, 4800))

    [c] = s.assistant(calls=[bash(f"cd {CWD} && python3 -c \"from docx import Document; d = Document('{docx}'); "
                                  "[print(p.text) for p in d.paragraphs]; print('---'); [print(' | '.join(c.text "
                                  "for c in r.cells)) for t in d.tables for r in t.rows]\"")])
    s.result(c, "bash", letter_text(h, end, manager), ms=rng.randint(200, 450))
    if run_by_run:
        [c] = s.assistant(calls=[bash(f"cd {CWD} && python3 -c \"from docx import Document; d = Document('{docx}'); "
                                      "[print(repr(r.text), r.bold, r.underline) for p in d.paragraphs if "
                                      "'respond' in p.text for r in p.runs]\"")])
        _, _, deadline = hire_dates(h, end)
        s.result(c, "bash", f"'Please respond by ' None None\n'{fmt_date(deadline, False)}' True True\n'.' None None\n")

    files = f"`{docx}`" if NO_PDF in h.flaws else f"`{docx}` and `{pdf}`"
    bullets = ["- All placeholders filled (body, tables, header and footer)"]
    if h.relocation:
        bullets.append(f"- Relocation clause included (£{h.relocation}, 30 days)")
    elif RELOC_GAP in h.flaws:
        bullets.append("- Relocation package is \"No\", so the relocation text was left out")
    else:
        bullets.append("- Relocation section removed (not applicable)")
    if h.manager is None and INVENTED_MANAGER in h.flaws:
        bullets.append("- Manager taken from the previous Sales letter (Rachel Moore)")
    if run_by_run:
        bullets.append("- Formatting checked: salary and deadline keep the template styling")
    s.assistant(text=f"Created {files} from the template and `employee_data.json`.\n\n" + "\n".join(bullets))
    return s


# --------------------------------------------------------------------------- #
# Run stories: what the panel finds, proposes, and argues about
# --------------------------------------------------------------------------- #

DATE_RULE = ("- Write every date in the letter as day month year, e.g. `1 December 2026` (no weekday, "
             "no leading zero). This covers `DATE`, `START_DATE` and `RESPONSE_DEADLINE`.")
BLOCK_RULE = ("- When a conditional block such as `{{IF_RELOCATION}}…{{END_IF_RELOCATION}}` does not apply, "
              "delete the whole paragraph and the heading above it; never leave an empty paragraph or a "
              "heading with nothing under it.")
PDF_RULE = ("- Save every letter as both `.docx` and `.pdf`, named `Offer_<Lastname>_<Firstname>` "
            "(e.g. `Offer_Chen_Sarah.pdf`).")
ASK_RULE = ("- If `employee_data.json` has no value for a field the template needs (for example "
            "`MANAGER_NAME`), ask the user for it before writing the letter. Never copy it from older "
            "letters or invent it.")
PDF_RULE_V2 = ("- Save every letter as `.docx`, then convert that file with `soffice --headless "
               "--convert-to pdf` so the PDF matches it exactly; never re-type the letter into a PDF. Name "
               "both `Offer_<Lastname>_<Firstname>` (e.g. `Offer_Chen_Sarah.pdf`).")
FORMAT_RULE = ("- Fill placeholders run by run so the template formatting survives: the base salary stays "
               "bold and the response deadline stays bold and underlined. Re-open the saved file and check "
               "both before replying.")
BLOCK_RULE_V3 = ("- When a block or line does not apply, delete it with its label: a conditional block such "
                 "as `{{IF_RELOCATION}}…{{END_IF_RELOCATION}}` that is off, or a table row whose amount is "
                 "`0` (e.g. `SIGNING_BONUS`, `EQUITY_SHARES`). Never leave `£0`, `0 shares`, an empty "
                 "paragraph or a heading with nothing under it.")

US_DATE_PROBE = r"(January|February|March|April|May|June|July|August|September|October|November|December) [0-9]{1,2}, 20[0-9]{2}"


@dataclass(frozen=True)
class Edit:
    old: str
    new: str
    rationale: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Proposal:
    edits: tuple[Edit, ...]
    note: str


@dataclass(frozen=True)
class Finding:
    label: str | None
    texts: tuple[str, ...]   # phrasings; the first is the judged statement
    traces: tuple[str, ...]
    confidence: str
    probe: str


@dataclass(frozen=True)
class Ask:
    """One ask_panel query: `seat` indexes the panel (wrapping)."""
    seat: int
    question: str
    answer: str
    timeout: bool = False


@dataclass(frozen=True)
class Story:
    key: str
    batch: tuple[str, ...]
    summary: str
    verdicts: tuple[str, ...]
    findings: tuple[Finding, ...]
    hypotheses: tuple[tuple[str, tuple[str, ...], str, tuple[str, ...]], ...]
    directions: tuple[str, ...]
    unresolved: tuple[str, ...]
    waste: tuple[str, ...]
    weak_claim: str | None
    review_asks: tuple[Ask, ...]
    proposals: tuple[Proposal, ...]   # cycled over the propose panel
    final: Proposal
    commit_title: str
    commit_body: str
    propose_asks: tuple[Ask, ...]
    failed_propose_attempts: int = 0  # propose attempts whose panel dies on a provider error
    transport_retry: bool = False     # one reviewer hits a transient stream error


R1_FINAL = Proposal((
    Edit("# AGENTS.md", "# AGENTS.md\n\n## Offer letters\n\n" + DATE_RULE,
         "The user asked for `1 December 2026` style dates 'as all our letters do'; every letter in the batch "
         "used month-first dates because no convention was written down.", ("t01", "t02", "t03", "t04")),
    Edit("", BLOCK_RULE,
         "With relocation set to No the agent stripped only the markers and left the heading over an empty "
         "paragraph, which the user called a big empty gap.", ("t02",)),
    Edit("", PDF_RULE,
         "No session produced a PDF and files were named Offer_Letter_First_Last; the user wants a PDF too, "
         "named Offer_Lastname_Firstname.", ("t03",)),
    Edit("", ASK_RULE,
         "With MANAGER_NAME missing the agent copied a manager from an older letter; the user wants to be "
         "asked instead.", ("t04",)),
), "Four explicit preferences from the HR user had no rule in the empty AGENTS.md.")

R2_FINAL = Proposal((
    Edit(PDF_RULE, PDF_RULE_V2,
         "The PDF lost the bold salary line because it was re-typed with reportlab after docx2pdf failed; "
         "converting the filled .docx keeps both files identical.", ("t07",)),
    Edit(DATE_RULE, DATE_RULE + "\n" + FORMAT_RULE,
         "The fill script collapsed runs and dropped the deadline's bold and underline; the user asked to keep "
         "the template formatting exactly.", ("t07", "t08")),
), "Both formatting losses trace to how the letter is written, not to the existing rules.")

LIVE_FINAL = Proposal((
    Edit(BLOCK_RULE, BLOCK_RULE_V3,
         "Rows with a zero amount are the same 'does not apply' case as an off relocation block; both "
         "feedbacks ask for the line to be dropped.", ("t11", "t12")),
), "Zero-value bonus and equity rows are the same gap as the relocation block.")

STORIES: dict[str, Story] = {
    "r1": Story(
        key="r1",
        batch=("t01", "t02", "t03", "t04"),
        summary="Four offer-letter sessions carry explicit feedback that maps to four separate, repeatable "
                "preference gaps: date format, empty conditional blocks, missing PDF output with a naming "
                "convention, and invented data when a field is missing. AGENTS.md is empty, so none of these "
                "preferences were available to the agent.",
        verdicts=(
            "Four actionable preference gaps, each backed by explicit feedback; AGENTS.md has no rules yet.",
            "Strong batch: every trace has feedback and each names a concrete, reusable preference.",
            "Actionable. Date format repeats in all four traces; the other three gaps have one trace each.",
        ),
        findings=(
            Finding("INSTRUCTION_CONFLICT", (
                "All four letters write dates month-first (`October 19, 2026`); @t01's feedback asks for "
                "`1 December 2026` 'as all our letters do'. @t02, @t03 and @t04 repeat the format with no "
                "feedback on dates.",
                "`DATE`, `START_DATE` and `RESPONSE_DEADLINE` are rendered US-style in @t01, @t02, @t03 and "
                "@t04; only @t01 carries date feedback.",
            ), ("t01", "t02", "t03", "t04"), "high", US_DATE_PROBE),
            Finding("STATE_MISMATCH", (
                "With `RELOCATION_PACKAGE: \"No\"`, @t02 stripped only the `{{IF_RELOCATION}}` markers; the "
                "letter keeps the 'Relocation Assistance:' heading over an empty paragraph. Feedback: "
                "'There's a big empty gap where the relocation part was'.",
                "@t02's verify step prints 'Relocation Assistance:' followed by two blank lines; the user calls "
                "it a big empty gap.",
            ), ("t02",), "high", "Relocation Assistance|IF_RELOCATION"),
            Finding("INSTRUCTION_CONFLICT", (
                "No session writes a PDF and every output is named `Offer_Letter_<First>_<Last>.docx`; @t03's "
                "feedback asks for a PDF too, named Offer_Lastname_Firstname.",
                "Only .docx files are produced (@t01-@t04); @t03 feedback requests a PDF and the "
                "Offer_Lastname_Firstname name.",
            ), ("t01", "t02", "t03", "t04"), "high", r"\.pdf|Offer_Letter_[A-Za-z]+"),
            Finding("UNSUPPORTED_CLAIM", (
                "`employee_data.json` in @t04 has no `MANAGER_NAME`; the agent copied 'Rachel Moore' from "
                "`Offer_Letter_Ben_Harris.docx` into 'Reports To'. Feedback: 'Don't make up the manager, ask me'.",
                "DATA_UNAVAILABLE then a guess: @t04 fills 'Reports To' from an older Sales letter instead of "
                "asking.",
            ), ("t04",), "high", "MANAGER_NAME|Reports To|Rachel Moore"),
        ),
        hypotheses=(
            ("With no written date convention the agent falls back to US style; one explicit rule with the "
             "example `1 December 2026` should fix all three date fields.", ("t01", "t02", "t03", "t04"),
             "high", ()),
            ("When a field is missing the agent fills it from older letters in the folder; an 'ask the user' "
             "rule should stop it.", ("t04",), "medium", ("Only one session in the batch had a missing field.",)),
            ("Collapsing runs in the fill script can drop bold and underline from the template.", ("t02",), "low",
             ("No feedback in this batch mentions formatting.",
              "@t01 used a run-aware script and kept the bold deadline.")),
        ),
        directions=(
            "Add an Offer letters section with the date format `1 December 2026`.",
            "Delete conditional blocks that do not apply together with their heading.",
            "Save .docx and .pdf, named Offer_<Lastname>_<Firstname>.",
            "Ask the user for missing fields instead of inferring them.",
        ),
        unresolved=(
            "Whether formatting loss from run collapsing matters to the user: visible in @t02's file, never "
            "mentioned in feedback.",
            "Whether the US dates in @t02-@t04 were acceptable: only @t01 carries date feedback.",
        ),
        waste=(
            "@t02 printed the whole template XML (about 6 KB) to find split placeholders; a regex over "
            "`word/document.xml` was enough.",
            "@t04 listed the folder, then opened an older letter to guess a field instead of asking.",
            "Every trace re-dumps the template although it never changes between sessions.",
        ),
        weak_claim="The paragraph-level fill script in @t02 writes each paragraph's text into its first run, "
                   "which would drop the bold and underline on the response deadline. Confidence: low.",
        review_asks=(
            Ask(1, "You flagged run collapsing in @t02's fill script. Is the formatting loss visible in the saved "
                   "letter, and does any feedback in the batch mention it?",
                "The code collapses runs, so the deadline paragraph in @t02's output has a single unformatted run. "
                "No feedback in this batch mentions formatting, and @t01 used a run-aware script that kept bold. "
                "Keep it as a low-confidence hypothesis, not a finding."),
            Ask(2, "Falsify: is the invented manager in @t04 an instruction gap or a data problem? Check whether "
                   "the agent knew the field was missing before it filled the letter.",
                "It knew. The thinking block before the fill says `MANAGER_NAME` is missing and that it will reuse "
                "the manager from `Offer_Letter_Ben_Harris.docx`. The data was unavailable; the guess was the "
                "agent's choice, so an instruction to ask for missing fields addresses it."),
        ),
        proposals=(
            R1_FINAL,
            Proposal(R1_FINAL.edits + (Edit("", "- Keep the template's bold and underline when filling "
                                                "placeholders.", "Run collapsing in the fill script drops "
                                                "template formatting.", ("t02",)),),
                     "Four explicit preferences plus run-preserving fills."),
            Proposal((Edit("# AGENTS.md", "# AGENTS.md\n\n## Offer letters\n\n" + "\n".join(
                [DATE_RULE, BLOCK_RULE, PDF_RULE, ASK_RULE]),
                "One section with the four rules the feedback asks for.", ("t01", "t02", "t03", "t04")),),
                "One section with the four rules the feedback asks for."),
        ),
        final=R1_FINAL,
        commit_title="feat: add offer-letter rules for dates, gaps, PDF and missing data",
        commit_body="Adds an Offer letters section to AGENTS.md. Dates are written as 1 December 2026, "
                    "conditional blocks that do not apply are removed with their heading, every letter is "
                    "saved as .docx and .pdf named Offer_<Lastname>_<Firstname>, and missing fields such as "
                    "the manager are asked for instead of guessed.",
        propose_asks=(
            Ask(1, "Your fifth edit adds a formatting rule. Which trace has feedback that supports it?",
                "None does. @t02 shows collapsed runs in the file, but the user never mentioned formatting. Drop "
                "it until feedback confirms it."),
            Ask(2, "You merged four signals into one edit. Would splitting them into one edit per rule change any "
                   "wording?",
                "No. The bullets are identical; splitting only gives each rule its own evidence. Use the split "
                "version."),
        ),
    ),
    "r2": Story(
        key="r2",
        batch=("t05", "t06", "t07", "t08"),
        summary="The offer-letter rules held in all four sessions: day-month-year dates, both files named "
                "Offer_<Lastname>_<Firstname>, no empty relocation block. The remaining defect is formatting "
                "loss, once in the PDF path (reportlab fallback after docx2pdf failed) and once in the DOCX fill "
                "(runs collapsed). One name-order request is explicitly scoped to a single candidate.",
        verdicts=(
            "Rules from the last run hold; formatting loss is the one new, repeated signal.",
            "Two formatting complaints with two different mechanisms; one scoped one-off request.",
            "Actionable for formatting only. The name-order request is not a standing preference.",
        ),
        findings=(
            Finding(None, (
                "All four letters follow the current rules: dates as `26 October 2026`, `.docx` and `.pdf` named "
                "`Offer_<Lastname>_<Firstname>`, and @t07 removed the relocation heading with its block. @t05's "
                "feedback: 'Perfect, that's exactly it'.",
                "The v1 rules are followed in @t05, @t06, @t07 and @t08; @t05 is explicitly approved.",
            ), ("t05", "t06", "t07", "t08"), "high", r"[0-9]{1,2} (October|November|December) 2026|Offer_[A-Z]"),
            Finding("TOOL_ERROR", (
                "In @t07 `docx2pdf` was not installed (exit 1); the agent rebuilt the PDF with reportlab from plain "
                "paragraph text, so the PDF lost the bold salary line. Feedback: 'Keep the template formatting; "
                "the salary line lost its bold'.",
                "@t07: docx2pdf import error, then a reportlab re-typing of the letter; feedback reports the lost "
                "bold salary.",
            ), ("t07",), "high", "docx2pdf|reportlab|drawString"),
            Finding("STATE_MISMATCH", (
                "@t08's fill script writes each paragraph's text into its first run, so the saved `.docx` has the "
                "response deadline without bold or underline. Feedback: 'The deadline line lost its bold and "
                "underline. Please keep the template formatting exactly.'",
                "@t08 collapses runs (`p.runs[0].text = text`); the deadline formatting is gone and the user says so.",
            ), ("t08",), "high", r"runs\[0\]|runs\[1:\]"),
            Finding(None, (
                "@t06's only feedback is scoped to one candidate: 'For this candidate write Zhang Wei, family name "
                "first'. `employee_data.json` has no field for name order.",
                "@t06 asks for family-name-first 'for this candidate'; nothing in the data marks name order.",
            ), ("t06",), "medium", "Zhang|CANDIDATE_FULL_NAME"),
        ),
        hypotheses=(
            ("Converting the filled `.docx` with LibreOffice instead of re-typing it would keep the PDF identical "
             "to the DOCX.", ("t07",), "high", ()),
            ("Replacing placeholders run by run keeps the template's bold and underline; the low-confidence "
             "formatting hypothesis from the previous run is now confirmed by feedback.", ("t08",), "high", ()),
            ("Family-name-first should apply to every Chinese name.", ("t06",), "low",
             ("The feedback says 'For this candidate'.", "employee_data.json has no name-order field.")),
        ),
        directions=(
            "Convert the PDF from the filled .docx (`soffice --headless --convert-to pdf`); never re-type it.",
            "Fill placeholders per run and check that the salary and deadline keep their formatting.",
            "Keep the existing date, naming, missing-field and conditional-block rules unchanged.",
        ),
        unresolved=("Whether family-name-first should ever be a rule: one scoped request so far.",),
        waste=(
            "@t07 tried docx2pdf, then wrote a reportlab script; `soffice` was available and used in @t05.",
            "@t06 and @t08 re-dump the template before every fill.",
        ),
        weak_claim="Chinese names should be written family name first in every letter (@t06). Confidence: low.",
        review_asks=(
            Ask(1, "You propose family-name-first for all Chinese names. Defend it from @t06 alone, or concede.",
                "Concede. The feedback says 'For this candidate', and nothing in the data marks name order. It is "
                "a one-off correction, not a standing rule."),
            Ask(0, "Falsify the claim that @t07's and @t08's formatting losses share one cause.",
                "They do not share one cause. @t07 lost bold in the PDF because reportlab re-typed the text after "
                "docx2pdf failed; its .docx kept the bold. @t08 lost formatting in the .docx itself because the "
                "fill script collapsed runs. Two mechanisms, one user preference."),
        ),
        proposals=(
            R2_FINAL,
            Proposal(R2_FINAL.edits + (Edit(ASK_RULE, ASK_RULE + "\n- Write Chinese candidates' names family name "
                                            "first, e.g. `Zhang Wei`.",
                                            "The user corrected the name order for a Chinese candidate.", ("t06",)),),
                     "Formatting fixes plus the name-order preference."),
            Proposal((R2_FINAL.edits[1],), "Formatting fix only; the PDF failure is a tool problem."),
        ),
        final=R2_FINAL,
        commit_title="fix: keep template formatting in offer-letter DOCX and PDF",
        commit_body="Offer letters now fill placeholders run by run so bold and underline from the template "
                    "survive, and the PDF is converted from the filled .docx with LibreOffice instead of being "
                    "re-typed, so both files match. The one-off family-name-first request stays out of AGENTS.md "
                    "because it applied to a single candidate.",
        propose_asks=(
            Ask(1, "Your third edit makes family-name-first a rule for all Chinese names. The feedback in @t06 says "
                   "'For this candidate'. Defend or drop it.", "", timeout=True),
            Ask(2, "You left the PDF path alone as a tool problem. @t07's PDF lost bold only because it was "
                   "re-typed. Is a conversion rule an instruction fix?",
                "Yes. docx2pdf was missing, but re-typing the text was the agent's choice. Converting the filled "
                ".docx with soffice is an instruction it can follow; add it."),
        ),
        failed_propose_attempts=1,
        transport_retry=True,
    ),
    "r3": Story(
        key="r3",
        batch=("t09", "t10"),
        summary="Both sessions follow every current offer-letter rule. @t10 asked for the missing manager instead "
                "of guessing, and the only feedback in the batch is positive. No new failure mode appears.",
        verdicts=(
            "No actionable signal: both letters follow the current rules.",
            "Nothing to change. One approved session, one without feedback.",
        ),
        findings=(
            Finding(None, (
                "@t09 and @t10 follow every current rule: day-month-year dates, run-by-run fill, PDF converted from "
                "the DOCX, both named `Offer_<Lastname>_<Firstname>`. @t10 asked for the missing manager instead of "
                "guessing. @t09's feedback: 'Perfect, that's exactly it'.",
                "Current rules followed in @t09 and @t10, including the ask-for-missing-fields rule in @t10.",
            ), ("t09", "t10"), "high", "MANAGER_NAME|soffice|Offer_[A-Z]"),
            Finding("OUTCOME_UNKNOWN", (
                "@t10 has no feedback; the letter is consistent with the rules, but its outcome is unknown.",
                "@t10: OUTCOME_UNKNOWN, no feedback attached.",
            ), ("t10",), "medium", "Reports To"),
        ),
        hypotheses=(
            ("The current rules cover the observed preferences; no new failure mode appears in this batch.",
             ("t09", "t10"), "medium", ("Two sessions are a small sample.",)),
        ),
        directions=(),
        unresolved=("@t10's outcome: no feedback.",),
        waste=("Both sessions re-dump the template before filling; harmless.",),
        weak_claim=None,
        review_asks=(),
        proposals=(Proposal((), "No defensible signal: both sessions follow the current rules."),),
        final=Proposal((), "No new signal: both letters followed the current rules."),
        commit_title="chore: keep AGENTS.md unchanged for this batch",
        commit_body="Both sessions followed the current offer-letter rules and the only feedback was positive, "
                    "so there is nothing to change.",
        propose_asks=(),
    ),
    "live": Story(
        key="live",
        batch=("t11", "t12", "t13"),
        summary="Dates, file names, PDF conversion and formatting follow the current rules in all three sessions. "
                "Two letters print rows whose amount is zero ('Sign-on Bonus: £0', 'Equity Grant: 0 shares'), and "
                "both carry feedback asking for the row to be dropped. The existing conditional-block rule covers "
                "only `{{IF_…}}` blocks.",
        verdicts=(
            "One repeated signal: zero-value rows should disappear like an off conditional block.",
            "Actionable: two traces, two feedbacks, same mechanism.",
            "The current rules hold; widen the conditional-block rule to zero amounts.",
        ),
        findings=(
            Finding("STATE_MISMATCH", (
                "@t11's letter prints 'Sign-on Bonus: £0' because `SIGNING_BONUS` is \"0\". Feedback: 'If there's "
                "no bonus, just leave the line out.'",
                "@t11 fills the bonus row with £0; the user wants the row gone.",
            ), ("t11",), "high", "£0|SIGNING_BONUS"),
            Finding("STATE_MISMATCH", (
                "@t12 prints 'Equity Grant: 0 shares'. Feedback: 'Same thing with equity: '0 shares' looks odd, "
                "drop the line when there's none.'",
                "@t12 keeps a 0-shares equity row; feedback asks to drop it.",
            ), ("t12",), "high", "0 shares|EQUITY_SHARES"),
            Finding(None, (
                "Dates, names, PDF conversion and run-by-run formatting follow the current rules in @t11, @t12 and "
                "@t13. @t13's feedback: 'Perfect, that's exactly it'.",
                "Current rules followed in @t11-@t13; @t13 approved.",
            ), ("t11", "t12", "t13"), "high", "soffice|Offer_[A-Z]"),
        ),
        hypotheses=(
            ("Widening the conditional-block rule to rows with a zero amount removes both lines without adding a "
             "new rule.", ("t11", "t12"), "high", ()),
            ("The agent should ask before dropping any line.", ("t11",), "low",
             ("Both feedbacks ask for the line to be dropped outright.",)),
        ),
        directions=("Generalize the conditional-block rule to table rows whose amount is 0 (bonus, equity).",),
        unresolved=(),
        waste=("@t12 printed the full letter twice while checking formatting.",
               "@t11 re-dumped the template although it was unchanged."),
        weak_claim="The agent should ask before leaving any template line out (@t11). Confidence: low.",
        review_asks=(
            Ask(1, "You suggest asking before dropping lines. Does any feedback ask to be consulted?",
                "No. Both @t11 and @t12 ask for the line to be dropped outright. Asking would add a turn the user "
                "did not want; I withdraw it."),
            Ask(0, "Falsify: is the zero-value problem the same mechanism as the old empty relocation block?",
                "Same mechanism, different trigger. The relocation rule covers `{{IF_…}}` blocks only; "
                "`SIGNING_BONUS` and `EQUITY_SHARES` are plain table rows, so the agent filled them with 0. "
                "Widening the existing rule covers both."),
        ),
        proposals=(
            LIVE_FINAL,
            Proposal((Edit("", "- Leave out the Sign-on Bonus and Equity Grant rows when their value is 0.",
                           "Both zero-value rows drew feedback.", ("t11", "t12")),),
                     "A separate rule for zero-value rows."),
            Proposal((Edit("", "- Before leaving any template line out, ask the user.",
                           "Dropping lines silently surprised the user.", ("t11",)),),
                     "Ask before removing template content."),
        ),
        final=LIVE_FINAL,
        commit_title="fix: drop zero-value bonus and equity lines from offer letters",
        commit_body="The rule for blocks that do not apply now also covers amounts of 0, so letters leave out the "
                    "sign-on bonus or equity row instead of printing £0 or 0 shares. Dates, file names and "
                    "formatting rules are unchanged.",
        propose_asks=(
            Ask(1, "You add a separate zero-value rule next to the conditional-block rule. Would widening the "
                   "existing rule say the same thing with one bullet?",
                "Yes. One rule for 'does not apply' is clearer than two that overlap. Widen the existing bullet."),
            Ask(2, "Your edit asks before removing lines. Which feedback supports asking?",
                "None. Both say to drop the line. I withdraw it."),
        ),
    ),
}

# When each run starts: (story, day before --end, UTC time, trigger).
RUNS = [("r1", 11, "17:35", "manual"), ("r2", 5, "09:41", "auto"), ("r3", 3, "16:20", "manual")]


# --------------------------------------------------------------------------- #
# Driver emulation: the event stream majics.ts posts for one stage
# --------------------------------------------------------------------------- #


def summarize(value: str) -> str:
    """majics.ts summarizeArgs: one line, at most 120 chars."""
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
    """One pi session in the panel: its events carry the agentSink fields."""

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
    boot_ms: int                                    # Harbor build + container start
    events: list[tuple[int, dict[str, Any]]]
    artifacts: dict[str, str]
    teardown_ms: int


@dataclass
class Cast:
    """The story with its trace keys bound to the run's frozen batch."""
    story: Story
    ids: dict[str, str]
    rng: random.Random
    roster: dict[str, Any]

    def text(self, value: str) -> str:
        return re.sub(r"@(t\d\d)", lambda m: self.ids[m.group(1)], value)

    def traces(self, keys: tuple[str, ...]) -> list[str]:
        return [self.ids[k] for k in keys]


def roster_payload(roster: dict[str, Any]) -> list[dict[str, Any]]:
    """majics.ts rosterPayload: the seats from the materialized majics.json."""
    label = lambda spec: f"{spec['id']}@{spec['reasoning']}"  # noqa: E731
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


def reviewer_commands(cast: Cast, index: int) -> list[str]:
    """One reviewer's research path: workspace files, inventory, deep reads, cross-checks."""
    story, rng = cast.story, cast.rng
    batch = cast.traces(story.batch)
    order = batch[index % len(batch):] + batch[:index % len(batch)]
    grep_style = index % 3 == 1
    commands = [
        "sed -n '1,200p' /app/workspace/agents.md" if grep_style else "cat agents.md",
        py("import json\nev = json.load(open('evidence.json'))\nprint(ev['batch'])\nfor t in ev['traces']:\n"
           "    print(t['id'], t['feedbackPresent'], t['metrics'], [s['code'] for s in t['signals']])"),
        "python3 -c \"import json; log = json.load(open('log_edits.json')); print(len(log['entries'])); "
        "[print(e['id'], e['outcome'], e['title'], e['signal'][:80]) for e in log['entries']]\"",
        py("import json, glob, collections\nfor p in sorted(glob.glob('traces/*.jsonl')):\n"
           "    rows = [json.loads(l) for l in open(p)]\n    head = rows[0]\n    tools = collections.Counter(\n"
           "        b['name'] for r in rows for b in (r.get('message') or {}).get('content') or []\n"
           "        if isinstance(b, dict) and b.get('type') == 'toolCall')\n"
           "    errors = sum(1 for r in rows if (r.get('message') or {}).get('isError'))\n"
           "    print(p[7:-6], len(rows), dict(tools), errors, (head.get('feedback') or '')[:90])"),
    ]
    findings = [f for j, f in enumerate(story.findings)
                if not (index == 2 and len(story.findings) > 2 and j == len(story.findings) - 1)]
    for tid in order:
        key = next(k for k, v in cast.ids.items() if v == tid)
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
    batch = ", ".join(cast.traces(story.batch))
    findings = [f for j, f in enumerate(story.findings)
                if not (index == 2 and len(story.findings) > 2 and j == len(story.findings) - 1)]
    lines = ["### Verdict", story.verdicts[index % len(story.verdicts)], "", "### Coverage",
             f"Mode: full. Deep-read: {batch}. Counterexamples sampled: none (every trace assigned). "
             "Inventory-only: none.", "", "### Findings"]
    for n, f in enumerate(findings, 1):
        label = f"{f.label}: " if f.label else ""
        lines.append(f"{n}. {label}{cast.text(f.texts[index % len(f.texts)])} "
                     f"Traces: {', '.join(cast.traces(f.traces))}. Confidence: {f.confidence}.")
    lines += ["", "### Hypotheses"]
    for statement, _, confidence, contra in story.hypotheses:
        if confidence == "low" and story.weak_claim and index != 1 % max(1, len(cast.roster["reviewModels"])):
            continue
        needed = cast.text("; ".join(contra)) if contra else "a later session where the rule is present and the behavior repeats"
        lines.append(f"- {cast.text(statement)} ({confidence}; would disprove: {needed})")
    if story.weak_claim and index == 1 % max(1, len(cast.roster["reviewModels"])):
        lines.append(f"- {cast.text(story.weak_claim)}")
    lines += ["", "### Failure taxonomy"]
    labels: dict[str, list[str]] = {}
    for f in findings:
        if f.label:
            labels.setdefault(f.label, []).extend(cast.traces(f.traces))
    lines += [f"- {label}: {', '.join(dict.fromkeys(ids_))}" for label, ids_ in labels.items()] or ["- none observed"]
    lines += ["", "### Tool waste and better paths", f"- {cast.text(story.waste[index % len(story.waste)])}",
              "", "### Candidate directions"]
    lines += [f"- {cast.text(d)}" for d in story.directions] or ["- None: no instruction change is supported."]
    lines += ["", "### Unresolved"]
    lines += [f"- {cast.text(u)}" for u in story.unresolved] or ["- none"]
    return "\n".join(lines)


def ask_panel(judge: Seat, panel: list[Seat], asks: tuple[Ask, ...], cast: Cast, stage: str,
              judge_label: str, tl: Timeline) -> None:
    """The judge's single ask_panel call: parallel reruns, then analytics, then the tool result."""
    rng = cast.rng
    judge.t += rng.randint(25_000, 60_000)
    called = judge.t
    judge.tl.add(called, {"kind": "tool", "name": "ask_panel", "agent": judge.key, "model": judge.model,
                          "role": judge.role, "stage": judge.stage})
    finished = called
    timed_out: list[str] = []
    seen: set[str] = set()
    for ask in asks:
        worker = panel[ask.seat % len(panel)]
        if worker.key in seen:
            continue
        seen.add(worker.key)
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
        "role": "judge", "workersAsked": len(seen), "workersTimedOut": len(timed_out), "timedOutRoles": timed_out,
        "queriesAsked": len(seen), "queriesTimedOut": len(timed_out), "timeoutMs": 60_000,
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
                seat.say(f"Inventory done: {len(story.batch)} traces, all in full coverage. Deep-reading each.")
            if story.transport_retry and i == 1 % len(panel) and n == len(commands) // 2:
                seat.retry()
        seat.say(reviewer_report(cast, i), think=(35_000, 80_000))
        seat.end()
    judge_spec = roster["reviewJudge"]
    judge_label = f"{judge_spec['id']}@{judge_spec['reasoning']}"
    judge = Seat(tl, rng, "review-judge", judge_label, "judge", "review")
    judge.start(max(s.t for s in panel) + rng.randint(900, 1800))
    batch = cast.traces(story.batch)
    judge.tool("bash", py(f"import json\nfor tid in {batch!r}:\n    h = json.loads(open(f'traces/{{tid}}.jsonl')"
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
                      "confidence": f.confidence} for f in story.findings],
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
    final["commit_title"] = story.commit_title
    final["commit_body"] = story.commit_body
    judge.tool("submit_proposal", final["note"], think=(45_000, 80_000), ms=(3, 15))
    count = len(story.final.edits)
    judge.say(f"Submitted the fused proposal: {count} edit{'s' if count != 1 else ''} · commit: {story.commit_title}",
              think=(1500, 3500))
    judge.end()
    t = judge.t + rng.randint(30, 120)
    tl.add(t, {"kind": "stage", "stage": "propose", "status": "end", "durationMs": t})
    tl.add(t + rng.randint(5, 20), {"kind": "commit", "title": story.commit_title, "body": story.commit_body})
    artifact = {"edits": final["edits"], "note": final["note"], "commit_title": story.commit_title,
                "commit_body": story.commit_body}
    return StageScript(rng.randint(25_000, 50_000), tl.events(),
                       {"proposal.json": json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                        "driver-error.txt": ""}, rng.randint(5000, 11_000))


class Director:
    """Holds the story of the run in flight and plays its stage scripts."""

    def __init__(self, clock: Clock, seed: int) -> None:
        self.clock = clock
        self.seed = seed
        self.hone: Hone | None = None
        self.story: Story | None = None

    def cast(self, run_id: str, task_dir: Path, stage: str, attempt: int) -> Cast:
        assert self.hone is not None and self.story is not None
        story = self.story
        run = self.hone.db.run(run_id)
        assert run is not None
        if len(run["trace_ids"]) != len(story.batch):
            raise SystemExit(f"run {run_id} froze {len(run['trace_ids'])} traces; story {story.key} "
                             f"expects {len(story.batch)}")
        environment = task_dir / "environment"
        return Cast(
            story=story,
            ids=dict(zip(story.batch, run["trace_ids"], strict=True)),
            rng=random.Random(f"{self.seed}:{story.key}:{stage}:{attempt}"),
            roster=json.loads((environment / "config" / "majics.json").read_text(encoding="utf-8")),
        )

    async def play(self, run_id: str, script: StageScript) -> None:
        assert self.hone is not None
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
    """Stands in for HarborMajicsExecutor: same constructor and `run` contract,
    with the in-sandbox driver replaced by a scripted event stream."""

    def __init__(self, director: Director, settings: HoneConfig, dirs: Any, run_id: str, emit: Any) -> None:
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


def install_director(director: Director) -> None:
    pipeline_mod.HarborMajicsExecutor = functools.partial(ScriptedExecutor, director)


async def drive(hone: Hone, director: Director, story: Story, trigger: str) -> dict[str, Any]:
    director.story = story
    started = hone.start_run(trigger=trigger)
    task = hone._run_task
    assert task is not None
    await task
    run = hone.db.run(started["id"])
    assert run is not None
    return run


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def prepare_dir(data_dir: Path, force: bool) -> None:
    if data_dir.exists() and any(data_dir.iterdir()):
        if not force:
            raise SystemExit(f"{data_dir} is not empty; pass --force to wipe and reseed it")
        if not (data_dir / "app.sqlite").exists():
            raise SystemExit(f"refusing to wipe {data_dir}: it has files but no app.sqlite, so it is not a Hone data dir")
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)


async def seed(args: argparse.Namespace) -> None:
    data_dir = args.data_dir.resolve()
    end = dt.date.fromisoformat(args.end)
    prepare_dir(data_dir, args.force)
    raw = config_raw(args.reviewers, args.proposers)
    (data_dir / "hone.yaml").write_text(
        "# Written by scripts/dev/seed_runs.py. Serve this dir with\n"
        f"#   HONE_CONFIG={data_dir}/hone.yaml HONE_PORT=8090 uvicorn hone.api:app --port 8090\n"
        + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    settings = settings_for(data_dir, raw)

    clock = Clock(start_ms=ms_at(end, 15, "08:30"))
    clock.install()
    rng = random.Random(f"{args.seed}:runs")
    run_ids = iter([r for r in dict.fromkeys(f"r_{rng.getrandbits(16):04x}" for _ in range(16)) if r != LIVE_RUN_ID])
    ids.new_run_id = lambda: next(run_ids)
    director = Director(clock, args.seed)
    install_director(director)

    hone = Hone(settings)
    director.hone = hone
    hone.set_config(batch_size=4, auto_optimize=False)

    agenda: list[tuple[int, str, Any]] = [(ms_at(end, h.day, h.clock), "trace", (n, h)) for n, h in enumerate(HIRES)]
    agenda += [(ms_at(end, day, hhmm), "run", (key, trigger)) for key, day, hhmm, trigger in RUNS]
    folder = ["Offer_Letter_Ben_Harris.docx"]
    for at, kind, item in sorted(agenda, key=lambda x: x[0]):
        clock.set(max(at, clock.now_ms()))
        if kind == "trace":
            n, h = item
            trng = random.Random(f"{args.seed}:{h.key}")
            session_id = uuid7(clock.now_ms(), trng)
            session = offer_session(h, n, session_id, clock.now_ms(), hone.dirs.read_current(),
                                    folder[-4:], end, trng)
            clock.set(session.t + trng.randint(1500, 4000))
            trace = hone.upsert_trace(session_id, session.body(), hone.current_id)
            if h.feedback:
                clock.set(clock.now_ms() + trng.randint(60_000, 240_000))
                hone.add_feedback(trace["id"], h.feedback)
            folder.append(out_name(h, "docx"))
        else:
            key, trigger = item
            run = await drive(hone, director, STORIES[key], trigger)
            print(f"{run['id']}  {key:<4} {run['status']:<10} attempts={run['attempts']} "
                  f"traces={len(run['trace_ids'])} -> {run['result_version_id'] or '-'}")
    hone.close()
    print(f"seeded {data_dir}: {len(HIRES)} traces, {len(RUNS)} runs, "
          f"roster review[{args.reviewers}] propose[{args.proposers}]")
    print(f"live replay: uv run python scripts/dev/seed_runs.py live --data-dir {data_dir} "
          "--service http://127.0.0.1:8090")


def rewind(hone: Hone, run_id: str) -> None:
    """Undo a finished replay so the same run can play again."""
    run = hone.db.run(run_id)
    assert run is not None
    result = run["result_version_id"]
    if result:
        node = hone.db.node(result)
        branch = node["branch"] if node else None
        if not branch or hone.git.branch_tip(branch) != result:
            raise SystemExit(f"cannot rewind {run_id}: its commit {result} is no longer a branch tip")
        hone.git.checkout(branch)
        hone.git._run("reset", "--hard", "--quiet", run["base_version_id"])
        if hone.current_id == result:
            hone.db.set_config("current_id", run["base_version_id"])
    for sid in run["trace_ids"]:
        hone.db.execute("UPDATE traces SET status = 'new', analyzed_by = NULL WHERE session_id = ?", (sid,))
    log = logedits.read_log(hone.dirs.log_edits)
    log["entries"] = [e for e in log["entries"] if e.get("runId") != run_id]
    logedits.write_log(hone.dirs.log_edits, log)
    hone.db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    shutil.rmtree(hone.dirs.runs / run_id, ignore_errors=True)
    hone._sync_index_from_git()
    print(f"rewound {run_id}: AGENTS.md back at {run['base_version_id']}, {len(run['trace_ids'])} traces new again")


def nudge(service: str | None, token: str) -> None:
    """POST /api/config {} changes nothing but publishes `config_changed`, which
    makes every open dashboard refetch /api/state (and see the run)."""
    if not service:
        return
    request = urllib.request.Request(
        f"{service.rstrip('/')}/api/config", data=b"{}", method="POST",
        headers={"content-type": "application/json", "authorization": f"Bearer {token}"},
    )
    try:
        urllib.request.urlopen(request, timeout=5).read()
    except (urllib.error.URLError, OSError) as exc:
        print(f"warning: could not nudge {service}: {exc}", file=sys.stderr)


async def live(args: argparse.Namespace) -> None:
    data_dir = args.data_dir.resolve()
    settings = load_seeded_settings(data_dir)
    clock = Clock(speed=args.speed)
    director = Director(clock, args.seed)
    install_director(director)
    hone = Hone(settings)
    director.hone = hone
    run_id = args.run_id
    if hone.db.run(run_id):
        if not args.rewind:
            raise SystemExit(f"run {run_id} already exists; pass --rewind to undo it and replay again")
        rewind(hone, run_id)
        nudge(args.service, settings.service.token)
    story = STORIES["live"]
    if args.fail:
        story = replace(story, failed_propose_attempts=settings.optimization.max_attempts)
    fresh = [t for t in hone.db.traces() if t["status"] == "new"]
    if len(fresh) != len(story.batch):
        raise SystemExit(f"live replay expects {len(story.batch)} unanalyzed traces, found {len(fresh)}")
    if story.final.edits[0].old not in hone.dirs.read_current():
        raise SystemExit("live replay expects the seeded AGENTS.md (its conditional-block rule is missing)")
    hone.set_config(batch_size=max(len(story.batch), hone.db.get_config("batch_size")))
    ids.new_run_id = lambda: run_id
    print(f"replaying {run_id} at {args.speed:g}x: open {args.service or '<service>'}/runs/{run_id}")
    director.story = story
    hone.start_run(trigger="manual")
    nudge(args.service, settings.service.token)
    task = hone._run_task
    assert task is not None
    await task
    nudge(args.service, settings.service.token)
    run = hone.db.run(run_id)
    hone.close()
    print(f"{run_id} {run['status']} in {run['duration_ms'] / 1000:.1f}s -> {run['result_version_id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    seed_p = sub.add_parser("seed", help="write a fresh demo data dir")
    seed_p.add_argument("--data-dir", type=Path, required=True)
    seed_p.add_argument("--reviewers", type=int, default=3)
    seed_p.add_argument("--proposers", type=int, default=3)
    seed_p.add_argument("--seed", type=int, default=7)
    seed_p.add_argument("--end", default="2026-11-02", help="date of the last (live-batch) sessions")
    seed_p.add_argument("--force", action="store_true", help="wipe an existing Hone data dir first")
    live_p = sub.add_parser("live", help="replay the next run in real time against a running service")
    live_p.add_argument("--data-dir", type=Path, required=True)
    live_p.add_argument("--run-id", default=LIVE_RUN_ID)
    live_p.add_argument("--speed", type=float, default=11.0, help="time compression; 11 plays the ~13 min run in ~75 s")
    live_p.add_argument("--service", help="service URL to nudge so open dashboards refresh, e.g. http://127.0.0.1:8090")
    live_p.add_argument("--rewind", action="store_true", help="undo a previous replay of this run id first")
    live_p.add_argument("--seed", type=int, default=7)
    live_p.add_argument("--fail", action="store_true", help="every propose attempt dies, so the run ends failed")
    args = parser.parse_args()
    if args.command == "seed":
        for name in ("reviewers", "proposers"):
            if not 2 <= getattr(args, name) <= 8:
                parser.error(f"--{name} must be between 2 and 8 (Hone requires a panel of at least 2)")
        asyncio.run(seed(args))
    else:
        if args.speed <= 0:
            parser.error("--speed must be positive")
        asyncio.run(live(args))


if __name__ == "__main__":
    main()
