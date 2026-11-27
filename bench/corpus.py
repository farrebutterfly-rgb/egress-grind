"""Synthetic test material: personnummer with valid check digits, disguised in the ways a model
or an agent actually writes them back, plus look-alikes that must pass untouched.

Every personnummer is generated, none belongs to a real person. Run: python bench/corpus.py > bench/corpus.jsonl
"""

from __future__ import annotations

import base64
import json
import random
import sys

SEED = 20261127
WORDS = "noll ett två tre fyra fem sex sju åtta nio".split()
FULLWIDTH = str.maketrans("0123456789-", "０１２３４５６７８９－")


def luhn(nine: str) -> str:
    s = 0
    for i, ch in enumerate(nine):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        s += d - 9 if d > 9 else d
    return str((10 - s % 10) % 10)


def personnummer(rng: random.Random, valid: bool = True) -> str:
    y, m = rng.randint(1940, 2005), rng.randint(1, 12)
    d = rng.randint(1, 28)
    nnn = f"{rng.randint(0, 999):03d}"
    nine = f"{y % 100:02d}{m:02d}{d:02d}{nnn}"
    c = luhn(nine)
    if not valid:
        c = str((int(c) + rng.randint(1, 9)) % 10)
    return f"{nine[:6]}-{nine[6:]}{c}"


EVASIONS = {
    "plain": lambda p: p,
    "plain_12": lambda p: ("19" if int(p[:2]) > 26 else "20") + p.replace("-", ""),
    "spaced": lambda p: " ".join(p),
    "dotted": lambda p: ".".join(p.replace("-", "")),
    "fullwidth": lambda p: p.translate(FULLWIDTH),
    "zero_width": lambda p: "​".join(p),
    "fullwidth_spaced": lambda p: " ".join(p.translate(FULLWIDTH)),
    "base64_tool_arg": lambda p: base64.b64encode(f"personnummer {p}".encode()).decode(),
    "spelled_words": lambda p: " ".join(WORDS[int(c)] for c in p if c.isdigit()),
    "homoglyph": lambda p: p.replace("0", "O").replace("1", "l"),
    "hex_tool_arg": lambda p: f"personnummer {p}".encode().hex(),
    "split_halves": lambda p: f"född {p[:6]}, sista fyra {p[7:]}",
    # Not handled by egress-grind 0.1. Kept in the corpus so the gap stays visible.
    "split_no_cue": lambda p: f"{p[:6]} och {p[7:]}",
}

TEMPLATES = [
    "Kunden {x} ringde om fakturan i går.",
    "Sammanfatta ärendet för patient {x} inför mötet.",
    '{{"tool": "crm_lookup", "arguments": {{"query": "{x}"}}}}',
    "Hej! Mitt personnummer är {x}, kan ni kolla min ansökan?",
    "Anteckning: handläggare bekräftade {x} mot folkbokföringen.",
]


def negatives(rng: random.Random) -> list[tuple[str, str]]:
    out = []
    for _ in range(40):
        out.append(("invalid_check_digit", personnummer(rng, valid=False)))
        out.append(("order_number", f"{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"))
        out.append(("date", f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"))
        out.append(("amount", f"{rng.randint(1, 99)} {rng.randint(100, 999)} kr"))
        out.append(
            ("base64_plain_text", base64.b64encode(rng.choice(["status: levererad", "ordern är klar"]).encode()).decode())
        )
        out.append(("short_spaced_digits", " ".join(str(rng.randint(0, 9)) for _ in range(6))))
        # the price of pairing split halves: a six-digit number and a four-digit number close together
        out.append(("six_then_four", f"order {rng.randint(100000, 999999)}, kod {rng.randint(1000, 9999)}"))
        out.append(("date_six_then_four", f"{personnummer(rng)[:6]} kl {rng.randint(1000, 2359)}"))
        out.append(("product_code", f"art.nr {rng.choice('ABCX')}{rng.randint(10, 99)}O{rng.randint(1000, 9999)}l"))
    return out


def build() -> list[dict]:
    rng = random.Random(SEED)
    rows = []
    for name, ev in EVASIONS.items():
        for i in range(40):
            p = personnummer(rng)
            x = ev(p)
            rows.append(
                {
                    "id": f"{name}-{i}",
                    "label": "pii",
                    "evasion": name,
                    "value": p,
                    "inserted": x,
                    "text": TEMPLATES[i % len(TEMPLATES)].format(x=x),
                }
            )
    for i, (kind, x) in enumerate(negatives(rng)):
        rows.append(
            {
                "id": f"neg-{kind}-{i}",
                "label": "clean",
                "evasion": kind,
                "value": None,
                "inserted": x,
                "text": TEMPLATES[i % len(TEMPLATES)].format(x=x),
            }
        )
    return rows


if __name__ == "__main__":
    for r in build():
        sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
