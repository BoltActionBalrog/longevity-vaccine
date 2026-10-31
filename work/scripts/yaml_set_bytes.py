#!/usr/bin/env python
"""Set one cave content's bytes line in patches.yaml, by id:
    py yaml_set_bytes.py <content-id> "<hex tokens / placeholders>" [--comment "<symbol trailing comment>"]
Replaces the `bytes:` line under `      - id: <content-id>` (exactly one match) and, with --comment,
the trailing `# ...` of the content's symbol line `  <content-id>: { ... }   # ...`.
UTF-8 + newline preserving (feedback-yaml-utf8-encoding)."""
from __future__ import annotations

import io
import os
import re
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "patches", "patches.yaml")


def main(argv: list[str]) -> int:
    cid, hexs = argv[0], argv[1]
    comment = argv[argv.index("--comment") + 1] if "--comment" in argv else None
    txt = io.open(P, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.split(nl)
    idx = [k for k, x in enumerate(lines) if x == f"      - id: {cid}"]
    if len(idx) != 1:
        print(f"PROBLEM: content {cid}: {len(idx)} matches")
        return 1
    k = idx[0]
    while not lines[k].startswith("        bytes:"):
        k += 1
        assert k < idx[0] + 4, cid
    lines[k] = f'        bytes: "{hexs}"'
    if comment is not None:
        sidx = [k for k, x in enumerate(lines) if re.match(rf"  {re.escape(cid)}:\s", x)]
        if len(sidx) != 1:
            print(f"PROBLEM: symbol {cid}: {len(sidx)} matches")
            return 1
        head = lines[sidx[0]].split("#", 1)[0].rstrip()
        lines[sidx[0]] = f"{head}   # {comment}"
    io.open(P, "w", encoding="utf-8", newline="").write(nl.join(lines))
    print(f"{cid}: bytes set ({len(hexs.split())} tokens){' + comment' if comment else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
