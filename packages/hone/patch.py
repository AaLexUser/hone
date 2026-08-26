"""Verify and atomically apply MAJICS text replacements to AGENTS.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PatchError(Exception):
    """One rejected edit, with feedback suitable for the next proposal attempt."""


@dataclass
class Change:
    """A verified edit in the shape the run page renders."""

    op: str
    section: str
    line: int
    before: str | None = None
    after: str | None = None
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    anchor: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "section": self.section,
            "line": self.line,
            "before": self.before,
            "after": self.after,
            "rationale": self.rationale,
            "evidence": self.evidence,
        }


def verify_commit_message(result: dict[str, Any]) -> tuple[str, str]:
    """The MAJICS judge authors its own commit message: verify title and body.

    The title stays under 72 chars; the body explains the changes and their
    reasons. Raise PatchError otherwise.
    """
    commit = result.get("commit")
    if not isinstance(commit, dict):
        raise PatchError("commit message missing — provide a commit object with title and body")
    title = commit.get("title")
    if not isinstance(title, str) or not title.strip():
        raise PatchError("commit.title missing — a short summary line is required")
    title = title.strip().rstrip()
    if len(title) > 72:
        raise PatchError(f"commit.title is {len(title)} characters — keep it at 72 or fewer")
    body = commit.get("body")
    if not isinstance(body, str) or not body.strip():
        raise PatchError("commit.body missing — explain the changes and their reasons")
    return title, body.strip()


def _section_at(lines: list[str], idx: int) -> str:
    for j in range(idx, -1, -1):
        if lines[j].startswith("## "):
            return lines[j][3:].strip()
    return "top level"


def apply_proposal_edits(
    edits: list[Any],
    base_file: list[str],
    batch_trace_ids: list[str],
) -> tuple[list[Change], list[str]]:
    """Validate and atomically apply the one active MAJICS proposal format."""
    if not isinstance(edits, list):
        raise PatchError("edits must be a JSON array")
    if len(edits) > 5:
        raise PatchError("too many edits — keep it minimal (max 5)")
    original = "\n".join(base_file)
    working = original
    changes: list[Change] = []
    for i, e in enumerate(edits):
        if not isinstance(e, dict):
            raise PatchError(f"edit {i + 1} is not an object")
        rationale = e.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise PatchError(f"edit {i + 1}: rationale missing")
        evidence = e.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise PatchError(f"edit {i + 1}: evidence is empty")
        bad = [x for x in evidence if x not in batch_trace_ids]
        if bad:
            raise PatchError(f"edit {i + 1}: evidence {bad} not in the frozen batch")
        old_text = e.get("oldText")
        new_text = e.get("newText")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise PatchError(f"edit {i + 1}: oldText and newText must be strings")
        if not old_text and not new_text:
            raise PatchError(f"edit {i + 1}: oldText and newText cannot both be empty")
        if old_text == new_text:
            raise PatchError(f"edit {i + 1}: oldText and newText are identical")

        if old_text:
            matches = working.count(old_text)
            if matches == 0:
                raise PatchError(f"edit {i + 1}: oldText not found in the current AGENTS.md")
            if matches > 1:
                raise PatchError(f"edit {i + 1}: oldText matched {matches} places")
            char_index = working.index(old_text)
            line = working[:char_index].count("\n") + 1
            section = _section_at(working.splitlines(), line - 1)
            working = working.replace(old_text, new_text, 1)
        else:
            line = len(working.splitlines()) + 1
            section = _section_at(working.splitlines(), max(0, line - 2))
            working = working + ("\n" if working else "") + new_text

        inserted_after_anchor = bool(old_text and new_text.startswith(old_text + "\n"))
        if not old_text or inserted_after_anchor:
            op = "insert"
            shown_before = None
            shown_after = (
                new_text[len(old_text) + 1:] if inserted_after_anchor else new_text
            )
            if inserted_after_anchor:
                line += old_text.count("\n") + 1
        elif new_text == "":
            op = "delete"
            shown_before = old_text
            shown_after = None
        else:
            op = "update"
            shown_before = old_text
            shown_after = new_text
        changes.append(
            Change(
                op,
                section,
                line,
                before=shown_before,
                after=shown_after,
                rationale=rationale,
                evidence=list(evidence),
                anchor=old_text or None,
            )
        )
    new_file = working.splitlines()
    return ([], base_file) if working == original else (changes, new_file)


def diff_stats(a: list[str], b: list[str]) -> tuple[int, int]:
    import difflib

    sm = difflib.SequenceMatcher(a=a, b=b)
    adds = dels = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            adds += j2 - j1
        if tag in ("delete", "replace"):
            dels += i2 - i1
    return adds, dels
