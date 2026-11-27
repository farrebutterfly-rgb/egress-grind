"""Rebuild src/egress_grind/data/scb_2024.json.gz from SCB's open API (CC0).

python scripts/fetch_scb.py
"""

from __future__ import annotations

import gzip
import json
import urllib.request
from pathlib import Path

API = "https://api.scb.se/OV0104/v1/doris/sv/ssd"
POP = f"{API}/BE/BE0101/BE0101A/BefolkningNy"
OCC = f"{API}/AM/AM0208/AM0208C/YREG55BAS"
YEAR = "2024"
OUT = Path(__file__).parent.parent / "src" / "egress_grind" / "data" / "scb_2024.json.gz"


def get(url: str) -> dict:
    return json.load(urllib.request.urlopen(url, timeout=60))


def post(url: str, query: list[dict]) -> dict:
    body = json.dumps({"query": query, "response": {"format": "json"}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=300).read().decode("utf-8-sig"))


def item(code: str, values: list[str]) -> dict:
    return {"code": code, "selection": {"filter": "item", "values": values}}


def num(v: str) -> int:
    return int(v) if v.strip().isdigit() else 0


def main() -> None:
    pm = {v["code"]: v for v in get(POP)["variables"]}
    kommuner = [c for c in pm["Region"]["values"] if len(c) == 4]
    ages = [a for a in pm["Alder"]["values"] if a != "tot"]
    pop = post(
        POP,
        [
            item("Region", kommuner),
            item("Alder", ages),
            item("Kon", ["1", "2"]),
            item("ContentsCode", ["BE0101N1"]),
            item("Tid", [YEAR]),
        ],
    )
    om = {v["code"]: v for v in get(OCC)["variables"]}
    lan = [c for c in om["Region"]["values"] if c != "00"]
    occ = post(
        OCC,
        [
            item("Region", lan),
            item("Yrke2012", om["Yrke2012"]["values"]),
            item("Alder", om["Alder"]["values"]),
            item("Kon", ["1", "2"]),
            item("Tid", [YEAR]),
        ],
    )
    out = {
        "source_population": f"SCB BE0101A/BefolkningNy, folkmängd 31 december {YEAR}, kommun x ettårsålder x kön",
        "source_occupation": f"SCB AM0208C/YREG55BAS, anställda (nattbefolkning), län x SSYK2012 x ålder x kön, {YEAR}",
        "license": "SCB open data, CC0",
        "kommuner": dict(zip(pm["Region"]["values"], pm["Region"]["valueTexts"], strict=True)),
        "lan": {c: t for c, t in zip(om["Region"]["values"], om["Region"]["valueTexts"], strict=True) if c != "00"},
        "yrken": dict(zip(om["Yrke2012"]["values"], om["Yrke2012"]["valueTexts"], strict=True)),
        "aldersgrupper": om["Alder"]["values"],
        "pop": {"|".join(x["key"][:3]): num(x["values"][0]) for x in pop["data"] if num(x["values"][0])},
        "occ": {"|".join(x["key"][:4]): num(x["values"][0]) for x in occ["data"] if num(x["values"][0])},
    }
    out["kommuner"] = {c: n for c, n in out["kommuner"].items() if c in kommuner}
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(OUT, sum(out["pop"].values()), "people")


if __name__ == "__main__":
    main()
