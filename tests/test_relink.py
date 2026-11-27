import json

from test_grind import echo_handler, make_client

from egress_grind.relink import count, extract, guard, k_of


def test_population_total_matches_scb():
    assert count(None, None, None, None) == 10_587_710  # folkmängd 31 december 2024


def test_rare_combination_is_generalised_until_k_holds():
    g = guard("Patienten är en 34-årig kvinna från Arjeplog som arbetar som veterinär.")
    assert g.k_before < 1 and g.ok and g.k_after >= 5
    assert "Arjeplog" not in g.text and "34" not in g.text
    assert "Norrbottens län" in g.text


def test_common_combination_is_left_alone():
    t = "Han är 67 år och bor i Malmö."
    g = guard(t)
    assert g.text == t and g.steps == []


def test_generalised_text_reads_back_consistently():
    g = guard("Hon är född 1958, bor i Bjurholm och är präst.")
    q = extract(g.text)
    assert abs(k_of(q) - g.k_after) < 0.5


def test_one_quasi_identifier_alone_is_not_scored():
    assert guard("Kunden bor i Kiruna.").steps == []


def test_proxy_generalises_before_sending(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler)
    r = c.post(
        "/v1/chat/completions",
        json={"model": "m", "messages": [{"role": "user", "content": "En 34-årig kvinna från Arjeplog, veterinär."}]},
    )
    assert r.status_code == 200 and "Arjeplog" not in json.dumps(seen[0])


def test_proxy_blocks_when_messages_together_single_someone_out(tmp_path, monkeypatch):
    c, seen = make_client(tmp_path, monkeypatch, echo_handler)
    msgs = [
        {"role": "user", "content": "Ärendet gäller en kvinna i Arjeplog."},
        {"role": "assistant", "content": "Noterat."},
        {"role": "user", "content": "Hon är 34 år och veterinär."},
    ]
    r = c.post("/v1/chat/completions", json={"model": "m", "messages": msgs})
    assert r.status_code == 403 and r.json()["error"]["types"] == {"REIDENTIFIABLE": 1} and seen == []
