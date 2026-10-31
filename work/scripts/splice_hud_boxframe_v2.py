"""Splice thunk_hud_boxframe v2 (law hud_boxframe_rect: box-5 shared-painter panel split) into
patches.yaml. Byte-safe (read_bytes/write_bytes); only the one content entry's bytes change.
Run from work\\scripts AFTER `py assemble_hud_widgets.py` was run in a scratch dir and its
boxframe line saved to the path in argv[1]."""
import pathlib
import re
import sys

new_hex = pathlib.Path(sys.argv[1]).read_text().strip()
assert re.fullmatch(r"(?:[0-9A-F]{2} )*[0-9A-F]{2}", new_hex), "bad hex"
assert len(new_hex.split()) <= 0xE0
y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
data = y.read_bytes()
m = re.search(rb'(- id: thunk_hud_boxframe\r?\n\s*offset: 0x5740\r?\n\s*bytes: ")([^"]+)(")', data)
assert m, "entry not found"
start, end = m.start(2), m.end(2)
assert 0 < start < end
data = data[:start] + new_hex.encode() + data[end:]
y.write_bytes(data)
print("spliced", len(new_hex.split()), "bytes (was", len(m.group(2).split()), ")")
