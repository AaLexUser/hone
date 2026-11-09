"""The office scenario. An HR coordinator turns hiring approvals into offer letters.

One hire table drives everything the demo shows. Each hire has a signed
approval PDF, one Pi session that writes the letter, the flaws that session
shows, and the feedback the coordinator left. The data dir, the chats and the
project folder are all built from this table, so they always agree.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

COMPANY = "Kestrel Analytics Ltd"
COMPANY_ADDRESS = "10 Brock Street, London NW1 3FG"
HR_SIGNER = "Laura Bennett"
TEMPLATE = "Inbox/Offer letter template.docx"
ARCHIVE_LETTER = "Archive/Offer_Harris_Ben.docx"
# Paths inside Pi session JSONL use this placeholder for the project folder.
WORKSPACE = "{{WORKSPACE}}"
PROJECT_TITLE = "Offer letters"

US_DATES = "us_dates"              # month first dates
OLD_NAMES = "old_names"            # Offer_Letter_First_Last.docx
NO_PDF = "no_pdf"
RELOC_GAP = "reloc_gap"            # clears the conditional block, keeps its heading
INVENTED_MANAGER = "invented_manager"
PDF_FALLBACK = "pdf_fallback"      # docx2pdf missing, reportlab retypes the text
COLLAPSED_RUNS = "collapsed_runs"  # paragraph text written into its first run
ZERO_ROWS = "zero_rows"            # prints the £0 and 0 shares rows

DEPARTMENT_HEADS = {
    "Data Platform": ("Tom Becker", "Head of Data Platform"),
    "Design": ("Grace Holt", "Head of Design"),
    "Applied ML": ("Ines Duarte", "Head of Applied ML"),
    "Sales": ("Martin Shaw", "Sales Director"),
    "Analytics": ("Priya Shah", "Head of Analytics"),
    "Platform": ("Kofi Mensah", "Head of Platform"),
    "Finance": ("Owen Price", "Finance Director"),
    "Infrastructure": ("Sam Okoro", "Head of Infrastructure"),
    "Operations": ("Nadia Wells", "Head of Operations"),
    "Marketing": ("Claire Lambert", "Marketing Director"),
    "Customer Success": ("Ellen Ward", "Head of Customer Success"),
}


@dataclass(frozen=True)
class Hire:
    key: str
    workday: int    # working days before the last prepared day
    clock: str      # local time the session starts
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
    manager: str | None      # None leaves Reports to empty on the approval
    ask: str
    flaws: frozenset[str] = frozenset()
    feedback: str | None = None
    answer: str | None = None  # the coordinator's reply when the agent asks for the manager

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"

    @property
    def approval(self) -> str:
        return f"Inbox/Hiring approval {self.name}.pdf"


V0 = frozenset({US_DATES, OLD_NAMES, NO_PDF})
HIRES = [
    Hire("t01", 10, "09:42", "Sarah", "Chen", "Senior Data Engineer", "Data Platform",
         "14 Albion Road", "London", "N16 9JS", "78,000", "5,000", "1,500", "8,000", "Tom Becker",
         "New hire today. The signed approval for Sarah Chen is in Inbox, please prepare her offer letter. "
         "Keep your reply short.",
         V0, "Write dates like 1 December 2026, as all our letters do"),
    Hire("t02", 9, "10:15", "Tomás", "Herrera", "Product Designer", "Design",
         "3 Cotham Hill", "Bristol", "BS6 6LA", "64,000", "3,000", "800", None, "Grace Holt",
         "Offer letter for Tomás please, his approval is in Inbox and the template as usual.",
         V0 | {RELOC_GAP, COLLAPSED_RUNS}, "There's a big empty gap where the relocation part was"),
    Hire("t03", 8, "14:03", "Aisha", "Okafor", "Machine Learning Engineer", "Applied ML",
         "27 Marchmont Road", "Edinburgh", "EH9 1HX", "82,000", "6,000", "2,000", "6,500", "Ines Duarte",
         "Can you do the offer letter for today's new hire? The approval came in this morning.",
         V0, "I need a PDF too. Name it Offer_Lastname_Firstname like the letters in Archive"),
    Hire("t04", 7, "09:58", "Daniel", "Novak", "Account Executive", "Sales",
         "8 Wilmslow Road", "Manchester", "M14 5TP", "58,000", "4,000", "600", "4,000", None,
         "Please prepare Daniel Novak's offer letter from the template and his hiring approval.",
         V0 | {INVENTED_MANAGER}, "Don't make up the manager, ask me"),
    Hire("t05", 6, "11:20", "Lena", "Fischer", "Data Analyst", "Analytics",
         "41 Hyde Park Road", "Leeds", "LS6 1AF", "52,000", "2,500", "500", "5,000", "Priya Shah",
         "New hire today. Please prepare Lena Fischer's offer letter from her approval in Inbox.",
         feedback="Perfect, that's exactly it"),
    Hire("t06", 5, "10:05", "Wei", "Zhang", "Backend Engineer", "Platform",
         "19 Mill Road", "Cambridge", "CB1 2AD", "74,000", "5,000", "1,200", "9,000", "Kofi Mensah",
         "Offer letter for the new backend engineer please, the approval PDF has everything.",
         feedback="For this candidate write Zhang Wei, family name first"),
    Hire("t07", 4, "15:40", "Priya", "Raman", "Finance Analyst", "Finance",
         "5 Jesmond Road", "Newcastle", "NE2 1NL", "55,000", "3,000", "400", None, "Owen Price",
         "Can you prepare Priya's offer letter? Her approval is in Inbox.",
         frozenset({PDF_FALLBACK}), "Keep the template formatting. The salary line lost its bold in the PDF"),
    Hire("t08", 3, "09:30", "Jonas", "Berg", "Site Reliability Engineer", "Infrastructure",
         "12 Gloucester Road", "Bristol", "BS7 8AE", "76,000", "5,000", "1,000", "7,500", "Sam Okoro",
         "New hire today. Please prepare Jonas Berg's offer letter from the approval in Inbox. "
         "Keep your reply short.",
         frozenset({COLLAPSED_RUNS}),
         "The deadline line lost its bold and underline. Please keep the template formatting exactly."),
    Hire("t09", 2, "13:12", "Hana", "Sato", "UX Researcher", "Design",
         "30 Clarendon Road", "London", "W11 3AD", "61,000", "3,000", "700", None, "Grace Holt",
         "Offer letter for Hana please, her approval is in Inbox.",
         feedback="Perfect, that's exactly it"),
    Hire("t10", 1, "10:48", "Marco", "Bianchi", "Solutions Engineer", "Sales",
         "2 Deansgate", "Manchester", "M3 2BW", "66,000", "4,000", "900", "3,000", None,
         "Please prepare Marco Bianchi's offer letter from the template and his hiring approval.",
         answer="Rachel Moore"),
    Hire("t11", 0, "09:25", "Olivia", "Grant", "Office Manager", "Operations",
         "9 Grove Lane", "London", "SE5 8SY", "46,000", "0", "400", None, "Nadia Wells",
         "New hire today. Please prepare Olivia Grant's offer letter from her approval in Inbox.",
         frozenset({ZERO_ROWS}),
         "There's a '£0' sign-on bonus line. If there's no bonus, just leave the line out."),
    Hire("t12", 0, "11:40", "Yusuf", "Demir", "Data Scientist", "Applied ML",
         "16 Bath Street", "Glasgow", "G2 4JR", "71,000", "3,000", "0", "6,000", "Ines Duarte",
         "Offer letter for Yusuf please, the approval is in Inbox.",
         frozenset({ZERO_ROWS}),
         "Same thing with equity. '0 shares' looks odd, drop the line when there's none."),
    Hire("t13", 0, "14:55", "Chloé", "Martin", "Marketing Lead", "Marketing",
         "22 Princess Street", "Manchester", "M1 4LG", "69,000", "4,000", "800", "5,500", "Claire Lambert",
         "Can you do the offer letter for today's new hire? The signed approval is in Inbox.",
         feedback="Perfect, that's exactly it"),
]

# The approval waiting in Inbox for the live chat at the booth. No bonus and
# no equity, so a letter written under the prepared AGENTS.md prints the zero
# rows that the prepared run turns into a rule.
LIVE_HIRE = Hire("live", 0, "16:30", "Amara", "Osei", "Customer Success Manager", "Customer Success",
                 "11 Harborne Road", "Birmingham", "B15 3BU", "52,000", "0", "0", None, "Ellen Ward", "")

# Ben Harris joined before the coordinator used an agent. His letter in
# Archive shows the house style, and the agent copies his manager in t04.
ARCHIVE_HIRE = Hire("archive", 0, "09:00", "Ben", "Harris", "Account Executive", "Sales",
                    "4 Oxford Road", "Manchester", "M1 5QA", "56,000", "3,000", "500", None, "Rachel Moore", "")


# --------------------------------------------------------------------------- #
# Calendar, counted in working days back from the last prepared day
# --------------------------------------------------------------------------- #


def previous_workday(day: dt.date) -> dt.date:
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def workdays_back(end: dt.date, n: int) -> dt.date:
    for _ in range(n):
        end = previous_workday(end)
    return end


def last_prepared_day(today: dt.date) -> dt.date:
    """The prepared history ends on the working day before today, so every
    prepared session lies in the past whatever time the booth opens."""
    return previous_workday(today)


@dataclass(frozen=True)
class HireDates:
    letter: dt.date
    approved: dt.date
    start: dt.date
    deadline: dt.date


def hire_dates(h: Hire, end: dt.date) -> HireDates:
    letter = workdays_back(end, h.workday)
    start = letter + dt.timedelta(days=28)
    start += dt.timedelta(days=(7 - start.weekday()) % 7)  # first Monday on or after
    return HireDates(letter, previous_workday(letter), start, letter + dt.timedelta(days=7))


def local_ms(day: dt.date, hhmm: str) -> int:
    hh, mm = (int(x) for x in hhmm.split(":"))
    return int(dt.datetime.combine(day, dt.time(hh, mm)).astimezone().timestamp() * 1000)


def approval_ref(n: int, year: int) -> str:
    return f"HA-{year}-{214 + n:04d}"


def uk_date(d: dt.date) -> str:
    return f"{d.day} {d:%B} {d.year}"


def us_date(d: dt.date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def output_stem(h: Hire) -> str:
    return f"Offer_Letter_{h.first}_{h.last}" if OLD_NAMES in h.flaws else f"Offer_{h.last}_{h.first}"
