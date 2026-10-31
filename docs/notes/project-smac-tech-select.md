---
name: project-smac-tech-select
description: SELECT RESEARCH GOAL (tech_pick) screen scaling arc — CLOSED 2026-08-28 USER-VERIFIED all-res + COMMITTED, group tech_scale build fa4d6a21; option (a) law, cell-calibrated fonts, devfill R-1/B-1; lessons in file
type: project
---

**CLOSED 2026-08-28: user-verified in-game at 4K/1600/1920 (+1024 native no-op measured), group tech_scale build fa4d6a212a72d7c69141ab8594e6f74e, COMMITTED.** Residual: the n>8 (9+ choices) path is baked but unexercised in-game. Proto v3b measured on law at 4K/1600/1920. Bake src `assemble_tech.py` (enter/immfix/inset/n8/n8ch/rb1/calib/fi/ff), `splice_tech.py`, parity `test_tech_asm_parity.py`; MD5 lock + 835 sites + CHANGELOG done. v2 MEASURED: layout/icon/F-fonts on law; §5 exact-fill (g_fc_exact) did NOT move devfill's R/B strokes (still R−1..R @K=2 / R @K=1) → v3 stub_rb1 passes a rect COPY with R−1/B−1 (measured compensation); LOGFONT read-back: pool name/title fonts are "Arial Narrow" w700 while g_hud_font_name = "Arial" → v3 calibrates find_font replacements with the pool face + pool cell. LESSON: the terranx.h note "Font_init: Arial (<=12) else Arial Narrow" is WRONG — the face is the name string passed; the pool (config_popups) uses "Arial Narrow", TechWin's own fonts use "Arial". v2 = stub_exact (rect→g_faction_scratch_rect + g_fc_exact→devfill) on strip+cells, 11-byte cut @0x48646C → stub_inset (c_rb=s(4)−1, L-clamp s(3)), 0x487DBD = s(26)−s(3), 9-byte cut @0x487981 → stub_n8, 4 Font_init sites → stub_fi + 8 find_font sites → stub_ff with CELL-calibrated Frida-allocated Font objects (LOGFONT-verified variant→flags), canvas read-back of stroke bytes. Stub bytes are hand-assembled (`cmp dword [esp+8],imm32` = 8 bytes!) and guarded by tests/test_tech_stubs.py (node-extract + capstone).
- v1 FINDINGS: (1) `thunk_box_thick_devfill` paints cell/strip RIGHT+BOTTOM strokes 1 px OUTSIDE the half-open rect (R−1..R @K=2, R @K=1; backdrop flush only because clipped) → v2 exact-fill (`g_fc_exact` +0x2554, `g_faction_scratch_rect` +0x1010) + canvas read-back; (2) native `+1` gutter costs 1.5 px/gap @4K → law **c_rb = s(4)−1** for the R/B inset (L-clamp stays s(3)); 11-byte cut @0x48646C; strip B one-cascade s(26); (3) **find_font snaps to font_size_table (cap 40)** → name 50→40, title 45→40 @4K (×2.0): fonts must be CELL-calibrated Font_init objects (popup precedent project_smac_font_calibration), stubs at the 8 find_font + 4 Font_init sites; n>8 `mov esi,edi` share → 9-byte cut. Left/top channel, strokes, icon, insets, unlock anchor = correct. Files: `work\_tech_static_map.md`,
`work\_tech_pixel_geometry.md`, `work\_tech_patch_plan.md` (site table = the bake spec),
`work\scripts\hook_tech_proto.js`, traces `work\frida_tech_census.log` (3 runs) → proto log `work\frida_tech_proto.log`;
laws `tech_*` in `scaling_laws.py` (+ `SL.tech*`), tests `tests\test_scaling_tech.py`; open item in the maintainer's work log.

- Window = STACK-LOCAL `TechWin` inside `tech_pick` 0x5BEB70 (ctor 0x484AC0, exec 0x486510, draw_cell 0x4863F0,
  draw_cell_content 0x484C60, unlock writer 0x484B80, vtbl 0x66CFCC; fields +0xA14 cw/+0xA18 ch/+0xA1C pad/+0xA24
  cols/+0xA28 rows/+0xA2C n; fonts +0xBBC stride 0x28). Symbols in terranx.h.
- **The full-width frame is VANILLA** (zero patches/PRACX in the cluster): screen-fit law cw=SW/cols−20 (≤SW/3),
  ch=max(cw·3/2,SH/2), overflow → SH/rows−40, W=(cw+1)·cols+1, H=(ch+1)·rows+0x1E; traces confirm at 1024/1600/4K
  (949×720 / 1525×1152 / 3765×2112, all @(37,24)); interior constants all native.
- **Law decision (user): option (a)** = vanilla's law at DEVICE density (each constant ×g/16) — never smaller than
  vanilla's picker; ≈ "vanilla on the virtual SW·16/g screen then ×g/16". 4K: cw910 ch980 W3645 H2037 @(97,61).
  Gutter rule: 1-byte `inc` gutters (pitch cw+1, W, hit-test, x+1 insets) stay native by law — draw and hit-test
  share them; pitch proportionality rides on cw.
- Icon lever: SCALE_NUM_G/DEN_G = ((16+s)·g)/256 realised IN PLACE by `tech_icon_imms` (DEN 16→256, s literal
  −10→6g−16, `and ebx,2`→2g, `add ebx,−14`→2g−16, `sar 4`→`sar 8`); iconW 80→201 @4K; thresholds 0x8C/0xB4 scaled.
- Proto mechanism = SE pattern: 48 verified-original immediates patched once at tech_pick entry (g>16 only) + 3
  box_sprite sites → thunk_box_thick_devfill; entry-only log hooks print LAW-vs-actual MATCH lines.
- Proto limits → bake: n>8 `add eax,−0x45` imm8 overflows g≥30 (proto SKIPs); edi=10 shared by pad / n>8 font /
  cols(n≥40); line pitch = scaled font's natural metric (measure vs fl(16g/16)); caption centring nudge not applied.
- `refs\pristine\TechSelect.png` is a 1024×768 view pillarboxed onto 4K at 2.8125× — measure it as native.

See (a private note), [[feedback-frida-attach-branch-target]], [[feedback-proportionate-scaling]],
[[project-smac-social-engineering]] (the proto/bake pattern this arc copies).
