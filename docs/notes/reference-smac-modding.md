---
name: reference-smac-modding
description: External resources for Alpha Centauri reverse-engineering and modding — prior art for any binary-patching work
type: reference
---

Twenty years of SMAC community RE work exists. Don't start from zero on any binary-modding project for `terranx.exe`.

- **Thinker Mod** (induktio) — github.com/induktio/thinker — extensively documented offsets, structure definitions, header files mapping ~1000 game functions and globals. Best free source of named symbols for `terranx.exe`.
- **PRACX source** (DrazharLn) — open source; shows exactly which functions in `terranx.exe` are hooked and how patches are applied. Concrete example of working DLL injection against SMAC.
- **alphacentauri2.info forums** — decades of identified addresses, modding discussion, partial RE notes. Primary community hub.
- **Yitzi's patch** and **Scient's patch** — both have published address tables for the SMAC binary.
- **Will to Power (WTP) mod** — another active modding effort, may have additional offset info.

Related: [[project-smac-ui-scaling]]
