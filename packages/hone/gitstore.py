"""AGENTS.md lives in a real Git repository: versions are commits, branches are
branches, and "current" is HEAD.

The repo lives at /data/repo with a single tracked file, AGENTS.md. The
optimizer's applied edits land as commits whose messages the MAJICS judge
authored (short title + explanatory body). The SQLite `nodes`
table is only an index for the UI; Git is the source of truth for history.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

TRUNK = "main"
HONE_AUTHOR = ("Hone", "hone@hone.local")
OPTIMIZER_AUTHOR = ("Hone Optimizer", "optimizer@hone.local")

# Branch names Hone generates when an optimizer run forks history.
AUTO_BRANCH_PREFIX = "b"


class GitError(Exception):
    """A git operation failed; str(exc) carries stderr for the UI."""


def valid_branch_name(name: str) -> bool:
    if not name or name.startswith("-") or name != name.strip():
        return False
    check = subprocess.run(
        ["git", "check-ref-format", "--branch", name], capture_output=True
    )
    return check.returncode == 0 and "/" not in name


class GitRepo:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = path / "AGENTS.md"

    # ------------------------------------------------------------- plumbing

    def _run(self, *args: str, stdin: str | None = None, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            input=stdin,
            capture_output=True,
            text=True,
        )
        if check and proc.returncode != 0:
            raise GitError((proc.stderr or proc.stdout).strip())
        return proc.stdout

    def ensure(self) -> None:
        """Init the repo on first boot; idempotent afterwards."""
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            subprocess.run(
                ["git", "init", "-b", TRUNK, str(self.path)],
                capture_output=True,
                text=True,
                check=True,
            )
        self._run("config", "user.name", HONE_AUTHOR[0])
        self._run("config", "user.email", HONE_AUTHOR[1])
        self._run("config", "advice.detachedHead", "false")
        self._run("config", "commit.verbose", "false")

    # --------------------------------------------------------------- state

    def has_commits(self) -> bool:
        return self._run("rev-parse", "--verify", "-q", "HEAD", check=False).strip() != ""

    def short(self, rev: str = "HEAD") -> str:
        return self._run("rev-parse", "--short=7", rev).strip()

    def head_short(self) -> str | None:
        return self.short() if self.has_commits() else None

    def rev_exists(self, rev: str) -> bool:
        return self._run("rev-parse", "--verify", "-q", rev, check=False).strip() != ""

    def full_sha(self, rev: str) -> str:
        return self._run("rev-parse", rev).strip()

    def current_branch(self) -> str | None:
        """Branch HEAD is on, or None when detached at a commit."""
        out = self._run("branch", "--show-current", check=False).strip()
        return out or None

    def is_clean(self) -> bool:
        return self._run("status", "--porcelain").strip() == ""

    def branches(self) -> list[dict[str, str]]:
        """[{name, tip}] for every local branch, newest tip first."""
        out = self._run(
            "for-each-ref",
            "refs/heads",
            "--sort=-committerdate",
            "--format=%(refname:short)%00%(objectname:short=7)",
        )
        return [
            {"name": parts[0], "tip": parts[1]}
            for line in out.splitlines()
            if (parts := line.split("\x00")) and len(parts) == 2
        ]

    def branch_tip(self, name: str) -> str | None:
        for b in self.branches():
            if b["name"] == name:
                return b["tip"]
        return None

    def branches_at(self, sha: str) -> list[str]:
        out = self._run(
            "for-each-ref",
            "refs/heads",
            f"--points-at={sha}",
            "--format=%(refname:short)",
        )
        return [l for l in out.splitlines() if l]

    def file_at(self, rev: str) -> str:
        return self._run("show", f"{rev}:AGENTS.md", check=False)

    # -------------------------------------------------------------- commit

    def commit_worktree(
        self,
        text: str,
        title: str,
        body: str = "",
        trailers: dict[str, str] | None = None,
        author: tuple[str, str] = HONE_AUTHOR,
    ) -> str:
        """Replace AGENTS.md in the working tree and commit on the current branch."""
        self.file.write_text(text, encoding="utf-8")
        self._run("add", "AGENTS.md")
        return self.commit_staged(title, body, trailers, author)

    def commit_staged(
        self,
        title: str,
        body: str = "",
        trailers: dict[str, str] | None = None,
        author: tuple[str, str] = HONE_AUTHOR,
    ) -> str:
        """Commit the staged changes; git refuses when nothing changed — no empty commits."""
        message = _format_message(title, body, trailers)
        self._run(
            "commit",
            f"--author={author[0]} <{author[1]}>",
            "-m",
            message,
        )
        return self.short("HEAD")

    def checkout(self, ref: str) -> None:
        """Move HEAD (branch or detached) and the working tree to ref."""
        self._run("checkout", "--quiet", ref)

    def checkout_branch_or_detach(self, sha: str) -> None:
        """Point HEAD at sha: on its branch when it is the tip, detached otherwise."""
        at = self.branches_at(sha)
        current = self.current_branch()
        self.checkout(current if current in at else (at[0] if at else sha))

    def create_branch(self, name: str, at: str) -> None:
        self._run("branch", name, at)

    def rename_branch(self, old: str, new: str) -> None:
        self._run("branch", "-m", old, new)

    def merge(self, name: str, into: str, author: tuple[str, str] = HONE_AUTHOR) -> str:
        """Merge branch `name` into the current branch; merge commit always."""
        title = f"merge: branch {name} into {into}"
        message = _format_message(
            title, f"Merges the optimized history on {name} into {into}.",
            {"Hone-Branch": into, "Hone-Merge": name},
        )
        proc = subprocess.run(
            ["git", "-C", str(self.path), "merge", "--no-ff", name, "-m", message],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            self._run("merge", "--abort", check=False)
            hint = (proc.stderr or proc.stdout).strip()
            raise GitError(f"merge conflicted in AGENTS.md — nothing was changed. {hint}")
        return self.short("HEAD")

    # ----------------------------------------------------------------- log

    def log_all(self) -> list[dict[str, object]]:
        """Every commit reachable from any branch, oldest first."""
        out = self._run(
            "log", "--all", "--date-order", "--reverse",
            "--pretty=format:%H%x00%h%x00%P%x00%at%x00%B%x1e",
        )
        commits = []
        for record in out.split("\x1e"):
            record = record.strip("\n")
            if not record.strip():
                continue
            parts = record.split("\x00")
            if len(parts) != 5:
                continue
            full, short, parents, at, message = parts
            title, body, trailers = _parse_message(message)
            commits.append(
                {
                    "sha": short,
                    "full": full,
                    "parents": [self.short(p) for p in parents.split()] if parents else [],
                    "at": int(at) * 1000,
                    "title": title,
                    "body": body,
                    "trailers": trailers,
                }
            )
        return commits


def _format_message(
    title: str, body: str = "", trailers: dict[str, str] | None = None
) -> str:
    parts = [title.strip()]
    if body.strip():
        parts.append(body.strip())
    if trailers:
        parts.append("\n".join(f"{k}: {v}" for k, v in trailers.items()))
    return "\n\n".join(parts) + "\n"


def _parse_message(message: str) -> tuple[str, str, dict[str, str]]:
    """Split a commit message into (title, body, hone trailers)."""
    message = message.strip()
    blocks = message.split("\n\n")
    title = blocks[0].strip() if blocks else ""
    body = "\n\n".join(blocks[1:]).strip()
    trailers: dict[str, str] = {}
    for line in message.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            if key.strip().startswith("Hone-"):
                trailers[key.strip()] = value.strip()
    return title, body, trailers
