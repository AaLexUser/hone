"""Real office files. The approval PDFs, the letter template, and a workspace
that runs the transcripts' commands for real.

The approval forms are drawn with reportlab. Every other document in the
project folder comes from running the exact command a prepared chat shows
(pdftotext, a python-docx fill script, LibreOffice), so each output file shows
the flaw its chat is about.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

from .scenario import (
    COMPANY,
    COMPANY_ADDRESS,
    DEPARTMENT_HEADS,
    TEMPLATE,
    WORKSPACE,
    Hire,
)

# Adapted from the SkillsBench offer-letter-generator task (Apache 2.0): a UK
# company, A4, pounds, a fixed signer, and the original's split runs kept.
TEMPLATE_ASSET = Path(__file__).parent / "assets" / "Offer letter template.docx"

REQUIRED_TOOLS = ("pdftotext", "soffice")


def check_tools() -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(f"the demo scenario needs {', '.join(missing)} on PATH (poppler and LibreOffice)")


# --------------------------------------------------------------------------- #
# Hiring approval form
# --------------------------------------------------------------------------- #

INK = (0.11, 0.17, 0.42)
GREY = (0.42, 0.44, 0.5)


def _signature(canvas, name: str, x: float, y: float) -> None:
    """A pen scribble seeded by the name, so the same person always signs alike."""
    rng = random.Random(name)
    points: list[tuple[float, float]] = [(x, y + 4)]
    cx = x
    for word in name.split():
        cx += rng.uniform(2, 5)
        points += [(cx + 3, y + rng.uniform(22, 28)), (cx + 7, y - rng.uniform(1, 4)), (cx + 9, y + 9)]
        cx += 10
        for _ in range(max(3, len(word) - 1)):
            step = rng.uniform(4.5, 7.5)
            points += [(cx + step * 0.5, y + rng.uniform(6, 13)), (cx + step, y + rng.uniform(0, 2.5))]
            cx += step
        cx += rng.uniform(6, 10)
    points.append((cx + 6, y + 10))
    points += [(cx - 20, y - 4), (x + 10, y - rng.uniform(2, 6)), (x - 4, y + 1)]
    points = [(px + (py - y) * 0.28, py) for px, py in points]

    path = canvas.beginPath()
    path.moveTo(*points[0])
    padded = [points[0], *points, points[-1]]
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        path.curveTo(*c1, *c2, *p2)
    canvas.setStrokeColorRGB(*INK)
    canvas.setLineWidth(1.15)
    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    canvas.drawPath(path, stroke=1, fill=0)


def approval_rows(h: Hire, start: dt.date) -> list[tuple[str, list[tuple[str, str]]]]:
    bonus = f"£{h.bonus}"
    relocation = f"Yes, £{h.relocation} and 30 days temporary housing" if h.relocation else "No"
    return [
        ("Candidate", [
            ("Name", h.name),
            ("Home address", f"{h.street}, {h.city} {h.postcode}"),
        ]),
        ("Role", [
            ("Job title", h.position),
            ("Department", h.department),
            ("Reports to", h.manager or ""),
            ("Start date", start.isoformat()),
            ("Contract", "Permanent, full time"),
        ]),
        ("Offer", [
            ("Base salary", f"£{h.salary} per year"),
            ("Sign-on bonus", bonus),
            ("Equity", f"{h.equity} shares"),
            ("Relocation package", relocation),
            ("Annual leave", "25 days plus bank holidays"),
            ("Offer valid for", "7 days from the offer letter"),
        ]),
    ]


def write_approval(path: Path, h: Hire, ref: str, approved: dt.date, start: dt.date) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas

    head, head_title = DEPARTMENT_HEADS[h.department]
    width, height = A4
    left, value_x, right = 56.0, 210.0, width - 56.0
    c = pdf_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(f"Hiring approval {h.name}")
    c.setAuthor(f"{head}, {head_title}")
    c.setSubject(COMPANY)

    y = height - 64
    c.setFillColorRGB(0.1, 0.1, 0.12)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(left, y, COMPANY)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(right, y, "Hiring approval")
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(*GREY)
    c.drawString(left, y - 15, "People Team")
    c.drawRightString(right, y - 15, f"Ref {ref}")
    y -= 32
    c.setStrokeColorRGB(0.8, 0.81, 0.85)
    c.setLineWidth(0.8)
    c.line(left, y, right, y)

    y -= 30
    for section, rows in approval_rows(h, start):
        c.setFillColorRGB(0.1, 0.1, 0.12)
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(left, y, section)
        y -= 20
        for label, value in rows:
            c.setFont("Helvetica", 9.5)
            c.setFillColorRGB(*GREY)
            c.drawString(left + 10, y, label)
            c.setFont("Helvetica", 10.5)
            c.setFillColorRGB(0.1, 0.1, 0.12)
            c.drawString(value_x, y, value)
            c.setStrokeColorRGB(0.9, 0.9, 0.92)
            c.setLineWidth(0.5)
            c.line(value_x, y - 5, right, y - 5)
            y -= 19
        y -= 14

    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(left, y, "Approval")
    y -= 20
    c.setFont("Helvetica", 9.5)
    c.setFillColorRGB(*GREY)
    c.drawString(left + 10, y - 26, "Approved by")
    _signature(c, head, value_x + 6, y - 22)
    c.setStrokeColorRGB(0.55, 0.56, 0.6)
    c.setLineWidth(0.6)
    c.line(value_x, y - 31, value_x + 200, y - 31)
    c.setFont("Helvetica", 10.5)
    c.setFillColorRGB(0.1, 0.1, 0.12)
    c.drawString(value_x, y - 45, f"{head}, {head_title}")
    c.setFont("Helvetica", 9.5)
    c.setFillColorRGB(*GREY)
    c.drawString(left + 10, y - 66, "Date approved")
    c.setFont("Helvetica", 10.5)
    c.setFillColorRGB(0.1, 0.1, 0.12)
    c.drawString(value_x, y - 66, approved.isoformat())

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*GREY)
    c.drawString(left, 40, f"{COMPANY}, {COMPANY_ADDRESS}. Internal, please do not forward.")
    c.showPage()
    c.save()


# --------------------------------------------------------------------------- #
# Scripts the agent writes and runs
# --------------------------------------------------------------------------- #


def py_heredoc(body: str) -> str:
    return f"python3 - <<'EOF'\n{body.strip()}\nEOF"


DUMP_TEMPLATE = py_heredoc(f"""
from docx import Document

d = Document('{TEMPLATE}')


def show(paragraphs, indent=''):
    for p in paragraphs:
        if p.text.strip():
            runs = [r.text for r in p.runs]
            print(indent + repr(p.text), 'runs=' + repr(runs) if '{{{{' in p.text and len(runs) > 1 else '')


def tables(container, indent=''):
    for t in container.tables:
        for row in t.rows:
            for cell in row.cells:
                show(cell.paragraphs, indent + '  ')
                tables(cell, indent + '  ')


show(d.paragraphs)
print('TABLES')
tables(d)
s = d.sections[0]
print('HEADER', [p.text for p in s.header.paragraphs])
print('FOOTER', [p.text for p in s.footer.paragraphs])
""")


def dump_details(docx: str) -> str:
    """The nested details table of a letter, one row per line."""
    return py_heredoc(f"""
from docx import Document

d = Document('{docx}')
for outer in d.tables:
    for row in outer.rows:
        for cell in row.cells:
            for t in cell.tables:
                for r in t.rows:
                    print(' | '.join(c.text for c in r.cells))
""")


def print_letter(docx: str) -> str:
    return py_heredoc(f"""
from docx import Document

d = Document('{docx}')
s = d.sections[0]
print('[header]', s.header.paragraphs[0].text)
for p in d.paragraphs:
    print(p.text)
print('---')
for outer in d.tables:
    for row in outer.rows:
        for cell in row.cells:
            for t in cell.tables:
                for r in t.rows:
                    print(' | '.join(c.text for c in r.cells))
print('[footer]', s.footer.paragraphs[0].text)
""")


def check_formatting(docx: str) -> str:
    return py_heredoc(f"""
from docx import Document

d = Document('{docx}')
deadline = next(p for p in d.paragraphs if p.text.startswith('Please respond'))
print('deadline', [(r.text, r.bold, r.underline) for r in deadline.runs if r.text])
for outer in d.tables:
    for row in outer.rows:
        for cell in row.cells:
            for t in cell.tables:
                for r in t.rows:
                    if r.cells[0].text == 'Base Salary:':
                        print('salary', [(x.text, x.bold) for x in r.cells[1].paragraphs[0].runs if x.text])
""")


FILL_COLLAPSE = """\
def fill(p):
    text = p.text
    if '{{' not in text:
        return
    for key, value in values.items():
        text = text.replace('{{' + key + '}}', value)
    p.runs[0].text = text
    for r in p.runs[1:]:
        r.text = ''"""

FILL_RUN_AWARE = """\
def fill(p):
    # placeholders are split across runs, so pull the pieces into the run
    # where each one starts and every other run keeps its own formatting
    runs = p.runs
    for i, run in enumerate(runs):
        text = run.text
        j = i + 1
        while text.count('{{') > text.count('}}') and j < len(runs):
            text += runs[j].text
            runs[j].text = ''
            j += 1
        for key, value in values.items():
            text = text.replace('{{' + key + '}}', value)
        run.text = text"""

BLOCK_STRIP = """\
def relocation_block(p):
    if not RELOCATION:
        for r in p.runs:
            r.text = ''
        return
    for r in p.runs:
        r.text = r.text.replace('{{IF_RELOCATION}}', '').replace('{{END_IF_RELOCATION}}', '')"""

BLOCK_DELETE = """\
def relocation_block(p):
    if not RELOCATION:
        # AGENTS.md says a block that does not apply goes, heading included
        heading = p._p.getprevious()
        spacer = p._p.getnext()
        p._p.getparent().remove(p._p)
        if heading is not None and 'Relocation' in ''.join(heading.itertext()):
            heading.getparent().remove(heading)
        # The block sits between two spacers, so one goes with it
        if spacer is not None and spacer.tag == p._p.tag and not ''.join(spacer.itertext()).strip():
            spacer.getparent().remove(spacer)
        return
    for r in p.runs:
        r.text = r.text.replace('{{IF_RELOCATION}}', '').replace('{{END_IF_RELOCATION}}', '')"""

FILL_SCRIPT = """\
from datetime import date, timedelta

from docx import Document

TEMPLATE = '__TEMPLATE__'
OUT = '__OUT__'
RELOCATION = __RELOCATION__


def fmt(d):
    return __DATE_EXPR__


today = date.today()
values = {
__VALUES__
}


def paragraphs(container):
    yield from container.paragraphs
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from paragraphs(cell)


__FILL__


__BLOCK__


doc = Document(TEMPLATE)
parts = [doc] + [s.header for s in doc.sections] + [s.footer for s in doc.sections]
for part in parts:
    for p in list(paragraphs(part)):
        if '{{IF_RELOCATION}}' in p.text:
            relocation_block(p)
        fill(p)
doc.save(OUT)
left = [p.text for part in parts for p in paragraphs(part) if '{{' in p.text]
print('wrote', OUT)
print('unresolved placeholders:', left)
"""


def fill_script(values: list[tuple[str, str, str | None]], *, out: str, relocation: bool, us_dates: bool,
                collapse: bool, delete_blocks: bool) -> str:
    """`values` rows are (key, python expression, trailing comment)."""
    body = "\n".join(f"    '{key}': {expr},{f'  # {note}' if note else ''}" for key, expr, note in values)
    date_expr = "f'{d:%B} {d.day}, {d.year}'" if us_dates else "f'{d.day} {d:%B} {d.year}'"
    return (FILL_SCRIPT
            .replace("__TEMPLATE__", TEMPLATE)
            .replace("__OUT__", out)
            .replace("__RELOCATION__", str(relocation))
            .replace("__DATE_EXPR__", date_expr)
            .replace("__VALUES__", body)
            .replace("__FILL__", FILL_COLLAPSE if collapse else FILL_RUN_AWARE)
            .replace("__BLOCK__", BLOCK_DELETE if delete_blocks else BLOCK_STRIP))


def letter_values(h: Hire, ref: str, start: dt.date, manager: str,
                  manager_note: str | None = None) -> list[tuple[str, str, str | None]]:
    q = repr
    return [
        ("COMPANY_NAME", q(COMPANY), None),
        ("APPROVAL_REF", q(ref), None),
        ("DATE", "fmt(today)", None),
        ("CANDIDATE_FULL_NAME", q(h.name), None),
        ("CANDIDATE_FIRST_NAME", q(h.first), None),
        ("STREET_ADDRESS", q(h.street), None),
        ("CITY", q(h.city), None),
        ("POSTCODE", q(h.postcode), None),
        ("POSITION", q(h.position), None),
        ("DEPARTMENT", q(h.department), None),
        ("START_DATE", f"fmt(date({start.year}, {start.month}, {start.day}))", None),
        ("MANAGER_NAME", q(manager), manager_note),
        ("BASE_SALARY", q(h.salary), None),
        ("SIGNING_BONUS", q(h.bonus), None),
        ("EQUITY_SHARES", q(h.equity), None),
        ("RELOCATION_AMOUNT", q(h.relocation or ""), None),
        ("RELOCATION_DAYS", q("30" if h.relocation else ""), None),
        ("PTO_DAYS", q("25"), None),
        ("RESPONSE_DEADLINE", "fmt(today + timedelta(days=7))", None),
    ]


def retype_pdf_script(docx: str, pdf: str) -> str:
    return f"""\
import textwrap

from docx import Document
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

doc = Document('{docx}')
pdf = canvas.Canvas('{pdf}', pagesize=A4)
y = 790


def line(text):
    global y
    for part in textwrap.wrap(text, 90) or ['']:
        pdf.drawString(60, y, part)
        y -= 16


def table(t):
    for row in t.rows:
        texts = [c.text.strip() for c in row.cells if c.text.strip()]
        if texts:
            line('    '.join(texts))
        for c in row.cells:
            for nested in c.tables:
                table(nested)


for p in doc.paragraphs:
    line(p.text)
for t in doc.tables:
    table(t)
pdf.save()
print('wrote {pdf}')
"""


# --------------------------------------------------------------------------- #
# Workspace, the project folder with a shell that runs commands for real
# --------------------------------------------------------------------------- #

SITECUSTOMIZE = '''\
import datetime as _dt
import os as _os

_today = _os.environ.get("HONE_DEMO_TODAY")
if _today:
    class _Date(_dt.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(_today)

    _dt.date = _Date
'''


class Workspace:
    """The project folder, and a bash that runs a transcript's command in it.

    `python3` is this interpreter (it has python-docx and reportlab), the
    scripts' `date.today()` is the given day, LibreOffice gets a private
    profile, and `/tmp/` in a command maps to a private scratch dir. Output is
    reported with the folder as `{{WORKSPACE}}`, as Pi would print it there.
    """

    def __init__(self, root: Path, scratch: Path) -> None:
        self.root = root
        self.tmp = scratch / "tmp"
        for d in (root, self.tmp, scratch / "bin", scratch / "site"):
            d.mkdir(parents=True, exist_ok=True)
        python = scratch / "bin" / "python3"
        python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        python.chmod(0o755)
        (scratch / "site" / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        self.env = {
            **os.environ,
            "PATH": f"{scratch / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": str(scratch / "site"),
            "UserInstallation": (scratch / "libreoffice").as_uri(),
        }

    def bash(self, command: str, today: dt.date) -> tuple[str, bool]:
        proc = subprocess.run(
            ["bash", "-c", command.replace("/tmp/", f"{self.tmp}/")],
            cwd=self.root, env={**self.env, "HONE_DEMO_TODAY": today.isoformat()},
            capture_output=True, text=True, timeout=180, check=False,
        )
        lines = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                 if not ln.startswith("Warning: failed to launch javaldx")]
        out = self.shown("\n".join(lines) + "\n" if lines else "")
        if proc.returncode:
            out += f"\n\nCommand exited with code {proc.returncode}"
        return out, proc.returncode != 0

    def shown(self, text: str) -> str:
        return text.replace(str(self.root), WORKSPACE).replace(f"{self.tmp}/", "/tmp/")

    def write_tmp(self, name: str, content: str) -> int:
        (self.tmp / name).write_text(content, encoding="utf-8")
        return len(content.encode("utf-8"))

    def files(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*") if p.is_file())
