"""Writes the registration lists and the badge sheet template of the name badge scenario.

python3 make_files.py <project dir>

<project dir>/Inbox gets one registration list per workshop, `Registrations <Workshop>.pdf`
(badge name, affiliation, role), and `Badge sheet template.docx`, an A4 sheet of perforated
badges: a 2 by 4 table of 90 by 55 mm cells at exact row height, each with a workshop line, a
{{NAME}} line in a 28 pt bold style, an {{AFFILIATION}} line and a {{ROLE}} line. At 28 pt a
name longer than about 14 characters wraps, and a name that needs three lines is cut off by the
exact row height.
"""

import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

WORKSHOPS = {
    "Graph Mining Workshop": [
        ("Xu Li", "Tsinghua University", "Speaker"),
        ("Anastasia Papadimitriou-Wolfe", "University of Edinburgh", "Speaker"),
        ("Jan de Vries", "TU Delft", "Participant"),
        ("Muhammad Abdurrahman Al-Khatib", "KAUST", "Organiser"),
        ("Sara Lindqvist", "KTH Stockholm", "Participant"),
        ("Bartholomew Featherstonehaugh", "University of Oxford", "Participant"),
        ("Ana Sá", "University of Porto", "Speaker"),
        ("Oluwaseun Adebayo-Okonkwo", "University of Lagos", "Participant"),
    ],
    "Data Streams Workshop": [
        ("Mei Chen", "NUS", "Speaker"),
        ("Konstantinos Vasilopoulos", "Athena Research Center", "Organiser"),
        ("Leo Park", "KAIST", "Participant"),
        ("Maria Guadalupe Hernández-Villanueva", "UNAM", "Speaker"),
        ("Tom Ruiz", "EPFL", "Participant"),
        ("Venkataraghavan Subramanian", "IIT Madras", "Participant"),
        ("Ida Holm", "Aalborg University", "Participant"),
        ("Friederike von Hohenstein-Schulz", "TU Munich", "Speaker"),
    ],
    "Fairness in ML Workshop": [
        ("Zoe Grant", "University of Toronto", "Organiser"),
        ("Aleksandra Wiśniewska-Kowalczyk", "University of Warsaw", "Speaker"),
        ("Raj Patel", "Imperial College London", "Participant"),
        ("Christopher Montgomery-Ashford", "University of Cambridge", "Participant"),
        ("Yuki Sato", "University of Tokyo", "Speaker"),
        ("Emmanuel Nwachukwu-Eze", "University of Ibadan", "Participant"),
        ("Lea Roth", "ETH Zurich", "Participant"),
        ("Francesca Bianchi-Santangelo", "Politecnico di Milano", "Speaker"),
    ],
    "Time Series Workshop": [
        ("Omar Haddad", "American University of Beirut", "Speaker"),
        ("Gwendolyn Fitzgerald-Hughes", "Trinity College Dublin", "Organiser"),
        ("Ivo Novak", "Charles University", "Participant"),
        ("Thiruvengadam Ramakrishnan", "IISc Bangalore", "Speaker"),
        ("Eva Kim", "Seoul National University", "Participant"),
        ("Jean-Baptiste Delacroix-Moreau", "Sorbonne University", "Participant"),
        ("Nora Berg", "University of Oslo", "Participant"),
        ("Alessandro Castellammare", "University of Bologna", "Speaker"),
    ],
    "Explainable AI Workshop": [
        ("Li Wei", "Peking University", "Speaker"),
        ("Maximilian Schwarzenberger", "University of Vienna", "Organiser"),
        ("Ola Nowak", "AGH Kraków", "Participant"),
        ("Rosalind Abernathy-Whitmore", "University of Bristol", "Speaker"),
        ("Hugo Lima", "University of São Paulo", "Participant"),
        ("Srinivasaraghavan Venkatesan", "IIT Bombay", "Participant"),
        ("Kai Weber", "TU Berlin", "Participant"),
        ("Philippa Worthington-Smythe", "University of Durham", "Speaker"),
    ],
}


def write_registrations(workshop, people, path):
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle(f"Registrations {workshop}")
    width, height = A4
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(20 * mm, height - 25 * mm, f"{workshop}, IEEE ICDM 2026")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, height - 32 * mm, "Confirmed registrations for badge printing")
    cols = [20 * mm, 100 * mm, 165 * mm]
    y = height - 45 * mm
    pdf.setFont("Helvetica-Bold", 10)
    for x, h in zip(cols, ["Badge name", "Affiliation", "Role"]):
        pdf.drawString(x, y, h)
    pdf.line(20 * mm, y - 2 * mm, width - 20 * mm, y - 2 * mm)
    pdf.setFont("Helvetica", 10)
    for person in people:
        y -= 8 * mm
        for x, v in zip(cols, person):
            pdf.drawString(x, y, v)
    pdf.save()


def write_template(path):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(15)
    section.top_margin = section.bottom_margin = Mm(38)
    styles = doc.styles
    for name, size, bold, italic in [("Badge Workshop", 9, False, False), ("Badge Name", 28, True, False),
                                     ("Badge Affiliation", 12, False, False), ("Badge Role", 11, False, True)]:
        style = styles.add_style(name, 1)
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = bold
        style.font.italic = italic
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        style.paragraph_format.space_after = Pt(4)
    styles["Badge Name"].paragraph_format.space_before = Pt(10)
    table = doc.add_table(rows=4, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    for row in table.rows:
        row.height = Mm(55)
        row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
        for cell in row.cells:
            cell.width = Mm(90)
            first = cell.paragraphs[0]
            first.text, first.style = "{{WORKSHOP}}", styles["Badge Workshop"]
            for text, style in [("{{NAME}}", "Badge Name"), ("{{AFFILIATION}}", "Badge Affiliation"), ("{{ROLE}}", "Badge Role")]:
                cell.add_paragraph(text, style=styles[style])
    doc.save(str(path))


def main(project):
    inbox = Path(project) / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for workshop, people in WORKSHOPS.items():
        write_registrations(workshop, people, inbox / f"Registrations {workshop}.pdf")
    write_template(inbox / "Badge sheet template.docx")


if __name__ == "__main__":
    main(sys.argv[1])
