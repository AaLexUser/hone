"""Writes the interview transcripts of the anonymisation scenario.

python3 make_files.py <project dir>

<project dir>/Inbox gets one DOCX per interview of a study on how data analysts use dashboards.
Each transcript names its participant in four places: the page header ("Interview with Mei Lin,
12 October 2026"), a demographics table on page 1, the bold speaker label on each answer ("Mei")
and the body, where the interviewer says "Mei", "Ms Lin" or "Mei Lin". Employer and city appear
in the table and the body. The participant also names two or three colleagues and a manager,
who must be anonymised too, though the request names only the participant.
"""

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt

PEOPLE = [
    dict(no="03", name="Mei Lin", first="Mei", title="Ms", last="Lin", job="Senior data analyst",
         employer="Northwind Logistics", city="Rotterdam", date="12 October 2026", pronoun="her", others=("Jonas Berg", "Priya Nair", "Ruben de Vries")),
    dict(no="04", name="Daniel Huber", first="Daniel", title="Mr", last="Huber", job="BI developer",
         employer="Alpenwerk Energie", city="Graz", date="14 October 2026", pronoun="his", others=("Katrin Moser", "Lukas Brandt", "Elena Weiss")),
    dict(no="05", name="Amara Okafor", first="Amara", title="Ms", last="Okafor", job="Analytics lead",
         employer="Harbourline Retail", city="Leeds", date="16 October 2026", pronoun="her", others=("Grace Whitfield", "Tom Ashworth", "Nadia Rahman")),
    dict(no="06", name="Tomás Ferreira", first="Tomás", title="Mr", last="Ferreira", job="Data engineer",
         employer="Atlântico Seguros", city="Porto", date="19 October 2026", pronoun="his", others=("Inês Carvalho", "Rui Matos", "Beatriz Lopes")),
    dict(no="07", name="Sofia Marin", first="Sofia", title="Ms", last="Marin", job="Product analyst",
         employer="Carpathia Telecom", city="Cluj-Napoca", date="21 October 2026", pronoun="her", others=("Andrei Popescu", "Ioana Dobre", "Mihai Stan")),
]


def exchanges(p):
    f, t, n, e, c = p["first"], f"{p['title']} {p['last']}", p["name"], p["employer"], p["city"]
    boss, peer, junior = p["others"]
    return [
        (f"Thanks for joining, {f}. Could you start with your role at {e}?",
         f"Sure. I'm a {p['job'].lower()} at {e}, in the {c} office. Most of my week goes into the dashboards the operations team opens every morning."),
        (f"{t}, which dashboard do you open first each day?",
         "The daily exceptions view. If a number looks off there, I go back to the source tables before anyone acts on it."),
        ("How often does a number on a dashboard turn out to be wrong?",
         f"More than people think. Last month a join counted every order twice and nobody in {c} noticed for a week, until {peer} spotted it in the weekly review."),
        (f"What did you change after that, {f}?",
         f"My manager, {boss}, asked for a row count check next to every chart. {junior.split()[0]} built it in two days. If the count moves more than ten percent overnight the chart turns grey."),
        (f"Do colleagues at {e} trust the dashboards now?",
         f"More than before. {boss} still messages me when something looks strange, which I think is healthy."),
        (f"Last question, {n}. What would you want from a tool that explains a dashboard?",
         "Tell me where each number comes from in one sentence. I don't want another chart, I want the reason."),
        (f"Thank you, {t}. That's everything.", "Happy to help."),
    ]


def write_transcript(p, path):
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    doc.sections[0].header.paragraphs[0].text = f"Interview with {p['name']}, {p['date']}"
    doc.add_heading(f"Interview {p['no']}", level=1)
    doc.add_paragraph("Study on how data analysts check the numbers on their dashboards.")
    table = doc.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    for row, (k, v) in zip(table.rows, [("Name", p["name"]), ("Job title", p["job"]),
                                         ("Employer", p["employer"]), ("City", p["city"])]):
        row.cells[0].text, row.cells[1].text = k, v
    doc.add_paragraph("")
    for question, answer in exchanges(p):
        q = doc.add_paragraph()
        q.add_run("Interviewer: ").bold = True
        q.add_run(question)
        a = doc.add_paragraph()
        a.add_run(f"{p['first']}: ").bold = True
        a.add_run(answer)
    doc.save(str(path))


def main(project):
    inbox = Path(project) / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for p in PEOPLE:
        write_transcript(p, inbox / f"Interview {p['no']} {p['name']}.docx")


if __name__ == "__main__":
    main(sys.argv[1])
