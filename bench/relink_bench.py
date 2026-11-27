"""Re-identification after masking: what an attacker with the population register can still do.

A synthetic population is drawn from SCB's own tables (kommun x age x sex, then occupation from the
län's share for that age group and sex). For each synthetic person a case note is written with a
synthetic personnummer and e-mail plus some of kommun, age, sex and occupation. Three treatments of
the note are compared:

  identifiers-only   personnummer and e-mail masked, everything else left (what a PII scanner does)
  egress-grind       the same, then relink.guard() generalises until k >= 5
  fixed-k-anon       always band age to ten years, kommun to län, drop occupation

The attacker knows every attribute that is still in the outgoing text at the precision it is
written in, including any the extractor missed, and counts matching people with relink.count().
Re-identification probability per note is 1/max(k, 1). Utility is the share of attributes that
reached the model at full precision.

    python bench/relink_bench.py  ->  bench/RELINK.md
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))

from corpus import luhn  # noqa: E402

from egress_grind import relink  # noqa: E402
from egress_grind.policy import decide  # noqa: E402

N = 2000
SEED = 20261127
WORD_FOR = {}
for w, c in relink.OCCUPATIONS.items():
    if " " not in w and w != "vd":
        WORD_FOR.setdefault(c, w)

SHAPES = [
    ("kommun", "ages", "sex"),
    ("kommun", "ages", "sex", "occupation"),
    ("kommun", "sex", "occupation"),
    ("kommun", "ages"),
    ("ages", "sex", "occupation"),
]


def draw_people(rng: random.Random, n: int) -> list[dict]:
    d = relink._data()
    cells = [(k, v) for k, v in d["pop"].items() if 18 <= k[1] <= 64]
    keys, weights = zip(*cells, strict=True)
    people = []
    for r, age, sex in rng.choices(keys, weights=weights, k=n):
        g = relink._group(age, d["groups"])
        base = d["lan_pop"].get((r[:2], g, sex), 0)
        occs = [(c, d["occ"].get((r[:2], c, g, sex), 0)) for c in WORD_FOR]
        employed_mapped = sum(x for _, x in occs)
        codes = [c for c, _ in occs] + [None]
        w = [x for _, x in occs] + [max(0, base - employed_mapped)]
        occ = rng.choices(codes, weights=w, k=1)[0]
        people.append({"kommun": r, "age": age, "sex": sex, "occupation": occ})
    return people


def pnr(rng: random.Random) -> str:
    nine = f"{rng.randint(40, 99):02d}{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}{rng.randint(0, 999):03d}"
    return f"{nine[:6]}-{nine[6:]}{luhn(nine)}"


def note(p: dict, shape: tuple[str, ...], rng: random.Random) -> str:
    d = relink._data()
    who = {"1": ("Mannen", "Han"), "2": ("Kvinnan", "Hon")}[p["sex"]] if "sex" in shape else ("Personen", "Personen")
    parts = [f"Ärende för {pnr(rng)}."]
    first = who[0]
    if "ages" in shape:
        parts.append(f"{first} är {p['age']} år")
    else:
        parts.append(f"{first} har hört av sig")
    if "kommun" in shape:
        parts[-1] += f" och bor i {d['kommuner'][p['kommun']]}."
    else:
        parts[-1] += "."
    if "occupation" in shape:
        parts.append(f"{who[1]} arbetar som {WORD_FOR[p['occupation']]}.")
    parts.append(f"Svar till kund{rng.randint(100, 999)}@exempel.se.")
    return " ".join(parts)


def k_for(p: dict, kept: dict) -> float:
    """kept maps attribute -> 'exact' | 'coarse' | None."""
    kommun = p["kommun"] if kept.get("kommun") == "exact" else None
    lan = p["kommun"][:2] if kept.get("kommun") == "coarse" else None
    if kept.get("ages") == "exact":
        ages = (p["age"],)
    elif kept.get("ages") == "coarse":
        lo = p["age"] // 10 * 10
        ages = tuple(range(lo, lo + 10))
    else:
        ages = None
    sex = p["sex"] if kept.get("sex") else None
    occ = p["occupation"] if kept.get("occupation") == "exact" else None
    return relink.count(kommun, ages, sex, occ, lan)


def main() -> None:
    rng = random.Random(SEED)
    people = draw_people(rng, N)
    rows = []
    for i, p in enumerate(people):
        shape = SHAPES[i % len(SHAPES)]
        if "occupation" in shape and p["occupation"] is None:
            shape = tuple(a for a in shape if a != "occupation")
        text = note(p, shape, rng)
        d = decide(text, mode="mask")
        assert d.action == "mask" and "@exempel.se" not in d.text, text
        masked = d.text

        ident = {a: "exact" for a in shape}
        g = relink.guard(masked)
        grind = dict(ident)
        for step in g.steps:
            if step == "age->band":
                grind["ages"] = "coarse"
            elif step == "kommun->län":
                grind["kommun"] = "coarse"
            elif step == "occupation removed":
                grind["occupation"] = None
        fixed = {a: ("coarse" if a in ("ages", "kommun") else (None if a == "occupation" else "exact")) for a in shape}
        rows.append(
            {
                "shape": shape,
                "ident": k_for(p, ident),
                "grind": k_for(p, grind),
                "fixed": k_for(p, fixed),
                "u_ident": 1.0,
                "u_grind": sum(v == "exact" for v in grind.values()) / len(shape),
                "u_fixed": sum(v == "exact" for v in fixed.values()) / len(shape),
                "missed": [a for a in shape if a not in g.quasi],
            }
        )

    def summary(sub, key):
        ks = [r[key] for r in sub]
        return (
            sum(1 / max(k, 1) for k in ks) / len(ks),
            sum(k < 1.5 for k in ks) / len(ks),
            sum(k < 5 for k in ks) / len(ks),
            sum(r[f"u_{key}"] for r in sub) / len(sub),
        )

    lines = [
        "# Re-identification after masking",
        "",
        f"{N} synthetic people drawn from SCB 2024 tables, one case note each. "
        "Attacker holds the full population register. Lower re-identification is better, higher utility is better.",
        "",
    ]
    groups = [("all notes", rows)] + [(" + ".join(s), [r for r in rows if r["shape"] == s]) for s in SHAPES]
    for title, sub in groups:
        if not sub:
            continue
        lines += [
            f"## {title} ({len(sub)} notes)",
            "",
            "| treatment | mean P(re-id) | unique (k<1.5) | k<5 | attributes kept exact |",
            "|---|---|---|---|---|",
        ]
        for key, label in (("ident", "identifiers-only"), ("grind", "egress-grind (k>=5)"), ("fixed", "fixed-k-anon")):
            p, u, k5, ut = summary(sub, key)
            lines.append(f"| {label} | {p:.3f} | {u:.1%} | {k5:.1%} | {ut:.0%} |")
        lines.append("")
    missed = sum(bool(r["missed"]) for r in rows)
    lines.append(
        f"Notes where the extractor missed an attribute that was in the text: {missed}/{N}. "
        "Those attributes reached the attacker at full precision and are counted that way above."
    )
    (HERE / "RELINK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
