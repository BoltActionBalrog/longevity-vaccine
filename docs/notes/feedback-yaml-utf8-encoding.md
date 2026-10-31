---
name: feedback-yaml-utf8-encoding
description: Don't edit patches.yaml (or any UTF-8 file) with a Python open()/write() round-trip on Windows — it corrupts non-ASCII and crashes apply
type: feedback
---

`D:\SmacxUi\work\patches\patches.yaml` contains UTF-8 non-ASCII (em-dashes `—` etc. in comments/descriptions). Editing it with a quick Python script using bare `open(p).read()` / `open(p,"w").write(s)` corrupted the encoding (em-dash → stray `0x97`), and `apply_patches.py` (which reads UTF-8) then crashed with `UnicodeDecodeError`, leaving the live binary at **pristine/unpatched** (a real outage — the crash-fix and everything else gone).

**Why:** on Windows the default text encoding is cp1252, not UTF-8, so a read/write round-trip re-encodes multibyte UTF-8 chars into invalid single bytes.

**How to apply:** prefer an editor that preserves UTF-8 for patches.yaml. If scripting is necessary, always pass `encoding="utf-8"` to both `open()` calls, or operate in binary mode (`"rb"`/`"wb"`) and only touch ASCII regions. After any programmatic edit, verify with `yaml.safe_load` AND re-apply + check the MD5 before moving on. Related: [[project-smac-modal-scaling]].
