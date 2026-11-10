"""Writes the office files of the spreadsheet scenario.

python3 make_files.py <project dir>

<project dir>/Inbox gets the expense report template and one receipts PDF per employee.
The company and its address are the same as in the offer letter scenario.
"""

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Border, Font, PatternFill, Side
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas

COMPANY = "Kestrel Analytics Ltd"
TEMPLATE = "Expense report template.xlsx"
CATEGORIES = ["Travel", "Accommodation", "Meals", "Taxis", "Conferences", "Office supplies", "Event materials"]

# name, department, cost centre, receipts as (date, merchant, address, lines, total, card)
EMPLOYEES = [
    ("Tom Becker", "Engineering", "E-115", [
        ("02/10/2026", "Pennine Rail", "London Kings Cross", ["Return London Kings Cross to Leeds", "Standard, off peak"], "142.60", "2291"),
        ("02/10/2026", "Corn Exchange Hotel", "Call Lane, Leeds LS1 7BR", ["1 night, 02 Oct to 03 Oct", "Room only"], "129.00", "2291"),
        ("03/10/2026", "Leeds Taxi Co", "Leeds", ["Hotel to client office, Wellington Place"], "18.20", "2291"),
        ("03/10/2026", "Tiled Hall Cafe", "Headrow, Leeds LS1 3AA", ["Lunch, 1 guest"], "12.40", "2291"),
        ("21/10/2026", "Northbook Press", "online order NB-48812", ["Two technical books"], "64.98", "2291"),
        ("28/10/2026", "CloudSummit London", "ExCeL London", ["Workshop ticket, 28 Oct"], "1080.00", "2291"),
    ]),
    ("Ana Ruiz", "Marketing", "M-330", [
        ("09/10/2026", "SkyBridge Air", "London Heathrow", ["Return flight London to Edinburgh", "Economy, 1 bag"], "214.30", "7730"),
        ("09/10/2026", "Canongate Rooms", "Canongate, Edinburgh EH8 8BN", ["2 nights, 09 Oct to 11 Oct"], "278.00", "7730"),
        ("10/10/2026", "Edinburgh Print Works", "Leith Walk, Edinburgh EH6 5HB", ["Event banners, 4 pieces", "Delivery to venue"], "1420.00", "7730"),
        ("10/10/2026", "Royal Mile Taxis", "Edinburgh", ["Venue to hotel"], "16.80", "7730"),
        ("10/10/2026", "The Grain Store", "Victoria Street, Edinburgh EH1 2LW", ["Team dinner, 3 guests"], "132.75", "7730"),
    ]),
    ("Priya Natarajan", "Sales", "S-210", [
        ("06/10/2026", "Pennine Rail", "London Euston", ["Return London Euston to Manchester Piccadilly", "Standard, anytime"], "187.40", "4417"),
        ("06/10/2026", "Hotel Albion", "Peter Street, Manchester M2 5GP", ["2 nights, 06 Oct to 08 Oct", "Room only"], "312.00", "4417"),
        ("07/10/2026", "Ancoats Kitchen", "Blossom Street, Manchester M4 6AJ", ["Client dinner, 4 guests"], "146.80", "4417"),
        ("07/10/2026", "City Cabs Manchester", "Manchester", ["Hotel to client office, Spinningfields"], "23.50", "4417"),
        ("08/10/2026", "Station Deli", "Manchester Piccadilly", ["Lunch"], "8.95", "4417"),
        ("14/10/2026", "DataConf UK", "Manchester Central", ["Conference registration, 2 days"], "1250.00", "4417"),
    ]),
    ("Ben Okafor", "Customer Success", "C-140", [
        ("15/10/2026", "Pennine Rail", "London Euston", ["Return London Euston to Birmingham New Street", "Standard, off peak"], "98.20", "5062"),
        ("15/10/2026", "Jewellery Quarter Hotel", "Vyse Street, Birmingham B18 6HS", ["1 night, 15 Oct to 16 Oct"], "119.00", "5062"),
        ("16/10/2026", "Brindley Place Bistro", "Brindley Place, Birmingham B1 2HP", ["Client lunch, 2 guests"], "58.40", "5062"),
        ("16/10/2026", "Birmingham Cabs", "Birmingham", ["Client office to station"], "14.60", "5062"),
        ("22/10/2026", "SaaS Connect London", "Olympia London", ["Conference pass, 2 days"], "1195.00", "5062"),
    ]),
]


def receipts_name(name):
    return f"Receipts October 2026 {name}.pdf"


def write_template(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Expense report"
    ws["A1"] = COMPANY
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Expense report"
    ws["A2"].font = Font(bold=True, size=12)
    for row, label in enumerate(["Employee", "Department", "Cost centre", "Month"], start=4):
        ws.cell(row=row, column=1, value=label).font = Font(bold=True)
    header = ["Date", "Merchant", "Category", "Description", "Amount (GBP)"]
    fill = PatternFill("solid", fgColor="E8E8EE")
    line = Border(bottom=Side(style="thin", color="8A8A99"))
    for col, title in enumerate(header, start=1):
        c = ws.cell(row=9, column=col, value=title)
        c.font = Font(bold=True)
        c.fill = fill
        c.border = line
    for col, width in zip("ABCDE", [14, 26, 18, 44, 16]):
        ws.column_dimensions[col].width = width
    cats = wb.create_sheet("Categories")
    cats["A1"] = "Category"
    cats["A1"].font = Font(bold=True)
    for i, cat in enumerate(CATEGORIES, start=2):
        cats.cell(row=i, column=1, value=cat)
    cats.column_dimensions["A"].width = 22
    wb.save(path)


def write_receipts(path, name, department, centre, receipts):
    width, height = A4
    left, right = 56.0, width - 56.0
    c = pdf_canvas.Canvas(str(path), pagesize=A4, invariant=1)
    c.setTitle(receipts_name(name)[:-4])
    c.setAuthor(name)

    def page_head():
        y = height - 64
        c.setFont("Helvetica-Bold", 15)
        c.drawString(left, y, COMPANY)
        c.setFont("Helvetica-Bold", 13)
        c.drawRightString(right, y, "Expense receipts")
        c.setFont("Helvetica", 9.5)
        c.drawString(left, y - 18, f"Submitted by {name}, {department}, cost centre {centre}")
        c.drawRightString(right, y - 18, "October 2026")
        return y - 44

    y = page_head()
    for date, merchant, address, lines, total, card in receipts:
        box_h = 60 + 15 * len(lines)
        if y - box_h < 60:
            c.showPage()
            y = page_head()
        c.setStrokeColorRGB(0.7, 0.7, 0.75)
        c.setLineWidth(0.8)
        c.rect(left, y - box_h, right - left, box_h)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(left + 14, y - 22, merchant)
        c.setFont("Helvetica", 9.5)
        c.drawRightString(right - 14, y - 22, date)
        c.drawString(left + 14, y - 36, address)
        ly = y - 56
        for text in lines:
            c.drawString(left + 24, ly, text)
            ly -= 15
        c.setFont("Helvetica-Bold", 10.5)
        c.drawRightString(right - 14, y - box_h + 14, f"Total GBP {total}")
        c.setFont("Helvetica", 9)
        c.drawString(left + 14, y - box_h + 14, f"Paid by card ending {card}")
        y -= box_h + 18
    c.showPage()
    c.save()


def main():
    inbox = Path(sys.argv[1]) / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    write_template(inbox / TEMPLATE)
    for name, department, centre, receipts in EMPLOYEES:
        write_receipts(inbox / receipts_name(name), name, department, centre, receipts)
    print("wrote", inbox)


if __name__ == "__main__":
    main()
