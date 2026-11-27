"""Undo the ways a number gets disguised, on purpose or by accident, before it is scanned.

A model or an agent that has seen a personnummer can write it back as `8 5 0 3 1 2 - 2 3 8 7`, with
full-width digits, with zero-width characters between the digits, spelled out in Swedish words, or
base64-encoded inside a tool argument. The scanner only sees what this module gives it, so every
transform here is one evasion that stops working. The benchmark in bench/ measures each of them with and without this step.

Nothing here is used to rewrite the outgoing text. These are extra views for the scanner; a hit that
only shows up in one of them blocks the request (see policy.py), so positions never need mapping back.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"), None)
_SPACED_DIGITS = re.compile(r"(?<![\w])(?:\d[  ._]){5,}\d(?:[  ._]?[-+][  ._]?(?:\d[  ._]?){3}\d)?")
_NUM_WORDS = {
    "noll": "0", "nolla": "0", "ett": "1", "en": "1", "etta": "1", "två": "2", "tvåa": "2", "tre": "3", "trea": "3",
    "fyra": "4", "fyran": "4", "fem": "5", "femma": "5", "sex": "6", "sexa": "6", "sju": "7", "sjua": "7",
    "åtta": "8", "åttan": "8", "nio": "9", "nia": "9", "streck": "-", "minus": "-",
}  # fmt: skip
_W = "|".join(sorted(map(re.escape, _NUM_WORDS), key=len, reverse=True))
_SPELLED = re.compile(rf"(?<!\w)(?:(?:{_W})[\s,]+){{5,}}(?:{_W})(?!\w)", re.IGNORECASE)
_HOMOGLYPH = re.compile(r"(?<!\w)(?:[0-9OIl]{2})?[0-9OIl]{6}[-+]?[0-9OIl]{4}(?!\w)")
_HOMO_MAP = str.maketrans("OIl", "011")
_HEX = re.compile(r"^(?:[0-9a-fA-F]{2})+$")
_SIX = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_CUE = re.compile(r"personnummer|pers\.?nr|pnr|född|födelse|sista fyra|fyra sista|kontrollsiffr|samordningsnummer", re.I)
_FOUR = re.compile(r"(?<![\d-])(\d{4})(?![\d-])")
_B64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])")


@dataclass
class Views:
    """The texts the scanner looks at. `original` is always one of them."""

    original: str
    folded: str  # NFKC, zero-width removed, spaced-out digits joined
    decoded: list[str]  # base64 or hex segments that decode to readable text, and paired halves


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(ZERO_WIDTH)
    t = _SPELLED.sub(lambda m: "".join(_NUM_WORDS[w.lower()] for w in re.split(r"[\s,]+", m.group(0)) if w), t)
    t = _SPACED_DIGITS.sub(lambda m: re.sub(r"[  ._]", "", m.group(0)), t)
    return _HOMOGLYPH.sub(_unglyph, t)


def _unglyph(m: re.Match) -> str:
    s = m.group(0)
    return s.translate(_HOMO_MAP) if sum(c.isdigit() for c in s) >= 4 else s


def decode_segments(text: str) -> list[str]:
    out = []
    for m in _B64.finditer(text):
        s = m.group(0)
        candidates = []
        if _HEX.match(s) and not s.isdigit():
            candidates.append(lambda s=s: bytes.fromhex(s))
        candidates.append(lambda s=s: base64.b64decode(s + "=" * (-len(s) % 4), validate=True))
        for dec in candidates:
            try:
                txt = dec().decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
            if sum(ch.isprintable() for ch in txt) / max(1, len(txt)) > 0.9:
                out.append(txt)
                break
    return out


def paired_halves(text: str, window: int = 60) -> list[str]:
    """`född 850312, sista fyra 2387`: a six-digit date and a four-digit group close after it are
    joined into one candidate, but only when a word like personnummer, född or sista fyra is near.
    Without that cue, an order number next to a time of day would be paired too often (about one
    in twenty passes the check digit and date test by chance). The scanner decides if it is real."""
    out = []
    for m in _SIX.finditer(text):
        end = min(len(text), m.end() + window)
        if not _CUE.search(text, max(0, m.start() - 40), end):
            continue
        for n in _FOUR.finditer(text, m.end(), end):
            out.append(f"{m.group(1)}-{n.group(1)}")
    return out


def views(text: str) -> Views:
    folded = fold(text)
    decoded = [fold(d) for d in decode_segments(folded)]
    return Views(original=text, folded=folded, decoded=decoded + paired_halves(folded))
