"""Score one system on the corpus. Each system gets the outgoing text and returns
(blocked, text_that_would_leave). Systems live in different environments because LLM Guard pins
an old Presidio, so each is run on its own and the results are merged by bench/report.py.

    python bench/run.py --system svenska-pii
    python bench/run.py --system egress-grind
    python bench/run.py --system presidio      # needs presidio-analyzer + en_core_web_lg
    python bench/run.py --system llm-guard     # needs llm-guard

A personnummer counts as leaked if the text that would leave still contains the disguised form
verbatim, or if its digits can be read back out of it after undoing spacing, full-width digits,
zero-width characters and base64. That is the reading a language model can do on its own.
A clean row counts as a false positive if it is blocked or changed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

from egress_grind.normalize import views  # noqa: E402


def leaked(row: dict, blocked: bool, out: str) -> bool:
    if blocked:
        return False
    if row["inserted"] in out:
        return True
    digits = re.sub(r"\D", "", row["value"])
    v = views(out)
    return any(digits in re.sub(r"\D", "", t) for t in [v.folded, *v.decoded])


def mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    for s, e in sorted(spans, reverse=True):
        text = text[:s] + "<X>" + text[e:]
    return text


def system_svenska_pii():
    from svenska_pii import hitta

    def run(text):
        return False, mask_spans(text, [(h.start, h.end) for h in hitta(text)])

    return run, f"svenska-pii {metadata.version('svenska-pii')}"


def system_egress_grind():
    from egress_grind.policy import decide

    def run(text):
        d = decide(text, mode="mask")
        return d.action == "block", (d.text if d.action == "mask" else text)

    return run, "egress-grind 0.1.0 (mask mode)"


def _presidio(with_ner: bool):
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.predefined_recognizers import SePersonnummerRecognizer

    engine = AnalyzerEngine()
    engine.registry.add_recognizer(SePersonnummerRecognizer(supported_language="en"))
    if not with_ner:
        engine.registry.remove_recognizer("SpacyRecognizer")

    def run(text):
        res = engine.analyze(text=text, language="en")
        return False, mask_spans(text, [(r.start, r.end) for r in res])

    what = "en_core_web_lg NER + all pattern recognizers" if with_ner else "pattern recognizers only, NER removed"
    return run, f"presidio-analyzer {metadata.version('presidio-analyzer')} ({what}, + SE_PERSONNUMMER)"


def system_presidio():
    return _presidio(with_ner=True)


def system_presidio_patterns():
    return _presidio(with_ner=False)


def system_llm_guard():
    from llm_guard import scan_prompt
    from llm_guard.input_scanners import Anonymize, InvisibleText
    from llm_guard.vault import Vault

    scanners = [InvisibleText(), Anonymize(Vault())]

    def run(text):
        out, valid, _ = scan_prompt(scanners, text, fail_fast=False)
        return not valid.get("InvisibleText", True), out

    return run, f"llm-guard {metadata.version('llm-guard')} (InvisibleText + Anonymize, defaults)"


SYSTEMS = {
    "svenska-pii": system_svenska_pii,
    "egress-grind": system_egress_grind,
    "presidio": system_presidio,
    "presidio-patterns": system_presidio_patterns,
    "llm-guard": system_llm_guard,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", choices=SYSTEMS, required=True)
    args = ap.parse_args()
    run, label = SYSTEMS[args.system]()
    rows = [json.loads(line) for line in (HERE / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    results, t0 = [], time.perf_counter()
    for row in rows:
        s = time.perf_counter()
        blocked, out = run(row["text"])
        ms = (time.perf_counter() - s) * 1000
        if row["label"] == "pii":
            bad = leaked(row, blocked, out)
        else:
            bad = blocked or out != row["text"]
        results.append(
            {
                "id": row["id"],
                "label": row["label"],
                "evasion": row["evasion"],
                "blocked": blocked,
                "bad": bad,
                "ms": round(ms, 2),
            }
        )
    out = {"system": args.system, "label": label, "seconds": round(time.perf_counter() - t0, 1), "rows": results}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{args.system}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    n_pii = sum(r["label"] == "pii" for r in results)
    leaks = sum(r["bad"] for r in results if r["label"] == "pii")
    fps = sum(r["bad"] for r in results if r["label"] == "clean")
    print(f"{label}: leaked {leaks}/{n_pii}, false positives {fps}/{len(results) - n_pii}")


if __name__ == "__main__":
    main()
