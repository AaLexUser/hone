"""Deterministic, redacted research index for a frozen trace batch.

The compiler surfaces exact events that are expensive for every MAJICS worker
to rediscover. It does not label outcomes, rank hypotheses, or authorize edits.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

EVIDENCE_VERSION = 1


def _argument_hash(arguments: Any) -> str:
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _exit_code(message: Mapping[str, Any]) -> int | None:
    sources = [message, message.get("details")]
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in ("exitCode", "exit_code", "returnCode", "return_code"):
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
    return None


def compile_trace(
    trace_id: str,
    body: str,
    *,
    feedback_present: bool = False,
    prompt_version: str = "",
    source_missing: bool = False,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    malformed: list[int] = []
    session: dict[str, Any] = {}
    for line_number, raw in enumerate(body.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            malformed.append(line_number)
            continue
        if not isinstance(value, dict):
            malformed.append(line_number)
            continue
        if value.get("type") == "session" and not session:
            session = value
        entries.append(value)

    calls: dict[tuple[str, str], list[int]] = defaultdict(list)
    call_names: dict[str, str] = {}
    tool_calls = 0
    messages = 0
    errors: list[dict[str, Any]] = []

    for entry in entries:
        message = entry.get("message", entry)
        if not isinstance(message, dict) or not message.get("role"):
            continue
        message_index = messages
        messages += 1
        if message.get("role") == "assistant":
            blocks = message.get("content")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "toolCall":
                    continue
                name = str(block.get("name") or "unknown")
                digest = _argument_hash(block.get("arguments", {}))
                calls[(name, digest)].append(message_index)
                call_id = block.get("id")
                if isinstance(call_id, str):
                    call_names[call_id] = name
                tool_calls += 1
        elif message.get("role") == "toolResult":
            code = _exit_code(message)
            if message.get("isError") is True or (code is not None and code != 0):
                name = message.get("toolName")
                if not isinstance(name, str):
                    name = call_names.get(str(message.get("toolCallId") or ""), "unknown")
                signal: dict[str, Any] = {
                    "code": "EXPLICIT_TOOL_ERROR",
                    "tool": name,
                    "messageIndex": message_index,
                }
                if code is not None:
                    signal["exitCode"] = code
                errors.append(signal)

    signals: list[dict[str, Any]] = []
    if source_missing:
        signals.append({"code": "MISSING_TRACE"})
    if malformed:
        signals.append({
            "code": "MALFORMED_JSONL",
            "lineNumbers": malformed,
            "count": len(malformed),
        })
    signals.extend(errors)
    for (name, digest), indexes in sorted(calls.items()):
        if len(indexes) >= 3:
            signals.append({
                "code": "EXACT_TOOL_REPEAT",
                "tool": name,
                "argumentHash": digest,
                "messageIndexes": indexes,
                "count": len(indexes),
            })

    return {
        "id": trace_id,
        "promptVersion": str(session.get("agents_md") or prompt_version or ""),
        "feedbackPresent": bool(feedback_present or session.get("feedback")),
        "metrics": {
            "messages": messages,
            "toolCalls": tool_calls,
            "uniqueToolCalls": len(calls),
        },
        "signals": signals,
    }


def compile_batch(run_id: str, traces: list[dict[str, Any]]) -> dict[str, Any]:
    compiled = [
        compile_trace(
            str(trace["id"]),
            str(trace["body"]),
            feedback_present=bool(trace.get("feedback_present")),
            prompt_version=str(trace.get("prompt_version") or ""),
            source_missing=bool(trace.get("source_missing")),
        )
        for trace in traces
    ]
    counts = Counter(signal["code"] for trace in compiled for signal in trace["signals"])
    return {
        "version": EVIDENCE_VERSION,
        "role": "research_index_not_verdict",
        "runId": run_id,
        "traces": compiled,
        "batch": {
            "traceCount": len(compiled),
            "feedbackCount": sum(1 for trace in compiled if trace["feedbackPresent"]),
            "signalCounts": dict(sorted(counts.items())),
        },
    }


def compile_run(dirs: Any, db: Any, run: Mapping[str, Any]) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    for trace_id in run["trace_ids"]:
        source: Path = dirs.trace_path(trace_id)
        row = db.one(
            "SELECT feedback, version_id FROM traces WHERE session_id = ?",
            (trace_id,),
        ) or {}
        traces.append({
            "id": trace_id,
            "body": source.read_text(encoding="utf-8", errors="replace")
            if source.exists() and source.stat().st_size else "",
            "source_missing": not source.exists() or not source.stat().st_size,
            "feedback_present": bool(row.get("feedback")),
            "prompt_version": row.get("version_id") or "",
        })
    return compile_batch(str(run["id"]), traces)
