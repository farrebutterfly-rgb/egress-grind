"""Put masked values back into the model's answer, including when it arrives in pieces.

A streamed answer can split a placeholder across chunks (`[se_person` then `nummer_1]`). The
StreamRestorer holds back only the tail that could still be the start of a placeholder and
releases everything before it, so the caller sees text as soon as it is safe to show.
"""

from __future__ import annotations

import json
import re

_PH = re.compile(r"\[[a-z_]+_\d+\]")
_MAX_PH = 40


def restore(text: str, mapping: dict[str, str], json_string: bool = False) -> str:
    """json_string: the text is the inside of a JSON string (tool arguments), so values are escaped."""
    if not mapping or not text:
        return text

    def sub(m: re.Match) -> str:
        val = mapping.get(m.group(0))
        if val is None:
            return m.group(0)
        return json.dumps(val, ensure_ascii=False)[1:-1] if json_string else val

    return _PH.sub(sub, text)


class StreamRestorer:
    def __init__(self, mapping: dict[str, str], json_string: bool = False):
        self.mapping = mapping
        self.json_string = json_string
        self.buf = ""

    def feed(self, piece: str) -> str:
        self.buf += piece
        cut = len(self.buf)
        i = self.buf.rfind("[")
        if i != -1 and "]" not in self.buf[i:] and len(self.buf) - i <= _MAX_PH:
            cut = i
        out, self.buf = self.buf[:cut], self.buf[cut:]
        return restore(out, self.mapping, self.json_string)

    def flush(self) -> str:
        out, self.buf = self.buf, ""
        return restore(out, self.mapping, self.json_string)
