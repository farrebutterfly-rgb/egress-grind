"""Can the person still be found after the identifiers are gone?

Masking a personnummer is not enough if the text that leaves still says "a 34-year-old woman in
Arjeplog who works as a veterinarian". This module reads the quasi-identifiers that are left
(kommun, age, sex, occupation), counts how many people in Sweden match them, and generalises the
text until at least `k_min` people do.

Attacker model: the attacker sees exactly what left the gateway and has a complete register of the
population with kommun, age, sex and occupation. In Sweden that is close to reality: name, age and
address per kommun are searchable on public sites built on the state register (SPAR). With k
matching people, the attacker's best guess is right with probability 1/k.

Counts come from SCB, not from a model:
  * people per kommun, one-year age and sex, 31 December 2024 (BE0101A/BefolkningNy), exact
  * employees per län, occupation (SSYK 2012, 3 digits), age group and sex, 2024 (AM0208C/YREG55BAS)
With an occupation, k is an estimate: the län's occupation share for that age group and sex is
applied to the kommun. That assumes occupations are spread evenly within a län. It is stated, not
hidden, and the benchmark reports results with and without occupation.
"""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib import resources

YEAR = 2024
K_MIN = 5


@cache
def _data() -> dict:
    with resources.files("egress_grind.data").joinpath("scb_2024.json.gz").open("rb") as f:
        d = json.loads(gzip.decompress(f.read()))
    pop: dict[tuple[str, int, str], int] = {}
    lan_pop: dict[tuple[str, str, str], int] = {}
    groups = d["aldersgrupper"]
    for key, n in d["pop"].items():
        r, a, k = key.split("|")
        age = 100 if a == "100+" else int(a)
        pop[(r, age, k)] = n
        g = _group(age, groups)
        if g:
            lan_pop[(r[:2], g, k)] = lan_pop.get((r[:2], g, k), 0) + n
    occ = {tuple(key.split("|")): n for key, n in d["occ"].items()}
    return {"pop": pop, "lan_pop": lan_pop, "occ": occ, "groups": groups, **{x: d[x] for x in ("kommuner", "lan", "yrken")}}


def _group(age: int, groups: list[str]) -> str | None:
    for g in groups:
        lo, hi = (int(x) for x in g.split("-"))
        if lo <= age <= hi:
            return g
    return None


# Common Swedish job titles, singular and definite forms, mapped to SSYK 2012 three-digit codes.
OCCUPATIONS = {
    "läkare": "221", "sjuksköterska": "222", "barnmorska": "223", "psykolog": "224", "veterinär": "225",
    "tandläkare": "226", "fysioterapeut": "227", "sjukgymnast": "227", "arbetsterapeut": "227",
    "undersköterska": "532", "vårdbiträde": "533", "personlig assistent": "534", "tandsköterska": "535",
    "tandhygienist": "325", "förskollärare": "234", "grundskollärare": "234", "lärare": "234",
    "gymnasielärare": "233", "fritidspedagog": "234", "barnskötare": "531", "elevassistent": "531",
    "universitetslektor": "231", "professor": "231", "socialsekreterare": "266", "kurator": "266",
    "präst": "267", "diakon": "267", "jurist": "261", "advokat": "261", "åklagare": "261", "domare": "261",
    "polis": "336", "polisman": "336", "revisor": "241", "redovisningsekonom": "331", "ekonom": "331",
    "systemutvecklare": "251", "programmerare": "251", "utvecklare": "251", "civilingenjör": "214",
    "ingenjör": "311", "arkitekt": "216", "journalist": "264", "tolk": "264", "bibliotekarie": "262",
    "musiker": "265", "skådespelare": "265", "konstnär": "265", "pilot": "315", "officer": "011", "soldat": "031",
    "snickare": "711", "murare": "711", "elektriker": "741", "rörmokare": "712", "vvs-montör": "712",
    "målare": "713", "svetsare": "721", "plåtslagare": "721", "mekaniker": "723", "bilmekaniker": "723",
    "lastbilschaufför": "833", "busschaufför": "833", "bussförare": "833", "taxichaufför": "832",
    "lokförare": "831", "kock": "512", "servitör": "513", "servitris": "513", "bartender": "513",
    "frisör": "514", "städare": "911", "lokalvårdare": "911", "butiksbiträde": "522", "kassör": "523",
    "lagerarbetare": "432", "brevbärare": "442", "väktare": "541", "montör": "821", "bagare": "761",
    "slaktare": "761", "skogsarbetare": "621", "lantbrukare": "613", "bonde": "613", "fiskare": "622",
    "receptionist": "422", "kundtjänstmedarbetare": "422", "fastighetsskötare": "515", "vaktmästare": "962",
    "verkställande direktör": "112", "vd": "112", "rektor": "141", "förskolechef": "142",
}  # fmt: skip

_FEMALE = r"kvinna|kvinnan|kvinnlig|hon|henne|flicka|flickan|tjej|tjejen|dam|damen|mamma|dotter"
_MALE = r"man|mannen|manlig|han|honom|pojke|pojken|kille|killen|herr|pappa|son"
_BAND = re.compile(r"(?<!\d)(\d{1,2})-(\d{1,2})(?:[- ]?år(?:ig|ige|iga|ing)?|[- ]?åring)(?!\w)", re.I)
_AGE = re.compile(r"(?<!\d)(\d{1,3})(?:[- ]?år(?:ig|ige|iga|ing|ingen)?|[- ]?åring(?:en)?)(?!\w)", re.I)
_BORN = re.compile(r"född (?:år )?(19\d\d|20[0-2]\d)(?!\d)", re.I)
_DECADE = re.compile(r"född på (19\d0|20[0-2]0)-talet", re.I)
_PLACE_PREP = r"(?:i|från|bor i|boende i|bosatt i|folkbokförd i|skriven i)"


@dataclass
class Quasi:
    kommun: tuple[str, str, str] | None = None  # (code, name, matched text)
    ages: tuple[int, ...] | None = None
    age_span: tuple[int, int] | None = None
    born: int | None = None
    lan: str | None = None
    sex: str | None = None  # "1" man, "2" woman
    occupation: tuple[str, str, int, int] | None = None  # (ssyk, word, start, end)
    spans: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def found(self) -> list[str]:
        return [n for n in ("kommun", "lan", "ages", "sex", "occupation") if getattr(self, n) is not None]


@cache
def _kommun_re() -> re.Pattern:
    names = sorted(_data()["kommuner"].values(), key=len, reverse=True)
    return re.compile(rf"(?<!\w){_PLACE_PREP}\s+({'|'.join(map(re.escape, names))})(?![\wåäö])")


@cache
def _occ_re() -> re.Pattern:
    words = sorted(OCCUPATIONS, key=len, reverse=True)
    return re.compile(rf"(?<!\w)({'|'.join(map(re.escape, words))})(?:n|en|na|erna)?(?!\w)", re.I)


def extract(text: str) -> Quasi:
    q = Quasi()
    d = _data()
    if m := _kommun_re().search(text):
        name = m.group(1)
        code = next(c for c, n in d["kommuner"].items() if n == name)
        q.kommun = (code, name, m.group(0))
        q.spans["kommun"] = m.span(1)
    if m := re.search(rf"(?<!\w){_PLACE_PREP}\s+({'|'.join(map(re.escape, d['lan'].values()))})(?!\w)", text):
        q.lan = next(c for c, n in d["lan"].items() if n == m.group(1))
    if m := _BAND.search(text):
        q.ages = tuple(range(int(m.group(1)), int(m.group(2)) + 1))
    elif m := _DECADE.search(text):
        dec = int(m.group(1))
        q.ages = tuple(range(YEAR - dec - 9, YEAR - dec + 1))
    elif m := _AGE.search(text):
        q.ages = (int(m.group(1)),)
        q.spans["ages"] = m.span(1)
    elif m := _BORN.search(text):
        q.ages = (YEAR - int(m.group(1)),)
        q.spans["born"] = m.span(1)
        q.born = int(m.group(1))
    f = re.search(rf"(?<!\w)(?:{_FEMALE})(?!\w)", text, re.I)
    ma = re.search(rf"(?<!\w)(?:{_MALE})(?!\w)", text, re.I)
    if f and not ma:
        q.sex = "2"
    elif ma and not f:
        q.sex = "1"
    if m := _occ_re().search(text):
        q.occupation = (OCCUPATIONS[m.group(1).lower()], m.group(1), *m.span())
        q.spans["occupation"] = m.span()
    return q


def count(
    kommun: str | None, ages: tuple[int, ...] | None, sex: str | None, ssyk: str | None, lan: str | None = None
) -> float:
    """Expected number of people in Sweden who match. Exact without occupation, estimated with it."""
    d = _data()
    regions = [kommun] if kommun else [c for c in d["kommuner"] if lan is None or c[:2] == lan]
    age_list = ages if ages else tuple(range(0, 101))
    sexes = [sex] if sex else ["1", "2"]
    total = 0.0
    for r in regions:
        for a in age_list:
            for s in sexes:
                n = d["pop"].get((r, a, s), 0)
                if not n:
                    continue
                if ssyk is None:
                    total += n
                    continue
                g = _group(a, d["groups"])
                if g is None:
                    continue
                emp = d["occ"].get((r[:2], ssyk, g, s), 0)
                base = d["lan_pop"].get((r[:2], g, s), 0)
                total += n * emp / base if base else 0
    return total


def k_of(q: Quasi) -> float:
    return count(
        q.kommun[0] if q.kommun else None,
        q.ages,
        q.sex,
        q.occupation[0] if q.occupation else None,
        q.lan,
    )


@dataclass
class Guard:
    text: str
    k_before: float
    k_after: float
    steps: list[str]
    quasi: list[str]

    @property
    def ok(self) -> bool:
        return self.k_after >= self.kmin

    kmin: float = K_MIN


def guard(text: str, k_min: float = K_MIN) -> Guard:
    """Generalise quasi-identifiers until at least k_min people match: exact age becomes a
    ten-year band, then the kommun becomes its län, then the occupation is removed."""
    q = extract(text)
    found = q.found
    if len(found) < 2:
        return Guard(text, float("inf"), float("inf"), [], found, k_min)
    k0 = k_of(q)
    steps: list[str] = []
    kommun = q.kommun[0] if q.kommun else None
    lan = q.lan
    ages = q.ages
    ssyk = q.occupation[0] if q.occupation else None
    k = k0
    out = text
    edits: list[tuple[int, int, str]] = []

    if k < k_min and ages and len(ages) == 1:
        if q.born:
            dec = q.born // 10 * 10
            ages = tuple(range(YEAR - dec - 9, YEAR - dec + 1))
            edits.append((*q.spans["born"], f"på {dec}-talet"))
        else:
            lo = ages[0] // 10 * 10
            ages = tuple(range(lo, lo + 10))
            edits.append((*q.spans["ages"], f"{lo}-{lo + 9}"))
        steps.append("age->band")
        k = count(kommun, ages, q.sex, ssyk, lan)
    if k < k_min and kommun:
        lan = kommun[:2]
        lan_name = _data()["lan"].get(lan, "länet")
        edits.append((*q.spans["kommun"], lan_name))
        kommun = None
        steps.append("kommun->län")
        k = count(kommun, ages, q.sex, ssyk, lan)
    if k < k_min and ssyk:
        edits.append((*q.spans["occupation"], "[yrke]"))
        ssyk = None
        steps.append("occupation removed")
        k = count(kommun, ages, q.sex, ssyk, lan)
    for s, e, rep in sorted(edits, reverse=True):
        out = out[:s] + rep + out[e:]
    return Guard(out, k0, k, steps, found, k_min)
