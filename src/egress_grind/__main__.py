"""python -m egress_grind verify audit.jsonl"""

import sys

from .audit import verify


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "verify":
        print("usage: python -m egress_grind verify <audit.jsonl>", file=sys.stderr)
        return 2
    ok, line = verify(sys.argv[2])
    print("chain intact" if ok else f"chain broken at line {line}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
