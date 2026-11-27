"""Decides what happens to one outgoing request.

Three outcomes, in order of preference for the person whose data it is:

* ``block``  the request never leaves; the caller gets 403 with the entity types (never the values).
* ``mask``   personal data is replaced with numbered placeholders, the request goes out, and the
             placeholders in the answer are put back before the caller sees it. The cloud model
             never sees the value.
* ``pass``   nothing found.

Modes: ``strict`` (default) blocks hard types (personnummer, samordningsnummer, bank details)
and masks the rest; ``mask`` masks everything; ``block`` blocks on any hit. In every mode,
anything that only shows up after normalisation or decoding blocks, because a disguised
identifier is a stronger signal than a plain one, and masking a base64 blob in place is not
reliable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from svenska_pii import dom, hitta

from .normalize import views

HARD = {"SE_PERSONNUMMER", "SE_SAMORDNINGSNUMMER", "SE_ORGNR", "SE_BANKGIRO", "SE_PLUSGIRO", "SE_IBAN", "SE_KONTONUMMER"}


@dataclass
class Decision:
    action: str  # "block" | "mask" | "pass"
    types: dict[str, int] = field(default_factory=dict)
    via: str = "plain"  # "plain" | "normalised" | "decoded"
    text: str | None = None  # masked text when action == "mask"
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original value


def _count(hits) -> dict[str, int]:
    c: dict[str, int] = {}
    for h in hits:
        c[h.entity_type] = c.get(h.entity_type, 0) + 1
    return c


class Pseudonyms:
    """One table per request: the same value always gets the same placeholder, across messages."""

    def __init__(self):
        self.by_value: dict[str, str] = {}
        self.n = 0

    def placeholder(self, entity_type: str, value: str) -> str:
        if value not in self.by_value:
            self.n += 1
            self.by_value[value] = f"[{entity_type.lower()}_{self.n}]"
        return self.by_value[value]

    @property
    def mapping(self) -> dict[str, str]:
        return {ph: v for v, ph in self.by_value.items()}


def _mask(text: str, hits, table: Pseudonyms) -> str:
    out, pos = [], 0
    for h in sorted(hits, key=lambda h: h.start):
        if h.start < pos:
            continue
        out.append(text[pos : h.start])
        out.append(table.placeholder(h.entity_type, text[h.start : h.end]))
        pos = h.end
    out.append(text[pos:])
    return "".join(out)


def decide(text: str, mode: str = "strict", allowlist: list[str] | None = None, table: Pseudonyms | None = None) -> Decision:
    """See the module docstring for the modes."""
    v = views(text)
    plain = hitta(v.original, allowlist=allowlist)
    folded = hitta(v.folded, allowlist=allowlist) if v.folded != v.original else []
    decoded = [h for d in v.decoded for h in hitta(d, allowlist=allowlist)]

    plain_vals = {re.sub(r"\D", "", h.text) or h.text for h in plain}
    hidden = [h for h in folded + decoded if (re.sub(r"\D", "", h.text) or h.text) not in plain_vals]
    if hidden:
        return Decision("block", _count(hidden), via="normalised" if any(h in folded for h in hidden) else "decoded")
    if not plain:
        return Decision("pass")
    verdict = dom(plain)
    if mode == "block":
        return Decision("block", _count(plain))
    if mode == "strict" and verdict.stop:
        return Decision("block", dict(verdict.reason))
    table = table if table is not None else Pseudonyms()
    masked = _mask(v.original, plain, table)
    return Decision("mask", _count(plain), text=masked, mapping=table.mapping)
