"""OpenAI-compatible proxy: POST /v1/chat/completions, scanned on the way out, restored on the way back.

Point an existing client at this service instead of the provider (base_url=http://localhost:8080/v1)
and nothing else changes. Every text the model would see is scanned: message content (plain or as
content parts), tool results, and the arguments of earlier tool calls. If any of them blocks, the
request never leaves and the caller gets 403 with the entity types. If the scanner itself fails,
the request is refused with 503: the gateway fails closed, never open.

Run: uvicorn egress_grind.api:create_app --factory --port 8080

Configuration (environment):
  EGRESS_UPSTREAM   base URL of the real provider, default https://api.openai.com
  EGRESS_MODE       strict | mask | block, default strict
  EGRESS_AUDIT      path of the audit log, default audit.jsonl
  EGRESS_ALLOWLIST  comma-separated values never treated as personal data (your own org.nr, say)
  EGRESS_RELINK_K   generalise until at least this many people in Sweden match, default 5, 0 = off
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import relink
from .audit import AuditLog
from .policy import Decision, Pseudonyms, decide
from .restore import StreamRestorer, restore

_FORWARD_HEADERS = ("authorization", "api-key", "openai-organization", "openai-project")


class Blocked(Exception):
    def __init__(self, decision: Decision, where: str):
        self.decision, self.where = decision, where


def _scan_request(
    body: dict, mode: str, allowlist: list[str] | None, k_min: float = 0
) -> tuple[dict, Pseudonyms, dict[str, int]]:
    """Returns the masked body, the pseudonym table and the entity counts. Raises Blocked.

    With k_min > 0 every text is also generalised until at least k_min people in Sweden match
    what is left (see relink.py), and the request is blocked if that is not possible, or if the
    messages together narrow it below k_min even though each one alone does not."""
    table = Pseudonyms()
    counts: dict[str, int] = {}
    sent: list[str] = []

    def check(text: str, where: str) -> str:
        d = decide(text, mode=mode, allowlist=allowlist, table=table)
        for k, v in d.types.items():
            counts[k] = counts.get(k, 0) + v
        if d.action == "block":
            raise Blocked(d, where)
        out = d.text if d.action == "mask" else text
        if k_min:
            g = relink.guard(out, k_min)
            if g.steps:
                counts["GENERALISED"] = counts.get("GENERALISED", 0) + 1
            if not g.ok:
                raise Blocked(Decision("block", {"REIDENTIFIABLE": 1}, via="relink"), where)
            out = g.text
        sent.append(out)
        return out

    out = json.loads(json.dumps(body))
    for i, msg in enumerate(out.get("messages", [])):
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = check(content, f"messages[{i}].content")
        elif isinstance(content, list):
            for j, part in enumerate(content):
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                    part["text"] = check(part["text"], f"messages[{i}].content[{j}]")
                elif isinstance(part, dict) and part.get("type") not in ("text", None):
                    raise Blocked(
                        Decision("block", {"UNSCANNABLE_" + str(part.get("type")).upper(): 1}), f"messages[{i}].content[{j}]"
                    )
        for k, call in enumerate(msg.get("tool_calls") or []):
            fn = call.get("function") or {}
            if isinstance(fn.get("arguments"), str):
                fn["arguments"] = check(fn["arguments"], f"messages[{i}].tool_calls[{k}].arguments")
    if k_min and len(sent) > 1:
        q = relink.extract("\n".join(sent))
        if len(q.found) >= 2 and relink.k_of(q) < k_min:
            raise Blocked(Decision("block", {"REIDENTIFIABLE": 1}, via="relink"), "messages")
    return out, table, counts


def _restore_message(msg: dict, mapping: dict[str, str]) -> None:
    if isinstance(msg.get("content"), str):
        msg["content"] = restore(msg["content"], mapping)
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") or {}
        if isinstance(fn.get("arguments"), str):
            fn["arguments"] = restore(fn["arguments"], mapping, json_string=True)


class _SSERestorer:
    """Restores placeholders across a server-sent event stream, per choice and per tool call."""

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.content: dict[int, StreamRestorer] = {}
        self.args: dict[tuple[int, int], StreamRestorer] = {}

    def chunk(self, data: dict) -> dict:
        for ch in data.get("choices", []):
            idx = ch.get("index", 0)
            delta = ch.get("delta") or {}
            done = ch.get("finish_reason") is not None
            if isinstance(delta.get("content"), str):
                r = self.content.setdefault(idx, StreamRestorer(self.mapping))
                delta["content"] = r.feed(delta["content"])
            if done and idx in self.content:
                delta["content"] = (delta.get("content") or "") + self.content.pop(idx).flush()
            for tc in delta.get("tool_calls") or []:
                fn = tc.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    key = (idx, tc.get("index", 0))
                    r = self.args.setdefault(key, StreamRestorer(self.mapping, json_string=True))
                    fn["arguments"] = r.feed(fn["arguments"])
            if done:
                tail = {k: r.flush() for k, r in list(self.args.items()) if k[0] == idx}
                for k in tail:
                    self.args.pop(k)
                if any(tail.values()):
                    delta.setdefault("tool_calls", [])
                    for (_, tci), rest in tail.items():
                        if rest:
                            delta["tool_calls"].append({"index": tci, "function": {"arguments": rest}})
            ch["delta"] = delta
        return data


def create_app(client: httpx.AsyncClient | None = None) -> FastAPI:
    upstream = os.environ.get("EGRESS_UPSTREAM", "https://api.openai.com").rstrip("/")
    mode = os.environ.get("EGRESS_MODE", "strict")
    allow = [a.strip() for a in os.environ.get("EGRESS_ALLOWLIST", "").split(",") if a.strip()] or None
    k_min = float(os.environ.get("EGRESS_RELINK_K", "5"))
    audit = AuditLog(os.environ.get("EGRESS_AUDIT", "audit.jsonl"))
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    app = FastAPI(title="egress-grind", version="0.1.0")
    app.state.audit = audit

    def unreachable(rid: str, action: str, counts: dict, e: Exception) -> JSONResponse:
        audit.write(id=rid, action=action, types=counts, upstream=None, error=type(e).__name__)
        return JSONResponse({"error": {"type": "egress_upstream_unreachable"}}, status_code=502)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "mode": mode}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        rid = uuid.uuid4().hex[:16]
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": {"message": "body is not JSON"}}, status_code=400)
        try:
            masked, table, counts = _scan_request(body, mode, allow, k_min)
        except Blocked as b:
            audit.write(id=rid, action="block", via=b.decision.via, where=b.where, types=b.decision.types)
            return JSONResponse(
                {"error": {"type": "egress_blocked", "where": b.where, "via": b.decision.via, "types": b.decision.types}},
                status_code=403,
            )
        except Exception as e:  # the scanner broke: refuse, never forward unscanned
            audit.write(id=rid, action="error", error=type(e).__name__)
            return JSONResponse({"error": {"type": "egress_scanner_error"}}, status_code=503)

        action = "mask" if table.by_value else "pass"
        headers = {k: v for k, v in request.headers.items() if k.lower() in _FORWARD_HEADERS}
        url = f"{upstream}/v1/chat/completions"
        mapping = table.mapping

        if masked.get("stream"):
            req = http.build_request("POST", url, json=masked, headers=headers)
            try:
                resp = await http.send(req, stream=True)
            except httpx.HTTPError as e:
                return unreachable(rid, action, counts, e)
            audit.write(id=rid, action=action, types=counts, upstream=resp.status_code, stream=True)
            if resp.status_code != 200:
                raw = await resp.aread()
                await resp.aclose()
                return Response(raw, status_code=resp.status_code, media_type=resp.headers.get("content-type"))

            async def events() -> AsyncIterator[bytes]:
                r = _SSERestorer(mapping)
                try:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: ") and line[6:].strip() != "[DONE]":
                            try:
                                data = json.loads(line[6:])
                            except json.JSONDecodeError:
                                yield (line + "\n").encode()
                                continue
                            yield f"data: {json.dumps(r.chunk(data), ensure_ascii=False)}\n".encode()
                        else:
                            yield (line + "\n").encode()
                finally:
                    await resp.aclose()

            return StreamingResponse(events(), media_type="text/event-stream")

        try:
            resp = await http.post(url, json=masked, headers=headers)
        except httpx.HTTPError as e:
            return unreachable(rid, action, counts, e)
        audit.write(id=rid, action=action, types=counts, upstream=resp.status_code)
        if resp.status_code != 200 or not mapping:
            return Response(resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))
        data: Any = resp.json()
        for ch in data.get("choices", []):
            if isinstance(ch.get("message"), dict):
                _restore_message(ch["message"], mapping)
        return JSONResponse(data)

    return app
