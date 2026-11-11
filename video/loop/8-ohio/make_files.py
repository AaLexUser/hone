"""Writes the client briefs and the proposal template of the "Ohio is not in Oxford" scenario.

python3 make_files.py <project dir>

<project dir>/Inbox gets one request for proposal per client, RFP_<Client>.pdf, each on the
client's own letterhead with its street address and country, and proposal_template.docx, the
agency's two page proposal. The agency is a design studio in Leeds. Its AGENTS.md says to use
British spelling, so the agent writes "organisation" and "colour" for American clients too.
US briefs are written in American spelling and UK briefs in British spelling, as each client
would write them.
"""

import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

US = dict(page=LETTER, colour="color", organisation="organization", programme="program",
          centre="center", prioritise="prioritize", money="$", country="United States")
UK = dict(page=A4, colour="colour", organisation="organisation", programme="programme",
          centre="centre", prioritise="prioritise", money="£", country="United Kingdom")

CLIENTS = [
    dict(slug="HarborMain", name="Harbor & Main Clinics", sector="a community health provider",
         street="400 North High Street", city="Columbus, OH 43215", contact="Dana Whitfield, Director of Communications",
         sites="nine clinics", budget="60,000", weeks=12, due="December 4, 2026", **US),
    dict(slug="AncoatsHousing", name="Ancoats Housing Trust", sector="a social housing provider",
         street="12 Jersey Street", city="Manchester M4 6JB", contact="Priya Shah, Head of Communications",
         sites="fourteen estates", budget="45,000", weeks=10, due="4 December 2026", **UK),
    dict(slug="LoneOak", name="Lone Oak Credit Union", sector="a member-owned credit union",
         street="1100 Congress Avenue", city="Austin, TX 78701", contact="Marcus Reyes, VP Marketing",
         sites="six branches", budget="75,000", weeks=14, due="December 8, 2026", **US),
    dict(slug="HarboursideArts", name="Harbourside Arts Centre", sector="an arts charity",
         street="21 Anchor Road", city="Bristol BS1 5TT", contact="Tom Ellery, Marketing Manager",
         sites="two venues", budget="30,000", weeks=8, due="8 December 2026", **UK),
    dict(slug="FrontRange", name="Front Range Public Libraries", sector="a public library service",
         street="10 West 14th Avenue", city="Denver, CO 80204", contact="Alicia Moreno, Communications Lead",
         sites="eleven branch libraries", budget="55,000", weeks=12, due="December 15, 2026", **US),
    dict(slug="ClydeTheatre", name="Clyde Youth Theatre", sector="a youth theatre charity",
         street="45 Trongate", city="Glasgow G1 5HD", contact="Fiona Baird, General Manager",
         sites="three rehearsal spaces", budget="25,000", weeks=8, due="15 December 2026", **UK),
]


def brief_paragraphs(c):
    return [
        ("Request for proposal: brand refresh",
         f"{c['name']} is {c['sector']} with {c['sites']}. Our identity has grown piece by piece and no longer "
         f"looks like one {c['organisation']}. We are inviting design studios to propose a brand refresh."),
        ("What we need",
         f"A refreshed logo and a {c['colour']} palette that works on screen, in print and on signage at every "
         f"{c['centre']}. A short brand guide our own staff can follow. A {c['programme']} of three staff workshops "
         f"so teams across the {c['organisation']} apply the new brand consistently."),
        ("What matters to us",
         f"Please {c['prioritise']} accessibility, including {c['colour']} contrast for people with low vision, "
         f"and show how you would involve front line staff."),
        ("Budget and timeline",
         f"Up to {c['money']}{c['budget']} including workshops. Work should finish within {c['weeks']} weeks of "
         f"appointment. Proposals of no more than two pages are due by {c['due']}."),
    ]


def write_brief(c, path):
    width, height = c["page"]
    pdf = canvas.Canvas(str(path), pagesize=c["page"])
    pdf.setTitle(f"{c['name']} request for proposal")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, height - 22 * mm, c["name"])
    pdf.setFont("Helvetica", 10)
    for i, line in enumerate([c["street"], c["city"], c["country"]]):
        pdf.drawString(20 * mm, height - (29 + 5 * i) * mm, line)
    pdf.line(20 * mm, height - 47 * mm, width - 20 * mm, height - 47 * mm)
    y = height - 58 * mm
    for heading, body in brief_paragraphs(c):
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(20 * mm, y, heading)
        y -= 7 * mm
        pdf.setFont("Helvetica", 10.5)
        line = ""
        for word in body.split():
            if pdf.stringWidth(line + " " + word, "Helvetica", 10.5) > width - 40 * mm:
                pdf.drawString(20 * mm, y, line.strip())
                y -= 5.5 * mm
                line = ""
            line += " " + word
        pdf.drawString(20 * mm, y, line.strip())
        y -= 11 * mm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, y, f"Contact: {c['contact']}")
    pdf.save()


def write_template(path):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    doc.add_paragraph("Kirkgate Studio, 3 Kirkgate, Leeds LS1 6BY")
    doc.add_heading("Proposal for [Client name]", level=1)
    doc.add_paragraph("[Date]")
    for heading, hint in [
        ("Your brief", "[Two or three sentences on what the client asked for, in our words.]"),
        ("Our approach", "[How we would do the work, step by step.]"),
        ("Deliverables", "[A short list of what the client receives.]"),
        ("Timeline", "[Phases with weeks.]"),
        ("Fees", "[Fee per phase and the total, within the client's budget.]"),
        ("Next steps", "[One or two sentences.]"),
    ]:
        doc.add_heading(heading, level=2)
        doc.add_paragraph(hint)
    doc.save(str(path))


def main(project):
    inbox = Path(project) / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for c in CLIENTS:
        write_brief(c, inbox / f"RFP_{c['slug']}.pdf")
    write_template(inbox / "proposal_template.docx")


if __name__ == "__main__":
    main(sys.argv[1])
