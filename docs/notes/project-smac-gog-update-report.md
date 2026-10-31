---
name: project-smac-gog-update-report
description: GOG shipped a newer SMACX build (13 Nov 2024) than the one our patch targets. Pre-update prep to make re-porting cheap. Checklist items 1-4 DONE (2026-05-29): artifacts archived, provenance pinned, signature relocator built, symbolic catalog generated. Remaining: item 5 (PRACX source) + the actual GOG update, both user-driven later.
type: project
---

**Situation:** All our binary patching ([[project-smac-menu-strip-scaling]], [[project-smac-win11-24h2-fix]]) targets a specific PRACX-patched `terranx.exe`. GOG released a NEWER build (patch note: *"Update (13 November 2024): Added a second executable for launching PRACX, Validated stability, Verified compatibility with Win 10/11, Added Cloud Saves."*) the maintainer has NOT installed. User will update **manually, later**; this prep makes the re-port cheap. **Prep items 1-4 are now DONE; the update itself is not yet applied.**

## DONE 2026-05-29 — prep executed (items 1-4)
- **Archive created at `archive\v2024-08-19\`** (outside the game dir, survives a GOG update/verify). Contains: `game-binaries/` (cc659f `.orig`, 2d0b14 `.bak`, 27cb07 patched, both terran.exe), `pracx-toolchain/` (pracxpatch v1.11, axstart, Ip, PRACX.v1.11.Uninstaller, change log, axstart border.pcx), `config/` (both .Ini, goggame .info/fileList, goglog), and a full copy of `work/` (Ghidra DB included, 263M). Archived binaries MD5-verified against source.
- **`PROVENANCE.md` + `provenance.yaml`** in the archive root: md5+sha256+size for every exe, GOG gameId `1207658936`, PRACX v1.11, SMAC linker ts `0x385E91FF` (constant, NOT a build discriminator — use hashes).
- **Baseline hashes pinned into `patches.yaml` `target:` block** (md5+sha256 for 2d0b14, pristine_* for cc659f, patched_md5 for 27cb07).
- **Signature relocator built** — see below.
- **Symbolic catalog** at `D:\SmacxUi\work\patches\CATALOG.md` (every site by function+pattern+intent, grouped; re-port reference so shifted VAs can be re-hunted).

## THE provenance finding (settles the old cc659f-vs-2d0b14 ambiguity)
The two "pristine" candidates differ by **exactly 39 bytes**, all OUTSIDE every patch site:
- `_SELFMOD` VA `0x668160`: in 2d0b14/27cb07 a PRACX hook stub — `E8 05 00 00 00` (call-over-string) + literal bytes `70 72 61 78` ("**prax**") + two `FF 15` indirect calls thru `[0x669120]`/`[0x669124]`. Zero padding in cc659f.
- `.data` VA `0x682000`: pointer-table slot[0] = `0x00668160` (ptr to that stub) in 2d0b14/27cb07; NULL in cc659f.

So the delta is **one PRACX runtime hook + its registration pointer**, not our work. **Conclusion (corrects the earlier "cc659f is the single most important artifact" claim):**
- **2d0b14 (`.bak`) is the load-bearing baseline** — patcher's `EXPECTED_MD5`, all 38 sites+cave verify against it, it produced the working 27cb07 the maintainer runs. Shipping binary MUST contain this hook.
- **cc659f (`.orig`) is byte-identical to 2d0b14 across ALL of `.text` and the 0x668200 cave** (delta only in `_SELFMOD 0x668160` + `.data 0x682000`), so Ghidra analysis on it stays valid — but it LACKS the PRACX hook and is NOT a safe shipping base alone.
- Open (needs item 5 / PRACX source): is the stub baked on-disk by pracxpatch.exe or written at runtime (the `_SELFMOD` name hints runtime)? Either way 2d0b14 is the proven-good base.

## The signature relocator (the re-port lifeline) — `D:\SmacxUi\work\scripts\build_signatures.py`
Runner `run-build-signatures.bat`. Turns each patch site into a wildcard-masked byte signature so sites are found by CONTENT, not by (volatile) VA. No capstone in the bundled python, so operands are masked from two truths: (1) the site's own rel32/abs32 placeholder positions from apply_patches.ByteTemplate; (2) a byte heuristic over context — wildcard 4 bytes after E8/E9 (rel32), after FF15/FF25 (abs indirect), and any 4-byte LE in image VA range. Window auto-widens to uniqueness; genuine twins (the two near-identical blit loops) fall back to **ordinal** ("k-th of N matches in address order"), with a count-changed guard on locate.
- **Validated:** build self-validates **44/44** sites against 2d0b14; `--locate` finds **44/44 same** in cc659f (proves robustness to the 39-byte PRACX delta). In the patched 27cb07, 30 still match / 14 go MISSING (correct: our patches altered fixed bytes), 0 shifted/ambiguous — proves the sigs discriminate.
- **Output `D:\SmacxUi\work\patches\signatures.yaml`** (signature hex + mask + site_offset + ordinal/match_count per site).
- **Day-one re-port move on the new build:** `run-build-signatures.bat --locate <new pristine terranx.exe>`, review proposed VAs, then update patches.yaml VAs.

## UPDATE LANDED 2026-05-29 — outcome: BEST CASE, no re-port needed
The GOG 13-Nov-2024 update is **purely additive** — it overwrote NO existing game exe. Our patched `terranx.exe` (27cb07) is untouched and still works.
- **New `terranx_PRACX.exe` MD5 = `2d0b1438` = byte-identical to our 2d0b14 baseline** (0 bytes differ; relocator 44/44 same; `_SELFMOD` present at RVA 0x264000). The feared runtime-loader/no-_SELFMOD scenario did NOT happen — PRACX still statically baked. Our patch applies to it unchanged. `terran_PRACX.exe` = `ffeeb6bd` = our existing terran.exe.
- Update also added **`ddraw.dll` (2.8MB DDrawCompat shim, md5 f64472b6)** loaded by all exes (Win10/11 compat), and **`terranx_widescreen.bat`/`terran_widescreen.bat`** which just flip `DirectDraw=0` in the .ini and launch **`terranx.exe`/`terran.exe`** (our patched files) — DDrawCompat framebuffer *stretch*, NOT true UI scaling, so our patcher keeps distinct value.
- **Launch map:** play tasks "Sid Meier's Alien Crossfire"→`terranx.exe` (OUR 27cb07) and `terranx_widescreen.bat`→`terranx.exe` (OUR) both run our scaled build. NEW task "SMAX PRACX"→`terranx_PRACX.exe` runs the UNPATCHED pristine build (no scaling). `terranx_PRACX`/`terran_PRACX` are sourced from Galaxy support cache (galaxyFileList F1649/F1650 absolute paths); base `terranx.exe` is tracked as F11.
- **RISK:** `terranx.exe` is in GOG's galaxyFileList (F11) + new `goggame-...hashdb` (md5 e68bdc72) → a future **Galaxy verify/repair could revert our 27cb07 terranx.exe to pristine**, wiping the patch. Recoverable: archive + trivial re-apply (baseline unchanged). Also TERRANX.ICD/TERRAN.ICD pristine blobs now present.
- Post-update build artifacts archived at **`archive\v2024-11-13-postupdate\`** (new-binaries/, launchers/, manifests/).
- **DECISION (user, 2026-05-29): `terranx_PRACX.exe` is DEFUNCT — we ignore it.** We will NOT patch it. Confirmed empirically that GOG's bundled `terranx_PRACX.exe` STILL has the Win11 24H2 hotseat freeze even with DDrawCompat active (see [[project-smac-win11-24h2-fix]]) — GOG's compat is rendering/DPI only, no CRT fix. So the new "SMAX PRACX" play task is broken on 24H2 and is not used. **Canonical build remains our patched `terranx.exe` (27cb07)**, launched via the "Sid Meier's Alien Crossfire" play task or `terranx_widescreen.bat` (both run terranx.exe). Don't relitigate patching terranx_PRACX.exe.

## Still TODO (user-driven, later)
- **Item 5:** grab PRACX source ([[reference-smac-modding]]) to learn whether pracxpatch bakes the 0x668160 stub on disk or PRACX writes it at runtime; needed only if the new build goes runtime-loader.
- **The actual GOG update** (manual). Post-update: hash+diff all new exes vs the provenance table; **check the new terranx.exe still has a `_SELFMOD` section** (RVA 0x264000 here) — if absent, PRACX went runtime-loader and the re-port is structural (add our own cave/section) not just offset relocation; then run the signature relocator.
- (Optional) exact Galaxy build ID lives in Galaxy's own DB, not in the game-dir files; not captured.

Related: [[project-smac-menu-strip-scaling]], [[project-smac-patcher-v02]], [[project-smac-win11-24h2-fix]], [[project-smac-ui-scaling]], [[reference-smac-modding]], [[project-smacx-baseline]]
