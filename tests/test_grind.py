import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from egress_grind import api as api_mod
from egress_grind.audit import verify
from egress_grind.normalize import fold, views
from egress_grind.policy import Pseudonyms, decide
from egress_grind.restore import StreamRestorer, restore

PNR = "850312-2387"  # synthetic, valid check digit
PNR_DIGITS = "8503122387"


# normalisation -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "disguised",
    [
        "8 5 0 3 1 2 - 2 3 8 7",
        "８５０３１２－２３８７",
        "85​03​12‍-2387",
        "8.5.0.3.1.2-2.3.8.7",
        "åtta fem noll tre ett två två tre åtta sju",
    ],
)
def test_fold_recovers_the_number(disguised):
    assert PNR_DIGITS in fold(disguised).replace("-", "")


def test_base64_segment_is_decoded():
    blob = base64.b64encode(f"kund {PNR}".encode()).decode()
    assert any(PNR in d for d in views(f'{{"note": "{blob}"}}').decoded)


def test_ordinary_text_is_left_alone():
    t = "Ordern skickas måndag, en av tre fick fem, ring växeln."
    assert fold(t) == t and views(t).decoded == []


# policy --------------------------------------------------------------------------------------


def test_plain_personnummer_blocks_in_strict():
    d = decide(f"Kunden har pnr {PNR}")
    assert d.action == "block" and d.types == {"SE_PERSONNUMMER": 1}


def test_mask_mode_masks_and_maps_back():
    d = decide(f"Kunden har pnr {PNR}", mode="mask")
    assert d.action == "mask" and PNR not in d.text
    assert restore(d.text, d.mapping) == f"Kunden har pnr {PNR}"


def test_soft_types_are_masked_in_strict():
    d = decide("Mejla anna.svensson@exempel.se")
    assert d.action == "mask" and "anna.svensson" not in d.text


@pytest.mark.parametrize("disguised", ["8 5 0 3 1 2 - 2 3 8 7", "８５０３１２－２３８７", "85​0312-2387"])
def test_disguised_number_blocks_even_in_mask_mode(disguised):
    d = decide(f"pnr {disguised}", mode="mask")
    assert d.action == "block" and d.via == "normalised"


def test_base64_blocks_via_decoded():
    blob = base64.b64encode(f"pnr {PNR}".encode()).decode()
    d = decide(f'{{"payload": "{blob}"}}', mode="mask")
    assert d.action == "block" and d.via == "decoded"


def test_hex_blocks_via_decoded():
    d = decide(f"payload {f'pnr {PNR}'.encode().hex()}", mode="mask")
    assert d.action == "block" and d.via == "decoded"


def test_homoglyph_digits_block():
    assert decide("pnr 85O3l2-2387", mode="mask").action == "block"


def test_split_halves_are_paired():
    d = decide("Hon är född 850312, sista fyra 2387.", mode="mask")
    assert d.action == "block" and d.types == {"SE_PERSONNUMMER": 1}


def test_split_halves_with_wrong_check_digit_pass():
    assert decide("Order 850312, kod 2388.", mode="mask").action == "pass"


def test_same_value_same_placeholder_across_texts():
    table = Pseudonyms()
    a = decide("anna@exempel.se", mode="mask", table=table)
    b = decide("svara anna@exempel.se", mode="mask", table=table)
    assert a.text in b.text and len(table.mapping) == 1


def test_nothing_found_passes():
    assert decide("Hej, vad kostar en offert?").action == "pass"


# streaming restore ---------------------------------------------------------------------------


def test_stream_restorer_handles_split_placeholder():
    r = StreamRestorer({"[email_1]": "anna@exempel.se"})
    out = r.feed("Skicka till [em") + r.feed("ail_") + r.feed("1] idag") + r.flush()
    assert out == "Skicka till anna@exempel.se idag"


def test_stream_restorer_releases_text_without_placeholders():
    r = StreamRestorer({"[email_1]": "x"})
    assert r.feed("hej ") == "hej "
    assert r.feed("[1] är en lista") == "[1] är en lista"


def test_json_string_restore_escapes():
    assert restore("[name_1]", {"[name_1]": 'a"b'}, json_string=True) == 'a\\"b'


# proxy ---------------------------------------------------------------------------------------


def make_client(tmp_path, monkeypatch, handler, mode="mask"):
    monkeypatch.setenv("EGRESS_UPSTREAM", "http://upstream.test")
    monkeypatch.setenv("EGRESS_MODE", mode)
    monkeypatch.setenv("EGRESS_AUDIT", str(tmp_path / "audit.jsonl"))
    seen = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    return TestClient(api_mod.create_app(client=http)), seen


def echo_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    last = body["messages"][-1]["content"]
    return httpx.Response(
        200, json={"choices": [{"index": 0, "message": {"role": "assistant", "content": f"Noterat: {last}"}}]}
    )


def test_proxy_masks_outgoing_and_restores_answer(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler)
    r = c.post(
        "/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "mejl anna@exempel.se"}]}
    )
    assert r.status_code == 200
    assert "anna@exempel.se" not in json.dumps(seen[0])
    assert r.json()["choices"][0]["message"]["content"] == "Noterat: mejl anna@exempel.se"


def test_proxy_blocks_and_never_calls_upstream(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler, mode="strict")
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": f"pnr {PNR}"}]})
    assert r.status_code == 403 and r.json()["error"]["types"] == {"SE_PERSONNUMMER": 1}
    assert PNR not in r.text and seen == []


def test_proxy_scans_tool_call_arguments(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler)
    blob = base64.b64encode(f"pnr {PNR}".encode()).decode()
    msgs = [
        {"role": "user", "content": "slå upp kunden"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "1", "type": "function", "function": {"name": "crm", "arguments": json.dumps({"q": blob})}}
            ],
        },
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
    ]
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": msgs})
    assert r.status_code == 403 and r.json()["error"]["via"] == "decoded" and seen == []


def test_proxy_scans_content_parts_and_refuses_images(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler)
    parts = [{"type": "text", "text": "titta"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": parts}]})
    assert r.status_code == 403 and seen == []


def test_proxy_fails_closed_when_scanner_breaks(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler)

    def boom(*a, **k):
        raise RuntimeError("scanner down")

    monkeypatch.setattr(api_mod, "decide", boom)
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hej"}]})
    assert r.status_code == 503 and seen == []


def test_proxy_restores_streamed_answer_split_across_chunks(tmp_path, monkeypatch):
    def sse(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        ph = body["messages"][0]["content"].split()[-1]  # e.g. [email_1]
        pieces = ["Svar till ", ph[:4], ph[4:], " klart"]
        lines = [
            f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': p}, 'finish_reason': None}]})}"
            for p in pieces
        ]
        lines.append(f"data: {json.dumps({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}")
        lines.append("data: [DONE]")
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n", headers={"content-type": "text/event-stream"})

    c, seen = make_client(tmp_path, monkeypatch, sse)
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "stream": True, "messages": [{"role": "user", "content": "mejl anna@exempel.se"}]},
    )
    text = "".join(
        json.loads(line[6:])["choices"][0]["delta"].get("content") or ""
        for line in r.text.splitlines()
        if line.startswith("data: {")
    )
    assert text == "Svar till anna@exempel.se klart"
    assert "anna@exempel.se" not in json.dumps(seen[0])


def test_proxy_restores_streamed_tool_arguments(tmp_path, monkeypatch):
    def sse(request: httpx.Request) -> httpx.Response:
        ph = json.loads(request.content)["messages"][0]["content"].split()[-1]
        args = json.dumps({"to": ph})
        cut = args.index("[") + 3
        lines = []
        for piece in (args[:cut], args[cut:]):
            d = {"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}
            lines.append(f"data: {json.dumps({'choices': [{'index': 0, 'delta': d, 'finish_reason': None}]})}")
        lines.append(f"data: {json.dumps({'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]})}")
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n", headers={"content-type": "text/event-stream"})

    c, _ = make_client(tmp_path, monkeypatch, sse)
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "stream": True, "messages": [{"role": "user", "content": "mejla anna@exempel.se"}]},
    )
    args = "".join(
        tc["function"]["arguments"]
        for line in r.text.splitlines()
        if line.startswith("data: {")
        for tc in json.loads(line[6:])["choices"][0]["delta"].get("tool_calls", [])
    )
    assert json.loads(args) == {"to": "anna@exempel.se"}


def test_proxy_reports_unreachable_upstream(tmp_path, monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    c, _ = make_client(tmp_path, monkeypatch, down)
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hej"}]})
    assert r.status_code == 502
    assert '"upstream": null' in (tmp_path / "audit.jsonl").read_text()


# audit ---------------------------------------------------------------------------------------


def test_audit_chain_holds_and_detects_tampering(tmp_path, monkeypatch):
    c, _ = make_client(tmp_path, monkeypatch, echo_handler, mode="strict")
    for content in ["hej", f"pnr {PNR}", "mejl anna@exempel.se"]:
        c.post("/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": content}]})
    log = tmp_path / "audit.jsonl"
    text = log.read_text()
    assert verify(log) == (True, None)
    assert PNR not in text and "anna@exempel.se" not in text
    lines = text.splitlines()
    lines[1] = lines[1].replace('"block"', '"pass"')
    log.write_text("\n".join(lines) + "\n")
    assert verify(log) == (False, 2)
