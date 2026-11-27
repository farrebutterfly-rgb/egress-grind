"""Merge bench/results/*.json into one table (bench/RESULTS.md)."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

HERE = Path(__file__).parent
ORDER = ["svenska-pii", "egress-grind", "presidio", "presidio-patterns", "llm-guard"]


def main() -> None:
    res = {p.stem: json.loads(p.read_text()) for p in (HERE / "results").glob("*.json")}
    systems = [s for s in ORDER if s in res]
    pii_ev = list(dict.fromkeys(r["evasion"] for r in res[systems[0]]["rows"] if r["label"] == "pii"))
    neg_ev = list(dict.fromkeys(r["evasion"] for r in res[systems[0]]["rows"] if r["label"] == "clean"))

    def cell(s, ev, label):
        rows = [r for r in res[s]["rows"] if r["evasion"] == ev and r["label"] == label]
        return f"{sum(r['bad'] for r in rows)}/{len(rows)}"

    lines = ["# Results", "", "Leaked personnummer per disguise (lower is better). 40 synthetic cases per row.", ""]
    lines.append("| disguise | " + " | ".join(systems) + " |")
    lines.append("|---|" + "---|" * len(systems))
    for ev in pii_ev:
        lines.append(f"| {ev} | " + " | ".join(cell(s, ev, "pii") for s in systems) + " |")
    tot = [sum(r["bad"] for r in res[s]["rows"] if r["label"] == "pii") for s in systems]
    n = sum(r["label"] == "pii" for r in res[systems[0]]["rows"])
    lines.append("| **total leaked** | " + " | ".join(f"**{t}/{n}**" for t in tot) + " |")
    lines += ["", "Clean text that was blocked or changed (false positives, lower is better).", ""]
    lines.append("| look-alike | " + " | ".join(systems) + " |")
    lines.append("|---|" + "---|" * len(systems))
    for ev in neg_ev:
        lines.append(f"| {ev} | " + " | ".join(cell(s, ev, "clean") for s in systems) + " |")
    ftot = [sum(r["bad"] for r in res[s]["rows"] if r["label"] == "clean") for s in systems]
    m = sum(r["label"] == "clean" for r in res[systems[0]]["rows"])
    lines.append("| **total** | " + " | ".join(f"**{t}/{m}**" for t in ftot) + " |")
    lines += ["", "| system | configuration | median ms per text |", "|---|---|---|"]
    for s in systems:
        lines.append(f"| {s} | {res[s]['label']} | {statistics.median(r['ms'] for r in res[s]['rows']):.2f} |")
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
