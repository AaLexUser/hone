"""Short hex ids in the shapes the UI renders: ses_xxxx / r_xxxx / 7-hex nodes."""

from __future__ import annotations

import secrets


def trace_id_from_session(session_id: str) -> str:
    hex_part = "".join(c for c in session_id if c in "0123456789abcdefABCDEF")
    return f"ses_{(hex_part[:8] or secrets.token_hex(4)).lower()}"


def new_run_id() -> str:
    return f"r_{secrets.token_hex(2)}"


def new_node_id() -> str:
    return secrets.token_hex(3) + secrets.token_hex(1)[:1]
