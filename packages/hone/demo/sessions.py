"""Prepared chats as Pi session JSONL, written while their commands run for real."""

from __future__ import annotations

import datetime as dt
import json
import random
from typing import Any

from .office import (
    DUMP_TEMPLATE,
    Workspace,
    check_formatting,
    dump_details,
    fill_script,
    letter_values,
    print_letter,
    retype_pdf_script,
)
from .scenario import (
    ARCHIVE_HIRE,
    ARCHIVE_LETTER,
    COLLAPSED_RUNS,
    INVENTED_MANAGER,
    NO_PDF,
    PDF_FALLBACK,
    RELOC_GAP,
    US_DATES,
    WORKSPACE,
    Hire,
    approval_ref,
    hire_dates,
    output_stem,
)

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


def iso(ms: int) -> str:
    stamp = dt.datetime.fromtimestamp(ms / 1000, dt.UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def uuid7(ms: int, rng: random.Random) -> str:
    tail = rng.getrandbits(74)
    hexed = f"{ms:012x}"
    a = (tail >> 62) & 0xFFF
    b = 0x8000 | ((tail >> 48) & 0x3FFF)
    c = tail & ((1 << 48) - 1)
    return f"{hexed[:8]}-{hexed[8:]}-7{a:03x}-{b:04x}-{c:012x}"


class PiSession:
    """Pi's session JSONL, a header and then a parent linked entry chain."""

    def __init__(self, rng: random.Random, session_id: str, start_ms: int, day: dt.date, title: str,
                 agents_md: str, model: str) -> None:
        self.rng = rng
        self.day = day
        self.t = start_ms
        self.parent: str | None = None
        self.cache = 14_336
        self.provider, _, self.model = model.partition("/")
        self.entries: list[dict[str, Any]] = [
            {"type": "session", "version": 3, "id": session_id, "timestamp": iso(self.t), "cwd": WORKSPACE},
        ]
        self._node("model_change", provider=self.provider, modelId=self.model)
        self._node("thinking_level_change", thinkingLevel="medium")
        self.t += rng.randint(90, 180)
        self._node("session_info", name=title[:50] + "...")
        context = (
            "<project_context>\nProject-specific instructions and guidelines:\n\n"
            f'<project_instructions path="{WORKSPACE}/AGENTS.md">\n{agents_md}\n</project_instructions>\n'
            "</project_context>"
        )
        self._message({
            "role": "system", "content": "",
            "sections": {**SYSTEM_SECTIONS, "project_context": context, "cwd": f"<cwd>\n{WORKSPACE}\n</cwd>"},
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

    def assistant(self, *, thinking: str | None = None, calls: list[tuple[str, dict]] | None = None,
                  text: str | None = None) -> list[str]:
        rng = self.rng
        calls = calls or []
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
            "role": "assistant", "content": content, "api": "openai-completions", "provider": self.provider,
            "model": self.model, "usage": usage, "stopReason": "toolUse" if calls else "stop",
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

    def bash(self, ws: Workspace, command: str, *, thinking: str | None = None,
             ms: tuple[int, int] = (40, 420)) -> str:
        """One bash call, run for real in the workspace."""
        [call] = self.assistant(thinking=thinking, calls=[("bash", {"command": command, "timeout": None})])
        output, failed = ws.bash(command, self.day)
        self.result(call, "bash", output, error=failed, ms=self.rng.randint(*ms))
        return output

    def write(self, ws: Workspace, name: str, content: str, *, thinking: str | None = None) -> None:
        [call] = self.assistant(thinking=thinking, calls=[("write", {"path": f"/tmp/{name}", "content": content})])
        size = ws.write_tmp(name, content)
        self.result(call, "write", f"Successfully wrote {size} bytes to /tmp/{name}", ms=self.rng.randint(2, 6))

    def body(self) -> bytes:
        return ("\n".join(json.dumps(e, ensure_ascii=False) for e in self.entries) + "\n").encode("utf-8")


def offer_session(h: Hire, n: int, session_id: str, start_ms: int, agents_md: str, ws: Workspace,
                  end: dt.date, model: str, rng: random.Random) -> PiSession:
    """One working session. Read the approval, fill the template, export, check."""
    dates = hire_dates(h, end)
    s = PiSession(rng, session_id, start_ms, dates.letter, h.ask, agents_md, model)
    s.user(h.ask)
    rules = "## Offer letters" in agents_md
    run_by_run = "run by run" in agents_md
    stem = output_stem(h)
    docx, pdf = f"{stem}.docx", f"{stem}.pdf"

    s.bash(ws, "ls -R", thinking="Let me look at the project folder first.")
    s.bash(ws, f'pdftotext -layout "{h.approval}" -', ms=(60, 180),
           thinking="The approval is a PDF. Extract its text with the layout kept.")
    s.bash(ws, DUMP_TEMPLATE, ms=(180, 420),
           thinking="Dump the template so I can see every placeholder, including the nested tables, the header "
                    "and the footer.")

    manager, note = h.manager or "", None
    if h.manager is None and INVENTED_MANAGER in h.flaws:
        s.bash(ws, dump_details(ARCHIVE_LETTER), ms=(180, 420),
               thinking="Reports to is empty on the approval. Archive has an earlier Sales offer, Ben Harris's. "
                        "Reuse the manager from that letter.")
        manager, note = ARCHIVE_HIRE.manager or "", "not on the approval, same as Ben Harris's letter"
    elif h.manager is None:
        s.assistant(text=f"The approval for {h.name} leaves **Reports to** empty. Who will {h.first} report to?")
        manager = h.answer or ""
        s.user(manager, delay_ms=rng.randint(40_000, 95_000))

    script = fill_script(letter_values(h, approval_ref(n, dates.letter.year), dates.start, manager, note),
                         out=docx, relocation=bool(h.relocation), us_dates=US_DATES in h.flaws,
                         collapse=COLLAPSED_RUNS in h.flaws, delete_blocks=rules)
    thinking = ("The placeholders are split across runs and the details sit in nested tables. Fill every "
                "paragraph, the header and the footer, and handle the conditional relocation block.")
    if rules:
        thinking = (f"Follow AGENTS.md. Day month year dates, drop blocks that do not apply, save as {docx} "
                    "and convert it to PDF.")
    if run_by_run:
        thinking += " Fill run by run so the template formatting survives, then check it."
    s.write(ws, "fill_offer.py", script, thinking=thinking)
    s.bash(ws, "python3 /tmp/fill_offer.py", ms=(300, 700))

    if PDF_FALLBACK in h.flaws:
        s.bash(ws, f"python3 -c \"from docx2pdf import convert; convert('{docx}')\"", ms=(60, 120))
        s.write(ws, "make_pdf.py", retype_pdf_script(docx, pdf),
                thinking="docx2pdf is not installed, but reportlab is. Draw the letter text into a PDF.")
        s.bash(ws, "python3 /tmp/make_pdf.py", ms=(400, 900))
    elif NO_PDF not in h.flaws:
        s.bash(ws, f"soffice --headless --convert-to pdf {docx}", ms=(2600, 4800))

    s.bash(ws, print_letter(docx), ms=(200, 450))
    if run_by_run:
        s.bash(ws, check_formatting(docx), ms=(200, 450))

    files = f"`{docx}`" if NO_PDF in h.flaws else f"`{docx}` and `{pdf}`"
    bullets = ["- All placeholders filled, including the details table, header and footer"]
    if h.relocation:
        bullets.append(f"- Relocation clause included (£{h.relocation}, 30 days)")
    elif RELOC_GAP in h.flaws:
        bullets.append("- The approval says no relocation package, so the relocation text was left out")
    else:
        bullets.append("- Relocation section removed, it does not apply")
    if note:
        bullets.append(f"- Reports to taken from Ben Harris's letter in Archive ({manager})")
    if run_by_run:
        bullets.append("- Formatting checked, the salary and the deadline keep the template styling")
    s.assistant(text=f"Created {files} from the template and {h.first}'s hiring approval.\n\n" + "\n".join(bullets))
    return s
