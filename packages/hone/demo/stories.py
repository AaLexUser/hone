"""What each prepared run finds, proposes and argues about.

`@tNN` in any text names a hire's trace and is resolved to its trace id when
the run plays. Three runs make the history (two commits and one run that
changes nothing). `live` is the run the booth replays over the last batch.
"""

from __future__ import annotations

from dataclasses import dataclass

DATE_RULE = ("- Write every date in the letter as day month year, for example `1 December 2026`, with no "
             "weekday and no leading zero. This covers the letter date, the start date and the response "
             "deadline.")
BLOCK_RULE = ("- When a conditional block such as `{{IF_RELOCATION}}…{{END_IF_RELOCATION}}` does not apply, "
              "delete the whole paragraph and the heading above it. Never leave an empty paragraph or a "
              "heading with nothing under it.")
PDF_RULE = ("- Save every letter as both `.docx` and `.pdf`, named `Offer_<Lastname>_<Firstname>` "
            "(for example `Offer_Chen_Sarah.pdf`).")
ASK_RULE = ("- If the hiring approval leaves a field the letter needs empty (for example Reports to), ask "
            "the user for it before writing the letter. Never copy it from older letters or invent it.")
PDF_RULE_V2 = ("- Save every letter as `.docx`, then convert that file with `soffice --headless "
               "--convert-to pdf` so the PDF matches it exactly. Never retype the letter into a PDF. Name "
               "both `Offer_<Lastname>_<Firstname>` (for example `Offer_Chen_Sarah.pdf`).")
FORMAT_RULE = ("- Fill placeholders run by run so the template formatting survives. The base salary stays "
               "bold and the response deadline stays bold and underlined. Reopen the saved file and check "
               "both before replying.")
BLOCK_RULE_V3 = ("- When a block or line does not apply, delete it with its label. That covers a conditional "
                 "block such as `{{IF_RELOCATION}}…{{END_IF_RELOCATION}}` that is off, and a details row "
                 "whose amount is 0 (the sign-on bonus or the equity grant). Never leave `£0`, `0 shares`, "
                 "an empty paragraph or a heading with nothing under it.")

US_DATE_PROBE = (r"(January|February|March|April|May|June|July|August|September|October|November|December) "
                 r"[0-9]{1,2}, 20[0-9]{2}")


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
    texts: tuple[str, ...]   # phrasings, the first is the judged statement
    traces: tuple[str, ...]
    confidence: str
    probe: str


@dataclass(frozen=True)
class Ask:
    """One ask_panel query. `seat` indexes the panel and wraps."""
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
         "The user asked for `1 December 2026` style dates 'as all our letters do', and the letter in Archive "
         "uses them. Every letter in the batch wrote month first dates because no convention was written down.",
         ("t01", "t02", "t03", "t04")),
    Edit("", BLOCK_RULE,
         "With relocation set to No the agent cleared only the block's text and kept the heading over an "
         "empty paragraph, which the user called a big empty gap.", ("t02",)),
    Edit("", PDF_RULE,
         "No session produced a PDF and files were named Offer_Letter_First_Last. The user wants a PDF too, "
         "named Offer_Lastname_Firstname like the letters in Archive.", ("t03",)),
    Edit("", ASK_RULE,
         "The approval left Reports to empty and the agent copied the manager from an older letter. The user "
         "wants to be asked instead.", ("t04",)),
), "Four explicit preferences from the HR user had no rule in the empty AGENTS.md.")

R2_FINAL = Proposal((
    Edit(PDF_RULE, PDF_RULE_V2,
         "The PDF lost the bold salary line because it was retyped with reportlab after docx2pdf failed. "
         "Converting the filled .docx keeps both files identical.", ("t07",)),
    Edit(DATE_RULE, DATE_RULE + "\n" + FORMAT_RULE,
         "The fill script collapsed runs and dropped the deadline's bold and underline. The user asked to keep "
         "the template formatting exactly.", ("t07", "t08")),
), "Both formatting losses come from how the letter is written, not from the existing rules.")

LIVE_FINAL = Proposal((
    Edit(BLOCK_RULE, BLOCK_RULE_V3,
         "Rows with a zero amount are the same 'does not apply' case as an off relocation block, and both "
         "feedbacks ask for the line to be dropped.", ("t11", "t12")),
), "Zero value bonus and equity rows are the same gap as the relocation block.")

STORIES: dict[str, Story] = {
    "r1": Story(
        key="r1",
        batch=("t01", "t02", "t03", "t04"),
        summary="Four offer letter sessions carry explicit feedback that maps to four separate, repeatable "
                "preference gaps. They are the date format, empty conditional blocks, the missing PDF with its "
                "naming convention, and a manager guessed when the approval left it empty. AGENTS.md is empty, "
                "so none of these preferences were available to the agent.",
        verdicts=(
            "Four actionable preference gaps, each backed by explicit feedback. AGENTS.md has no rules yet.",
            "Strong batch. Every trace has feedback and each names a concrete, reusable preference.",
            "Actionable. The date format repeats in all four traces, the other three gaps have one trace each.",
        ),
        findings=(
            Finding("INSTRUCTION_CONFLICT", (
                ("All four letters write dates month first (`October 19, 2026`). @t01's feedback asks for "
                "`1 December 2026` 'as all our letters do', which matches the letter in Archive. @t02, @t03 and "
                "@t04 repeat the format with no feedback on dates."),
                ("The letter date, start date and deadline are rendered US style in @t01, @t02, @t03 and @t04. "
                "Only @t01 carries date feedback."),
            ), ("t01", "t02", "t03", "t04"), "high", US_DATE_PROBE),
            Finding("STATE_MISMATCH", (
                ("The approval in @t02 says Relocation package No. The fill script cleared the block's runs but "
                "kept the 'Relocation Assistance:' heading over an empty paragraph. The feedback says 'There's "
                "a big empty gap where the relocation part was'."),
                ("@t02's check prints 'Relocation Assistance:' followed by two blank lines, and the user calls "
                "it a big empty gap."),
            ), ("t02",), "high", "Relocation Assistance|IF_RELOCATION"),
            Finding("INSTRUCTION_CONFLICT", (
                ("No session writes a PDF and every output is named `Offer_Letter_<First>_<Last>.docx`. @t03's "
                "feedback asks for a PDF too, named Offer_Lastname_Firstname like the letters in Archive."),
                ("Only .docx files are produced (@t01 to @t04). @t03's feedback asks for a PDF and the "
                "Offer_Lastname_Firstname name."),
            ), ("t01", "t02", "t03", "t04"), "high", r"\.pdf|Offer_Letter_[A-Za-z]+"),
            Finding("UNSUPPORTED_CLAIM", (
                ("Daniel Novak's approval in @t04 leaves Reports to empty. The agent copied 'Rachel Moore' from "
                "`Archive/Offer_Harris_Ben.docx` into the letter. The feedback says 'Don't make up the manager, "
                "ask me'."),
                ("Data unavailable, then a guess. @t04 fills Reports To from an older Sales letter instead of "
                "asking."),
            ), ("t04",), "high", "Reports to|Rachel Moore|Offer_Harris_Ben"),
        ),
        hypotheses=(
            (("With no written date convention the agent falls back to US style. One explicit rule with the "
             "example `1 December 2026` should fix all three dates."), ("t01", "t02", "t03", "t04"), "high", ()),
            (("When the approval leaves a field empty the agent fills it from older letters in the folder. An "
             "'ask the user' rule should stop it."), ("t04",), "medium",
             ("Only one session in the batch had an empty field.",)),
            ("Collapsing runs in the fill script can drop bold and underline from the template.", ("t02",), "low",
             ("No feedback in this batch mentions formatting.",
              "@t01 used a run aware script and kept the bold deadline.")),
        ),
        directions=(
            "Add an Offer letters section with the date format `1 December 2026`.",
            "Delete conditional blocks that do not apply together with their heading.",
            "Save .docx and .pdf, named Offer_<Lastname>_<Firstname>.",
            "Ask the user for fields the approval leaves empty instead of inferring them.",
        ),
        unresolved=(
            ("Whether formatting loss from run collapsing matters to the user. It is visible in @t02's file but "
            "never mentioned in feedback."),
            "Whether the US dates in @t02 to @t04 were acceptable. Only @t01 carries date feedback.",
        ),
        waste=(
            ("@t02 dumped every run of the template to find split placeholders. One regex over "
            "`word/document.xml` was enough."),
            "@t04 opened an older letter to guess a field instead of asking.",
            "Every trace dumps the template again although it never changes between sessions.",
        ),
        weak_claim="The fill script in @t02 writes each paragraph's text into its first run, which would drop the "
                   "bold and underline on the response deadline. Confidence: low.",
        review_asks=(
            Ask(1, "You flagged run collapsing in @t02's fill script. Is the formatting loss visible in the saved "
                   "letter, and does any feedback in the batch mention it?",
                "The code collapses runs, so the deadline paragraph in @t02's output is one unformatted run. No "
                "feedback in this batch mentions formatting, and @t01 used a run aware script that kept the bold. "
                "Keep it as a low confidence hypothesis, not a finding."),
            Ask(2, "Falsify this. Is the invented manager in @t04 an instruction gap or a data problem? Check "
                   "whether the agent knew the field was empty before it filled the letter.",
                "It knew. The thinking before the fill says Reports to is empty on the approval and that it will "
                "reuse the manager from Ben Harris's letter in Archive. The data was missing, the guess was the "
                "agent's choice, so an instruction to ask for empty fields addresses it."),
        ),
        proposals=(
            R1_FINAL,
            Proposal(R1_FINAL.edits + (Edit("", "- Keep the template's bold and underline when filling "
                                                "placeholders.", "Run collapsing in the fill script drops "
                                                "template formatting.", ("t02",)),),
                     "Four explicit preferences plus run preserving fills."),
            Proposal((Edit("# AGENTS.md", "# AGENTS.md\n\n## Offer letters\n\n" + "\n".join(
                [DATE_RULE, BLOCK_RULE, PDF_RULE, ASK_RULE]),
                "One section with the four rules the feedback asks for.", ("t01", "t02", "t03", "t04")),),
                "One section with the four rules the feedback asks for."),
        ),
        final=R1_FINAL,
        commit_title="feat: add offer letter rules for dates, gaps, PDF and missing data",
        commit_body="Adds an Offer letters section to AGENTS.md. Dates are written as 1 December 2026, "
                    "conditional blocks that do not apply are removed with their heading, every letter is "
                    "saved as .docx and .pdf named Offer_<Lastname>_<Firstname>, and a field the approval "
                    "leaves empty, such as the manager, is asked for instead of guessed.",
        propose_asks=(
            Ask(1, "Your fifth edit adds a formatting rule. Which trace has feedback that supports it?",
                "None does. @t02 shows collapsed runs in the file, but the user never mentioned formatting. Drop "
                "it until feedback confirms it."),
            Ask(2, "You merged four signals into one edit. Would splitting them into one edit per rule change any "
                   "wording?",
                "No. The bullets are identical, and splitting gives each rule its own evidence. Use the split "
                "version."),
        ),
    ),
    "r2": Story(
        key="r2",
        batch=("t05", "t06", "t07", "t08"),
        summary="The offer letter rules held in all four sessions. Dates are day month year, both files are "
                "named Offer_<Lastname>_<Firstname>, and no empty relocation block remains. The remaining defect "
                "is lost formatting, once in the PDF path (a reportlab retype after docx2pdf failed) and once in "
                "the DOCX fill (runs collapsed). One name order request is explicitly scoped to one candidate.",
        verdicts=(
            "Rules from the last run hold. Lost formatting is the one new, repeated signal.",
            "Two formatting complaints with two different mechanisms, and one scoped one off request.",
            "Actionable for formatting only. The name order request is not a standing preference.",
        ),
        findings=(
            Finding(None, (
                ("All four letters follow the current rules. Dates read `26 October 2026`, `.docx` and `.pdf` are "
                "named `Offer_<Lastname>_<Firstname>`, and @t07 removed the relocation heading with its block. "
                "@t05's feedback says 'Perfect, that's exactly it'."),
                "The v1 rules are followed in @t05, @t06, @t07 and @t08, and @t05 is explicitly approved.",
            ), ("t05", "t06", "t07", "t08"), "high", r"[0-9]{1,2} (October|November|December) 20[0-9]{2}|Offer_[A-Z]"),
            Finding("TOOL_ERROR", (
                ("In @t07 `docx2pdf` was not installed (exit 1). The agent rebuilt the PDF with reportlab from "
                "plain paragraph text, so the PDF lost the bold salary line. The feedback says 'Keep the template "
                "formatting. The salary line lost its bold in the PDF'."),
                ("@t07 hit a docx2pdf import error, then retyped the letter with reportlab. The feedback reports "
                "the lost bold salary."),
            ), ("t07",), "high", "docx2pdf|reportlab|drawString"),
            Finding("STATE_MISMATCH", (
                ("@t08's fill script writes each paragraph's text into its first run, so the saved `.docx` has the "
                "response deadline without bold or underline. The feedback says 'The deadline line lost its bold "
                "and underline. Please keep the template formatting exactly.'"),
                ("@t08 collapses runs (`p.runs[0].text = text`), the deadline formatting is gone and the user says "
                "so."),
            ), ("t08",), "high", r"runs\[0\]|runs\[1:\]"),
            Finding(None, (
                ("@t06's only feedback is scoped to one candidate, 'For this candidate write Zhang Wei, family "
                "name first'. The approval form has a single Name field and no name order."),
                ("@t06 asks for family name first 'for this candidate', and nothing on the approval marks name "
                "order."),
            ), ("t06",), "medium", "Zhang|CANDIDATE_FULL_NAME"),
        ),
        hypotheses=(
            (("Converting the filled `.docx` with LibreOffice instead of retyping it would keep the PDF identical "
             "to the DOCX."), ("t07",), "high", ()),
            (("Replacing placeholders run by run keeps the template's bold and underline. The low confidence "
             "formatting hypothesis from the previous run is now confirmed by feedback."), ("t08",), "high", ()),
            ("Family name first should apply to every Chinese name.", ("t06",), "low",
             ("The feedback says 'For this candidate'.", "The approval form has no name order field.")),
        ),
        directions=(
            "Convert the PDF from the filled .docx (`soffice --headless --convert-to pdf`), never retype it.",
            "Fill placeholders per run and check that the salary and deadline keep their formatting.",
            "Keep the existing date, naming, missing field and conditional block rules unchanged.",
        ),
        unresolved=("Whether family name first should ever be a rule. There is one scoped request so far.",),
        waste=(
            ("@t07 tried docx2pdf, then wrote a reportlab script, although `soffice` was available and used in "
            "@t05."),
            "@t06 and @t08 dump the template again before every fill.",
        ),
        weak_claim="Chinese names should be written family name first in every letter (@t06). Confidence: low.",
        review_asks=(
            Ask(1, "You propose family name first for all Chinese names. Defend it from @t06 alone, or concede.",
                "Concede. The feedback says 'For this candidate', and nothing on the approval marks name order. It "
                "is a one off correction, not a standing rule."),
            Ask(0, "Falsify the claim that the formatting losses in @t07 and @t08 share one cause.",
                "They do not share one cause. @t07 lost bold in the PDF because reportlab retyped the text after "
                "docx2pdf failed, and its .docx kept the bold. @t08 lost formatting in the .docx itself because the "
                "fill script collapsed runs. Two mechanisms, one user preference."),
        ),
        proposals=(
            R2_FINAL,
            Proposal(R2_FINAL.edits + (Edit(ASK_RULE, ASK_RULE + "\n- Write Chinese candidates' names family name "
                                            "first, for example `Zhang Wei`.",
                                            "The user corrected the name order for a Chinese candidate.", ("t06",)),),
                     "Formatting fixes plus the name order preference."),
            Proposal((R2_FINAL.edits[1],), "Formatting fix only. The PDF failure is a tool problem."),
        ),
        final=R2_FINAL,
        commit_title="fix: keep template formatting in offer letter DOCX and PDF",
        commit_body="Offer letters now fill placeholders run by run so bold and underline from the template "
                    "survive, and the PDF is converted from the filled .docx with LibreOffice instead of being "
                    "retyped, so both files match. The one off family name first request stays out of AGENTS.md "
                    "because it applied to a single candidate.",
        propose_asks=(
            Ask(1, "Your third edit makes family name first a rule for all Chinese names. The feedback in @t06 "
                   "says 'For this candidate'. Defend or drop it.",
                "Drop it. The feedback is scoped to one candidate and nothing in the approval marks name order. "
                "It stays out of AGENTS.md."),
            Ask(2, "You left the PDF path alone as a tool problem. @t07's PDF lost bold only because it was "
                   "retyped. Is a conversion rule an instruction fix?",
                "Yes. docx2pdf was missing, but retyping the text was the agent's choice. Converting the filled "
                ".docx with soffice is an instruction it can follow, so add it."),
        ),
    ),
    "r3": Story(
        key="r3",
        batch=("t09", "t10"),
        summary="Both sessions follow every current offer letter rule. @t10 asked for the missing manager instead "
                "of guessing, and the only feedback in the batch is positive. No new failure mode appears.",
        verdicts=(
            "No actionable signal. Both letters follow the current rules.",
            "Nothing to change. One approved session, one without feedback.",
        ),
        findings=(
            Finding(None, (
                ("@t09 and @t10 follow every current rule. Dates are day month year, placeholders are filled run "
                "by run, the PDF is converted from the DOCX, and both are named `Offer_<Lastname>_<Firstname>`. "
                "@t10 asked for the missing manager instead of guessing. @t09's feedback says 'Perfect, that's "
                "exactly it'."),
                "Current rules are followed in @t09 and @t10, including the ask for empty fields rule in @t10.",
            ), ("t09", "t10"), "high", "Reports to|soffice|Offer_[A-Z]"),
            Finding("OUTCOME_UNKNOWN", (
                "@t10 has no feedback. The letter is consistent with the rules, but its outcome is unknown.",
                "@t10 is OUTCOME_UNKNOWN, with no feedback attached.",
            ), ("t10",), "medium", "Reports To"),
        ),
        hypotheses=(
            ("The current rules cover the observed preferences, and no new failure mode appears in this batch.",
             ("t09", "t10"), "medium", ("Two sessions are a small sample.",)),
        ),
        directions=(),
        unresolved=("@t10's outcome, which has no feedback.",),
        waste=("Both sessions dump the template before filling, which is harmless.",),
        weak_claim=None,
        review_asks=(),
        proposals=(Proposal((), "No defensible signal. Both sessions follow the current rules."),),
        final=Proposal((), "No new signal. Both letters followed the current rules."),
        commit_title="chore: keep AGENTS.md unchanged for this batch",
        commit_body="Both sessions followed the current offer letter rules and the only feedback was positive, "
                    "so there is nothing to change.",
        propose_asks=(),
    ),
    "live": Story(
        key="live",
        batch=("t11", "t12", "t13"),
        summary="Dates, file names, PDF conversion and formatting follow the current rules in the prepared "
                "sessions. Two letters print rows whose amount is zero ('Sign-on Bonus: £0' and 'Equity Grant: "
                "0 shares'), and both carry feedback asking for the row to be dropped. The existing conditional "
                "block rule covers only `{{IF_…}}` blocks.",
        verdicts=(
            "One repeated signal. Zero value rows should disappear like an off conditional block.",
            "Actionable. Two traces, two feedbacks, same mechanism.",
            "The current rules hold. Widen the conditional block rule to zero amounts.",
        ),
        findings=(
            Finding("STATE_MISMATCH", (
                ("@t11's letter prints 'Sign-on Bonus: £0' because the approval lists the bonus as £0. The "
                "feedback says 'If there's no bonus, just leave the line out.'"),
                "@t11 fills the bonus row with £0, and the user wants the row gone.",
            ), ("t11",), "high", "£0|SIGNING_BONUS"),
            Finding("STATE_MISMATCH", (
                ("@t12 prints 'Equity Grant: 0 shares'. The feedback says 'Same thing with equity. '0 shares' "
                "looks odd, drop the line when there's none.'"),
                "@t12 keeps a 0 shares equity row, and the feedback asks to drop it.",
            ), ("t12",), "high", "0 shares|EQUITY_SHARES"),
            Finding(None, (
                ("Dates, names, PDF conversion and run by run formatting follow the current rules in @t11, @t12 "
                "and @t13. @t13's feedback says 'Perfect, that's exactly it'."),
                "Current rules are followed in @t11 to @t13, and @t13 is approved.",
            ), ("t11", "t12", "t13"), "high", "soffice|Offer_[A-Z]"),
        ),
        hypotheses=(
            (("Widening the conditional block rule to rows with a zero amount removes both lines without adding a "
             "new rule."), ("t11", "t12"), "high", ()),
            ("The agent should ask before dropping any line.", ("t11",), "low",
             ("Both feedbacks ask for the line to be dropped outright.",)),
        ),
        directions=("Widen the conditional block rule to details rows whose amount is 0 (bonus, equity).",),
        unresolved=(),
        waste=("@t12 printed the full letter twice while checking formatting.",
               "@t11 dumped the template again although it was unchanged."),
        weak_claim="The agent should ask before leaving any template line out (@t11). Confidence: low.",
        review_asks=(
            Ask(1, "You suggest asking before dropping lines. Does any feedback ask to be consulted?",
                "No. Both @t11 and @t12 ask for the line to be dropped outright. Asking would add a turn the user "
                "did not want, so I withdraw it."),
            Ask(0, "Falsify this. Is the zero value problem the same mechanism as the old empty relocation block?",
                "Same mechanism, different trigger. The relocation rule covers `{{IF_…}}` blocks only. The bonus "
                "and equity rows are plain table rows, so the agent filled them with 0. Widening the existing "
                "rule covers both."),
        ),
        proposals=(
            LIVE_FINAL,
            Proposal((Edit("", "- Leave out the Sign-on Bonus and Equity Grant rows when their value is 0.",
                           "Both zero value rows drew feedback.", ("t11", "t12")),),
                     "A separate rule for zero value rows."),
            Proposal((Edit("", "- Before leaving any template line out, ask the user.",
                           "Dropping lines silently surprised the user.", ("t11",)),),
                     "Ask before removing template content."),
        ),
        final=LIVE_FINAL,
        commit_title="fix: drop zero value bonus and equity lines from offer letters",
        commit_body="The rule for blocks that do not apply now also covers amounts of 0, so letters leave out the "
                    "sign-on bonus or equity row instead of printing £0 or 0 shares. Dates, file names and "
                    "formatting rules are unchanged.",
        propose_asks=(
            Ask(1, "You add a separate zero value rule next to the conditional block rule. Would widening the "
                   "existing rule say the same thing with one bullet?",
                "Yes. One rule for 'does not apply' is clearer than two that overlap. Widen the existing bullet."),
            Ask(2, "Your edit asks before removing lines. Which feedback supports asking?",
                "None. Both say to drop the line. I withdraw it."),
        ),
    ),
}

# When each prepared run starts, as (story, working days before the last
# prepared day, local time, trigger).
RUNS = [("r1", 7, "17:35", "manual"), ("r2", 3, "09:41", "auto"), ("r3", 1, "16:20", "manual")]
