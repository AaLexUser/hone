"""Validate and render the review judge's durable artifact."""

from __future__ import annotations

from html import escape
from typing import Any


class ReviewError(ValueError):
    pass


def validate_review(value: Any, trace_ids: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ReviewError("review must be a version 1 JSON object")
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        raise ReviewError("review.summary must be a nonempty string")
    for key in ("findings", "hypotheses", "directions", "unresolved"):
        if not isinstance(value.get(key), list):
            raise ReviewError(f"review.{key} must be an array")
    for key in ("findings", "hypotheses"):
        for item in value[key]:
            if not isinstance(item, dict) or not isinstance(item.get("statement"), str):
                raise ReviewError(f"review.{key} contains an invalid item")
            if not isinstance(item.get("traceIds"), list) or not all(
                isinstance(trace_id, str) for trace_id in item["traceIds"]
            ):
                raise ReviewError(f"review.{key} item traceIds must be an array")
            if trace_ids is not None and any(
                trace_id not in trace_ids for trace_id in item["traceIds"]
            ):
                raise ReviewError(f"review.{key} item cites a trace outside the frozen batch")
            if item.get("confidence") not in {"low", "medium", "high"}:
                raise ReviewError(f"review.{key} item confidence is invalid")
            if key == "hypotheses" and "contradictions" in item and not (
                isinstance(item["contradictions"], list)
                and all(isinstance(text, str) for text in item["contradictions"])
            ):
                raise ReviewError("review.hypotheses item contradictions must be strings")
    for key in ("directions", "unresolved"):
        if not all(isinstance(item, str) for item in value[key]):
            raise ReviewError(f"review.{key} must contain strings")
    return value


def _chips(trace_ids: list[Any]) -> str:
    return "".join(f'<code class="chip">{escape(str(trace_id))}</code>' for trace_id in trace_ids)


def _items(items: list[dict[str, Any]], *, hypotheses: bool = False) -> str:
    if not items:
        return '<p class="empty">None recorded.</p>'
    rows = []
    for item in items:
        contradictions = item.get("contradictions") if hypotheses else None
        extra = ""
        if isinstance(contradictions, list) and contradictions:
            extra = '<p class="contra">Contradictions: ' + escape("; ".join(map(str, contradictions))) + "</p>"
        rows.append(
            '<article class="item">'
            f'<span class="confidence {escape(str(item["confidence"]))}">{escape(str(item["confidence"]))}</span>'
            f'<p>{escape(item["statement"])}</p>'
            f'<div class="chips">{_chips(item["traceIds"])}</div>{extra}'
            "</article>"
        )
    return "".join(rows)


def _plain_list(items: list[Any]) -> str:
    if not items:
        return '<p class="empty">None recorded.</p>'
    return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in items) + "</ul>"


def render_review(value: Any) -> str:
    review = validate_review(value)
    summary = escape(review["summary"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trace Review Report</title><style>
:root{{--bg:#08090b;--panel:#0f1114;--line:#1d2126;--text:#eef0f2;--muted:#9da3ad;--accent:#6672e0;--green:#3dd68c;--amber:#ffb224}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:13px/1.55 Inter,system-ui,sans-serif}}
main{{max-width:960px;margin:auto;padding:36px 24px 64px}}h1{{font-size:28px;margin:4px 0 8px}}h2{{font-size:16px;margin:0 0 12px}}.eyebrow{{color:var(--accent);font:11px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}}
.summary{{color:var(--muted);font-size:15px;max-width:760px}}section{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin-top:16px}}
.item{{position:relative;border-top:1px solid var(--line);padding:14px 0}}.item:first-of-type{{border-top:0;padding-top:0}}.item p{{margin:0 70px 8px 0}}
.confidence{{position:absolute;right:0;top:14px;font:10px ui-monospace,monospace;text-transform:uppercase}}.item:first-of-type .confidence{{top:0}}.high{{color:var(--green)}}.medium{{color:var(--amber)}}.low{{color:var(--muted)}}
.chip{{display:inline-block;background:#171a20;border:1px solid #282d36;border-radius:99px;padding:2px 7px;margin:2px 4px 0 0;color:#cbd0da}}ul{{margin:0;padding-left:20px}}li+li{{margin-top:7px}}.empty,.contra{{color:var(--muted)}}
</style></head><body><main><p class="eyebrow">Judged artifact · review.json v1</p><h1>Trace Review Report</h1><p class="summary">{summary}</p>
<section><h2>Findings</h2>{_items(review["findings"])}</section>
<section><h2>Hypotheses</h2>{_items(review["hypotheses"], hypotheses=True)}</section>
<section><h2>Optimization directions</h2>{_plain_list(review["directions"])}</section>
<section><h2>Unresolved</h2>{_plain_list(review["unresolved"])}</section>
</main></body></html>"""
