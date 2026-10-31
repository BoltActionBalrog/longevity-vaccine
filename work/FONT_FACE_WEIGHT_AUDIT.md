# Font face / weight audit — SMACX UI-scaling patch set

Date: 2026-09-13 (addendum 2026-09-17: §3.14–3.17, the F9/F10 sites; §6 implementation 2026-09-17)
Status: **All 17 findings FIXED and baked 2026-09-17 (live exe bbcac547 + uimod.dll 7a19103f; §6), awaiting the
user's A/B at 4K + one non-4K resolution. The default-button-font probe (§1) resolved findings 4–8: Arial, not TNR.**

Scope note (2026-09-17): since the audit the HQ report family F2–F10 has been scaled end to end. F2–F8
were already covered (findings 3.2a–c, the `rw` FONTS / BIGFONT / `g_rw_font` sites; `rw_scale_kinds`
v9–v14 added no new font site — its 20 label pushes are the same `g_rw_font`). F9 Planetary Monument
(`mon_scale`, closed 2026-09-14) and F10 Hall of Fame (`hof_scale` v6, closed 2026-09-17) are NEW bakes
in `assemble_mon.py` with their own font thunks; they were audited on 2026-09-17 and are findings
3.14–3.17 below. Both screens use their own scale numerator (`mon_scale_num` = min(fl(16·ScreenH/768), fl(16·ScreenW/1024)),
UNCLAMPED, so num = 45 @4K, 30 @1440, 25 @1600×1200, 22 @1920×1080), which is why the HOF painter fonts
leave the 40-px pool at 4K where the popup g never does.

Trigger: the Longevity Mod Preferences row rendered in a different weight than the stock option rows at
non-4K resolutions. The user asked whether the same mistake (a bold/non-bold or face mismatch versus
vanilla) exists anywhere else we install a font. A read-only static audit of every font site in the
patch set (patches.yaml thunks, assemble_*.py sources, uimod.dll) against the pristine engine's font
setup followed. Nothing under `D:\SmacxUi` was modified by the audit.

## 1. The engine's font-pool rule

`config_popups` builds the `find_font` pool at **0x588BB0–0x588BFD** (pristine bytes), for each of the
12 table sizes {40,36,32,24,22,20,18,16,14,12,10,8} × 4 variants:

```
0x588bc1  mov ecx,[0x691b30]      ; "Arial Narrow"
0x588bc7  cmp eax,0xc / jg        ; size > 12 keeps Narrow
0x588bcc  mov ecx,[0x691b2c]      ; else "Arial"
0x588bd4  cmp eax,0xc / setg dl   ; dl = (size>12)
0x588bda  or  edx,[esi]           ; | font_variant_flags[v]  (= {0,1,2,4} @0x68F250)
0x588be1  call Font_init(name, size, flags)
```

The rule this encodes:

- **Every pool font above 12 px is "Arial Narrow" and BOLD (flags `1|v`) for variant 0 and variant 1
  alike**; variant 2 is bold-italic (flag 3). "Regular" does not exist above 12 px in the pool.
- **Every pool font of 12 px or less is plain "Arial" with weight = variant** (v0 regular, v1 bold,
  v2 italic — not a third face).

Two failure classes follow, and they drive nearly every finding below:

1. **Pool crossing.** Scaling a ≤12 px native font by asking the pool for `find_font(size·g/16, v)`
   silently changes the face (Arial → Arial Narrow) *and* the weight (v0/v2 gain bold) at every
   g ≥ 18 (i.e. every scaled resolution: g = 22 @1920×1080, 25 @1600×1200, 40 @4K).
2. **Bold drop.** Replacing a >12 px pool font with a direct `Font_init(name, s, v)` that does not
   OR in the bold bit loses the bold the pool would have given.

Side note on the Longevity row bug that triggered the audit: above 12 px `find_font(x,0)` and
`find_font(x,1)` are the same weight, so that defect was size-driven (find_font snapping 25 → 24), not
weight-driven.

### Second engine fact — the BaseButton default label font

The BaseButton default label font `[0x9B8E34]` is set once by `0x62D471` (`push edi` = static Font
0x7D3948, pushed by WinMain @0x45FA3E). Its static ctor 0x45F940 → 0x618EE0 leaves HFONT 0, so
`0x6195F5–0x619600` Font_inits it **"Times New Roman", 12, style 0** (which is also `g_default_font`
0x9BB484). `popups_normal` passes NULL (0x588645–0x588653 → no-op); only `popups_tutorial` (0x5888BC)
later changes it to `find_font(12,0)` = Arial 12 regular. So every FlatButton built at startup
(PrefWin, MainWin, MultiWin, TutWin) draws its label in **TNR 12 regular** natively unless its owner
calls `set_font`.

**Confidence: static trace; needs one runtime confirmation** (`GetObject` on `[[btn+0x970]+8]` →
LOGFONT `lfFaceName`/`lfWeight` at g=16, or a pristine 1024×768 shot of the Preferences window)
before acting on findings 4–8.

**Runtime confirmation 2026-09-17 (`hook_btnfont_probe.js` v2 at 1024×768, gdi32 CreateFontIndirectA
tap + GetObject reads; `work\frida_btnfont_probe.log`).** The trace was half right: the static Font
0x7D3948 IS created "Times New Roman" −12 weight 0 by its ctor, but it is then **re-Font_init'd
"Arial" 12 style 0** during startup, before `config_popups` builds the pool (log lines 4–5). Live reads:

| object | GetObject | meaning |
|---|---|---|
| COUNCIL button `+0x970` = 0x7D3948 | Arial −12 weight 0 | the default label font is **Arial 12 regular**, not TNR |
| PrefWin FlatButton #0 `+0x970` = 0x6E84B4 | Arial −14 weight 700 | the Preferences buttons use the **shared Arial 14 bold** (BaseWin's), not the default |
| HUD M / I `+0x970` = 0x7CFE8C | Arial −14 weight 700 | **Arial 14 bold** (not the fA12 our lever installed) |
| `[0x9B8E34]` | NULL | the trace's "default pointer" global is not what the buttons read |

So findings 4, 6, 7 are pool-crossing fixes to Arial fl(12g/16) regular (`t_ffn(12,0)`), and 5 and 8 are
Arial fl(14g/16) bold (`t_fdirect_a14b`). Laws: `BUTTON_DEFAULT_FONT`, `BUTTON_SHARED_A14B`,
`button_default_font_law`, `button_a14b_font_law`. The probe's first version attached inside
`Font_init` at a baked detour's resume address and crashed the boot (hazard recurrence, memory
`feedback-frida-attach-branch-target`); v2 hooks no engine code.

## 2. The reference pattern (already correct in the patch set)

`work\scripts\assemble_tech.py` `asm_tech_ff` (lines ~437–500) does it right: it derives the face and
flags from the **native** size and variant (`cmp esi,12 → narrow+1`, `or edx,[edi*4+0x68F250]`), then
calls `Font_init` at the **scaled** size. The recipe:

```
name  = native > 12 ? "Arial Narrow" : "Arial"
flags = (native > 12) | font_variant_flags[v]        ; font_variant_flags = {0,1,2,4} @0x68F250
size  = fl(native * g / 16)
Font_init(scratch, name, size, flags)
```

For natives that vanilla `Font_init`s directly (not through the pool — e.g. Arial 10 style 0,
Arial 14 style 1, TNR 12 style 0) keep the site's own name/style and scale only the size.

## 3. Findings — mismatches versus vanilla (ranked by visibility)

Column key: **WEIGHT** = bold where vanilla is regular (or vice versa); **FACE** = Arial vs Arial
Narrow (or TNR); **SIZE-LAW** = the native size used as the scaling base is not vanilla's.

### 3.1 Tooltips (every tooltip, all g ≥ 18)
- Site: `thunk_bubble_font` (patches.yaml ~line 1799; site config_popups 0x588F42
  `89 0D 54 7A 9B 00`).
- Vanilla: `find_font(12,0)` = **Arial 12 regular** (0x588F12/0x588F42).
- Ours: `find_font(fl(12g/16), 0)` → g=22: 16, g=25: 18, g=40: 32 = **Arial Narrow bold**.
- Defect: **WEIGHT + FACE** (pool crossing). Confidence: high.

### 3.2a HQ report list rows and F-screen text (all g > 16)
- Site: rw `FONTS` idx 0–3, 10 (`assemble_rw.py:77`, `asm_rw_init_leave` ~L293–320).
- Vanilla: `find_font` (10,0) (12,0) (12,2) (12,1) (11,0) = Arial regular / regular / italic / bold /
  regular (`_rw_dec_dispatch.txt:158–178`).
- Ours: `find_font(fl(sz·g/16), st)` → all cross 12 → Arial Narrow bold / bold-italic.
- Defect: **FACE** for all five; **+ WEIGHT** for the v0/v2 ones (pool crossing). Confidence: high.

### 3.2b HQ report large headers (g=40: all four; g=25 and g=22: the 32-px one)
- Site: rw `BIGFONT_IDX` 11–14: (26,0) (18,2) (22,0) (32,0).
- Vanilla: pool Arial Narrow **bold** (24/18/22/32, flags `1|v`).
- Ours: when s(sz) > 40 the code falls to `Font_init("Arial Narrow", s, st)` with st = 0/2/0/0 →
  **regular** / plain italic.
- Defect: **WEIGHT** (bold drop). Confidence: high.

### 3.2c HQ report / kinds console button labels
- Site: rw `g_rw_font` (`assemble_rw.py` ~452) → the 30 label pushes that replace 0x6E84B4.
- Vanilla: `Font_init("Arial", 14, 1)` @0x41F2A1 = Arial 14 bold.
- Ours: `find_font(g, 0)` = Arial Narrow g bold.
- Defect: **FACE** (Arial → Arial Narrow) **+ SIZE-LAW** (g ≠ fl(14g/16)). Confidence: high.

### 3.3 COMMLINK panel rows / VOTES and the header (all g > 16)
- Site: `thunk_comm_setfont` / `hm_scalefont` (`assemble_hudmenu_scale.py` ~L140–190, off-table
  branch).
- Vanilla: MultiWin row_font `Font_init("Arial", 10, 0)` @0x479FE4; hdr_font `("Arial", 14, 1)`
  @0x479FFA.
- Ours: off-table → `find_font(round((cell−3)g/16), 1)` = Arial Narrow bold.
- Defect: rows **WEIGHT + FACE**; header **FACE**. Confidence: high.

### 3.4 COUNCIL / MP-time buttons
- Site: `thunk_comm_btnfont` (hudmenu 0x60A0).
- Vanilla: the default button font (TNR 12 regular per §1; no `set_font` in 0x47A230–0x47A330).
- Ours: `find_font(round(12g/16), 1)` = Arial Narrow bold.
- Defect: **WEIGHT + FACE**. Confidence: pending the TNR runtime confirmation.

### 3.5 Preferences window buttons (all 15) + the DLL's Longevity tab/label buttons
- Site: `thunk_pref_show` (`assemble_prefwin.py:436–455`) and the DLL's tab/label font copy
  (`src\uimod\src\prefs.cpp:343–345`).
- Vanilla: the default button font (TNR 12 regular per §1).
- Ours: `find_font(fl(14g/16), 1)` = Arial Narrow 20/22/36 bold.
- Defect: **SIZE-LAW (14 ≠ 12) + WEIGHT + FACE**. Confidence: pending the TNR runtime confirmation.

### 3.6 Scenario-editor diplomacy dialog buttons
- Site: `thunk_diplo_btnfont` (`assemble_scenedit.py:236–255`).
- Vanilla: the default button font (TNR 12 regular, or Arial 12 regular if a TUTOR popup has run).
- Ours: `find_font(su(14,g), 1)` = Arial Narrow bold.
- Defect: **SIZE-LAW + WEIGHT + FACE**. Confidence: pending the TNR runtime confirmation.

### 3.7 TutWin TOUR / Close button labels
- Site: `thunk_tutbtn_post` (`assemble_tutbtn_post.py:66–78`).
- Vanilla: the default button font (TNR 12 regular per §1).
- Ours: `find_font(scale_px(12,g), 0)` → ≥14 = Arial Narrow bold.
- Defect: **WEIGHT + FACE**. Confidence: pending the TNR runtime confirmation.

### 3.8 HUD M / I buttons (minor)
- Site: `thunk_hud_btnfont` (`assemble_hud_widgets.py:426`).
- Vanilla: the default button font (TNR 12 regular per §1).
- Ours: MainWin fontA12 = Arial 12 regular (scaled).
- Defect: **FACE** only. Confidence: **UNSURE** — unclear whether these buttons draw any text at all;
  also pending the TNR confirmation.

### 3.9 Base screen (BaseWin) FlatButton labels
- Site: `thunk_bw_btnfont` (`assemble_basewin.py:asm_btnfont`).
- Vanilla: `+0x970 == 0x6E84B4` = Arial 14 **bold**.
- Ours: `find_font(fl(14g/16), 1)` = Arial Narrow bold.
- Defect: **FACE** only (weight and size law correct). Confidence: high.

### 3.10 Base-info name text (base screen)
- Site: `t_findfont` (`assemble_strip_content.py` ~L984; sites 0x415D17/0x415D5D `push 1; push ebx`,
  ebx from 32 shrinking to fit).
- Vanilla: pool `find_font(S,1)`: S > 12 → Arial Narrow bold.
- Ours: `Font_init("Arial", s(S), 1)` = Arial bold.
- Defect: **FACE** whenever the native S > 12 (the fit loop can drop S to ≤12, where Arial is
  correct). Confidence: high.

### 3.11 Preferences-window-owned text (the seven ffscale slots)
- Site: `thunk_pref_ffscale` (7 sites 0x48D90A–0x48D962: (10,0) (12,0) (12,2) (12,1) (14,0) (14,2)
  (14,1)).
- Vanilla: Arial regular / regular / italic / bold for the four ≤12 slots; Arial Narrow bold ×3 for
  the 14s.
- Ours: size × g/16 → the four ≤12 slots cross to Arial Narrow bold(/bold-italic); the three 14s MATCH.
- Defect: **FACE (+ WEIGHT for v0/v2)** for the slots at PrefWin +0x1B3B4..+0x1B3C0. Which on-screen
  text each slot draws still needs a reader census. Confidence: high on the font change, open on the
  visible element.

### 3.12 Multiplayer lobby (NetWin)
- Site: `thunk_nw_font` (yaml 0x48D0; sites 0x47F9EB/0x47FA6E `find_font(0xC,1)`, 0x480413,
  players.rowfont).
- Vanilla: Arial 12 bold (bodyfont); the hdr/row variants were not read.
- Ours: size × g/16 → Arial Narrow bold.
- Defect: **FACE** for the bodyfont sites. Confidence: **UNSURE** for the hdr/row sites (run
  `_disasm_va.py 0x47F9E0 0x47F9F0` and `0x480405 0x480418` to read them).

### 3.13 Datalinks tech page — title and category fonts
- Site: DL `PTR_ROWS` (`assemble_dl.py:199–205`).
- Vanilla: tech title `[0x8A40D4]` = ReportIf f16 (Arial Narrow 16 bold); category `[0x8A40C8]` =
  ReportIf f14 (Arial Narrow 14 bold).
- Ours: DL.F0 +0x1017C `Font_init("Arial", 18, 1)`; DL.F4 +0x1021C `("Arial", 14, 1)`.
- Defect: **FACE** (+ 16 → 18 SIZE-LAW on the title). Probably droppable now that `asm_rw_init_leave`
  scales the ReportIf fonts themselves. Confidence: high.

### 3.14 Planetary Monument (F9) plaque / caption text (all num > 16) — added 2026-09-17
- Site: `t_mon_font` (`assemble_mon.py` `asm_mon_font`, detour @0x47374D on the painter's
  `mov eax,[0x8A40BC]`; law `MON_FONT_PLAQUE = 12`).
- Vanilla: `[0x8A40BC]` = ReportInfc fonts[1] = `find_font(12,0)` = **Arial 12 regular** (it also feeds
  the +0xA44 line height, `_mon_static_map.md:498`).
- Ours: `find_font(fl(12·num/16), 0)` → num=22: 16, 25: 18, 30: 22, 45: 33 = **Arial Narrow bold**.
- Defect: **WEIGHT + FACE** (pool crossing, the tooltip class). Confidence: high (static trace of the
  law + the pool rule; not yet A/B'd against a pristine shot).

### 3.15 Planetary Monument (F9) button label
- Site: `t_mon_btn` (`asm_mon_btn`; law `MON_FONT_LABEL = 14`).
- Vanilla: the button's `+0x970` = `0x6E84B4` = `Font_init("Arial", 14, 1)` = Arial 14 **bold**.
- Ours: `find_font(fl(14·num/16), 1)` = Arial Narrow bold.
- Defect: **FACE** only (weight and size law correct; same class as 3.9 BaseWin). Confidence: high.

### 3.16 Hall of Fame (F10) painter fonts above the pool (num ≥ 30, i.e. 1440p and 4K)
- Site: `t_hof_fonts` (`asm_hof_fonts`; laws `HOF_FONTS = (14, 16, 22)`, `HOF_FONT_TABLE_MAX = 40`);
  the three cells feed 5 painter detours `t_hof_font_*` on `[0x8A40C8]` f14 (body/scores ×3),
  `[0x8A40D4]` f16 (panel titles), `[0x8A40EC]` f22 (title band).
- Vanilla: pool `find_font(14|16|22, 0)` = Arial Narrow **bold** (flag `1|0`).
- Ours: `find_font(fl(sz·num/16), 0)` while ≤ 40 → Arial Narrow bold = MATCH (1600: 21/25/34;
  1920: 19/22/30). Above 40 the code falls to `Font_init(scratch, "Arial Narrow", n, 0)` = **regular**:
  f22 → 41 @1440p; f16 → 45 and f22 → 61 @4K (f14 → 39 stays in the pool).
- Defect: **WEIGHT** (bold drop, the 3.2b class) on the title band at 1440p, and on both the band and
  the three panel titles at 4K. Confidence: high (arithmetic from the laws; `hof_font_scratch`).

### 3.17 Hall of Fame (F10) CLOSE button label
- Site: `t_hof_btn` (`asm_hof_btn`; law `HOF_FONT_LABEL = 14`).
- Vanilla: `0x6E84B4` = Arial 14 **bold**.
- Ours: `find_font(fl(14·num/16), 1)` = Arial Narrow bold.
- Defect: **FACE** only (same as 3.15 / 3.9). Confidence: high.

Coupling note: the HOF bake writes its row pitch (+0xA44) from the installed body font, so fixing 3.16
changes the pitch with it (re-verify rows after). The Monument's +0xA44 is computed by the engine at
0x47238B from the native `[0x8A40BC]` (that site is not detoured; only the painter load at 0x47374D is),
so 3.14 does not move it — check the plaque's line pitch when 3.14 is fixed.

### Summary table

| # | Screen / element | Site | Vanilla | Ours | Defect |
|---|---|---|---|---|---|
| 1 | Every tooltip | thunk_bubble_font | Arial 12 regular | AN bold 16/18/32 | WEIGHT+FACE |
| 2a | HQ report list rows, F-screens | rw FONTS 0–3,10 | Arial 10/12 reg/ital/bold | AN bold(-ital) | FACE (+WEIGHT v0/v2) |
| 2b | HQ report headers | rw BIGFONT_IDX 11–14 | AN bold | AN regular/italic when s>40 | WEIGHT |
| 2c | HQ report / kinds buttons | rw g_rw_font | Arial 14 bold | AN g bold | FACE + SIZE-LAW |
| 3 | COMMLINK rows/VOTES, header | thunk_comm_setfont | Arial 10 reg / Arial 14 bold | AN bold | WEIGHT+FACE / FACE |
| 4 | COUNCIL / MP-time buttons | thunk_comm_btnfont | TNR 12 regular* | AN bold | WEIGHT+FACE* |
| 5 | Preferences buttons + Longevity tab/label | thunk_pref_show, prefs.cpp | TNR 12 regular* | AN 14g/16 bold | SIZE-LAW+WEIGHT+FACE* |
| 6 | Scen-editor diplo buttons | thunk_diplo_btnfont | TNR/Arial 12 regular* | AN bold | SIZE-LAW+WEIGHT+FACE* |
| 7 | TutWin TOUR/Close | thunk_tutbtn_post | TNR 12 regular* | AN bold | WEIGHT+FACE* |
| 8 | HUD M/I buttons | thunk_hud_btnfont | TNR 12 regular* | Arial 12 reg scaled | FACE (UNSURE) |
| 9 | BaseWin buttons | thunk_bw_btnfont | Arial 14 bold | AN bold | FACE |
| 10 | Base-info name text | strip t_findfont | AN bold (S>12) | Arial bold | FACE |
| 11 | PrefWin-owned text (4 slots) | thunk_pref_ffscale | Arial ≤12 reg/ital/bold | AN bold | FACE (+WEIGHT) |
| 12 | MP lobby | thunk_nw_font | Arial 12 bold | AN bold | FACE (hdr/row UNSURE) |
| 13 | Datalinks tech title/category | DL PTR_ROWS | AN 16/14 bold | Arial 18/14 bold | FACE (+SIZE) |
| 14 | Monument (F9) plaque text | t_mon_font | Arial 12 regular | AN bold 16/18/22/33 | WEIGHT+FACE |
| 15 | Monument (F9) button | t_mon_btn | Arial 14 bold | AN bold | FACE |
| 16 | Hall of Fame (F10) band + panel titles | t_hof_fonts | AN bold | AN regular when n>40 (1440p band; 4K band+titles) | WEIGHT |
| 17 | Hall of Fame (F10) CLOSE | t_hof_btn | Arial 14 bold | AN bold | FACE |

\* = rests on the TNR-12 default-button-font static trace (§1), pending runtime confirmation.
Rows 14–17 added 2026-09-17 (the F9/F10 bakes postdate the audit).

## 4. Verified correct (MATCH)

| Site | Vanilla | Ours | Note |
|---|---|---|---|
| Button labels 0x6E84B4 → DL.F3 +0x101F4 | Arial 14 bold | Arial 14 bold | |
| `thunk_popup_setup_fonts` / `thunk_build_scaled_fonts` + 9 popups_normal rewires | 16 v0/v1 = AN bold (flag 1), v2 = AN bold-italic (3) | scratch0 flag 1 (v0=v1), scratch2 flag 3 | variant-consistent |
| `thunk_faction_bodyfont`, `thunk_btnfont_enter/leave` | AN bold trio `[0x9B8DA8]` @0x600CF8 | g_pf trio | |
| `thunk_tutwin_fonts` | popups_tutorial trio = InterludeFontSize(16) v0/1/2 | `find_font(g,0/1/2)` same order | |
| `thunk_interlude_font` | 0x945770/FC/F8 = v0/v1/v2 of InterludeFontSize (16, 0x588B02) | `find_font(s(16),0/1/2)` | |
| `thunk_credits_font` | ("Alpha Centauri",14,1) | (AC,s(14),1) | size-only |
| `thunk_push_scaled_font` (0x4ADC8C) | ("Arial",18,1) | ("Arial",s(18),1) | size-only |
| `thunk_hud_font`, `thunk_hud_fontobj`, `thunk_hud_fcache`, `thunk_map_font`, `thunk_pp_font/font10`, strip `t_fontinit` ×10, diplo `t_fontinit` ×5, `thunk_tech_fi`, SE 9 size imms, council 6 size imms, DW/scenedit size imms | — | size arg only | size-only |
| `thunk_bw_sf_14b/12p/12b/10b` + `t_sf_strip` (17+2 sites) | Arial per site: (14,1) ×7; (12,0) facilities/nutrients/misc; (12,1) psych/farm/energy/expenses; (10,1) commerce | `Font_init("Arial", s, same style)` | natives verified per site |
| `thunk_tech_ff` | pool law at native S | pool law at native S, calibrated | the reference pattern |
| `thunk_menu_layout` g_menu_font | `[0x9457EC]` = find_font(16,0) = AN bold | `find_font(min(g,40),1)` = AN bold | v0 ≡ v1 above 12 |
| `thunk_filedlg_titlefont` | find_font(14,v) AN bold | variant preserved | |
| DLL `CheckContentDraw` Longevity row | stock rows' font | see note | MATCH |

Longevity row note: at audit time the row used `find_font(g,1)` (= the def-dialog v1 above 12 px).
Later on 2026-09-13 it was re-based to the popups' scaled body font (`scratch0_font`, the
`thunk_build_scaled_fonts` Arial Narrow bold calibrated to cell = (20g)>>4), which is the Font the
stock option rows actually draw with — still a MATCH by construction.

## 5. Recommended fix

Per finding (from the audit):

- **1, 2a, 3, 4–7, 10, 11, 12**: replace the bare `find_font(scaled)` / `Font_init("Arial", …)` with the
  tech_ff recipe (§2) on a cave scratch Font: name and flags from the NATIVE size and variant, size =
  fl(native·g/16). For the natives that vanilla `Font_init`s directly (3–8) keep their own name/style
  (Arial 10 style 0, Arial 14 style 1, TNR 12 style 0). A shared cave helper
  `thunk_font_like_native(native, v, scaled)` would serve all of them.
- **2b**: `push {st | (1 if sz>12)}` in the BIGFONT branch.
- **2c / 9**: `Font_init("Arial", fl(14g/16), 1)` on a dedicated scratch Font (not `g_bw_font`, which is
  re-inited per `set_font`).
- **13**: drop the two PTR rows (title/category) if the ReportIf fonts are already scaled when the
  Datalinks screen opens; otherwise point them at Arial-Narrow-bold cave fonts.
- **14**: `t_mon_font` → the tech_ff recipe at native (12, v0): `Font_init(scratch, "Arial",
  fl(12·num/16), 0)` on a Monument cave scratch Font (keyed on `g_mon_num`, re-init only when num
  changes, like `t_hof_fonts`). Then re-check the plaque line pitch (+0xA44 is engine-computed from the
  native font, see §3 coupling note).
- **15 / 17**: `Font_init("Arial", fl(14·num/16), 1)` on a dedicated scratch (the 2c/9 fix) instead of
  `find_font(…,1)`.
- **16**: `push 1` (not `push 0`) in the above-40 `Font_init` branch of `t_hof_fonts` — one byte per
  font; the pool branch is already correct. Re-verify the HOF row pitch afterwards (it is derived from
  the body font).

Order of work:

1. Confirm the TNR-12 default button font at runtime (one Frida `GetObject` on `[[btn+0x970]+8]` at
   g=16, or a pristine 1024×768 Preferences shot). This decides whether findings 4–8 are real.
2. Findings 1–3 (most visible: tooltips, HQ report rows/headers/buttons, COMMLINK).
3. The rest (4–13), each on its own screen.

Every change follows the project rules: state the law in `work\scripts\scaling_laws.py` first, add an
emulation parity test under `work\tests\`, bake, then the user A/B-verifies against pristine at 4K and
at least one non-4K resolution (1920×1080 and/or 1600×1200). These screens are already user-verified
visually, so scope (all / top three / none) is the user's call.

---
Source: the font weight/face audit of 2026-09-13; its one-off scratch tooling (xref.py, callers.py,
bwsites.py, writers.py) was not kept.

## 6. Implementation (2026-09-17) — group `font_face_law`, live exe 3f1028b1

Source of truth: `scaling_laws.py` (`find_font_snap`, `font_pool_face`, `font_face_law`, `font_direct_law`,
`font_law_slot_key`, `FONT_LAW_SLOT_KEYS`); port `work\scripts\assemble_fontlaw.py` (+ `splice_fontlaw.py`);
parity `work\tests\test_fontlaw_asm_parity.py` (127 cases) + the touched bakes' parity tests; law sweep in
`test_scaling_laws.py`.

The helpers (pcave2 0x2E000..0x2E5B0):

| helper | contract |
|---|---|
| `t_ffn(S, v)` | the `find_font` drop-in that takes the NATIVE size + variant. g ≤ 16 → `find_font(S, v)`. S > 12 and fl(S·g/16) ≤ 40 → `find_font(n, v)` (the pool already gives Narrow+bold; sizes snap as before → zero change for the verified > 12 sites). Else a keyed cave slot Font_init'd with the pool's face law for the NATIVE size: name = S > 12 ? "Arial Narrow" : "Arial", style = (S > 12) \| font_variant_flags[v], size = fl(S·g/16) exact. |
| `t_ffn_num(S, v, num)` / `t_ffn_at(slot, S, v, num)` | the same at an explicit num / on a private slot (Monument, base-info name). |
| `t_fdirect_at(slot, S, style, num)` / `t_fdirect_a14b()` | a font vanilla `Font_init`s directly keeps its own face and style, size fl(S·num/16) — the `0x6E84B4` Arial 14 bold family on one shared slot. |

Slots are `Font 0x28 + num + key` (0x30); a slot re-inits only when (num, key) change (`Font_init` frees the old
HFONT itself). 15 shared slots keyed (S, v) + 5 private (a14b, bwname, mon_plaque, mon_btn, hof_btn).

Per finding:

| # | change |
|---|---|
| 1 | `thunk_bubble_font` → `t_ffn(12, 0)`: Arial 12 regular scaled (was Arial Narrow bold). |
| 2a/2b | `t_rw_init_leave`: all 15 report fonts → `t_ffn(S, st)` (the ≤ 12 ones = Arial regular/italic/bold; the headers keep bold above 40). Its own scratch branch is gone; layout FROZEN so no other rw thunk moved. |
| 2c / 9 | `g_rw_font` and `thunk_bw_btnfont` → `t_fdirect_a14b()` = Arial fl(14g/16) bold (was Arial Narrow at g / fl(14g/16)). |
| 3 | `hm_scalefont`: MultiWin row_font (MW+0x285C) → `t_ffn(10, 0)`, hdr_font (MW+0x2884) → `t_ffn(14, 1)`. |
| 10 | strip `t_findfont` → `t_ffn_at(g_font_bwname, S, 1, g)`: Arial Narrow bold for S > 12, Arial bold below. |
| 11 | `thunk_pref_ffscale` = `push t_ffn; ret` (the 7 sites push their native (S, v)). |
| 12 | `thunk_nw_font` = `push t_ffn; ret` (only the (12, 1) site at 0x47FA6E changes: Arial bold). |
| 13 | DL `PTR_ROWS` title/category dropped: the tech title/category draw with the ReportInfc f16/f14 (Arial Narrow bold), which `t_rw_init_leave` scales at desktop_init (0x58EECB) before any Datalinks open. Tech table 172 → 168 rows. |
| 14 / 15 | `t_mon_font` → `t_ffn_at(g_font_mon_plaque, 12, 0, num)` (Arial 12 regular at the Monument's num); `t_mon_btn` → `t_fdirect_at(g_font_mon_btn, 14, 1, num)`. |
| 16 / 17 | `t_hof_fonts` scratch branch pushes style `HOF_FONT_SCRATCH_STYLE = 1` (bold kept above 40); `t_hof_btn` → `t_fdirect_at(g_font_hof_btn, 14, 1, num)`. |
| 4 / 6 / 7 | (part 2, live exe bbcac547) `thunk_comm_btnfont`, `thunk_diplo_btnfont`, `thunk_tutbtn_post` v4 → `t_ffn(12, 0)`: Arial fl(12g/16) regular (the probed default label font; was Arial Narrow bold, the diplo one also on a 14 size law). |
| 5 | (part 2) `thunk_pref_show` → `t_fdirect_a14b()` for the 15 PrefWin buttons; the DLL's Longevity tab/label take the same slot when `.pcave2` is present (uimod.dll 7a19103f, `prefs.cpp`), else the v1 pool lookup. Arial fl(14g/16) bold (was Arial Narrow bold; the 14 size law was right). |
| 8 | (part 2) `thunk_hud_btnfont` v2 → canvas font0 = `t_fdirect_a14b()` (Arial fl(14g/16) bold; v1 installed fA12 = Arial 12 regular against a vanilla Arial 14 bold). |

Verification still owed (the user, vs pristine, 4K + 1600×1200 and/or 1920×1080): a tooltip; F2 rows/headers +
DATALINKS/CLOSE; F3–F8 rows; COMMLINK rows/VOTES/header; the Preferences pages' small text; the MP lobby body text;
a base screen's buttons + base name; F9 plaque + button; F10 band/panel titles + CLOSE; the Datalinks tech title/
category. Watch for fit/wrap changes where Arial replaced Arial Narrow (≈15–20 % wider at the same size).

### 6.3 Addendum — the SocialWin model-button label fit (2026-09-17, live 989a8086)

Not one of the 17 findings (the SE label font was already Arial 14 bold) but the one place where a SIZE law had to
become a runtime fit: vanilla's model buttons sit at ZERO slack ("THOUGHT CONTROL" = 140 px in Arial 14 bold vs a
146 − 6 px budget), so no fixed `fl(14·g/16)` survives GDI's per-size advance rounding at every g (19 px → 195 px vs a
194 px budget at 1920×1080 = ellipsis). Law `scaling_laws.se_label_fit` = the engine's own base-name idiom: step the
label Font down until every label's `Buffer_text_width` (the painter's measure) ≤ (R − L) − 6, then repaint.
WHERE it runs matters: `SocialWin_build` is MODAL (its tail `call [vtbl+0xE4]` = `Win_set_modal` returns only when the
screen closes), so a fit placed "after the build" (v1/v2, ret-swapped) ran after the user had left the screen and its
after-close repaint broke the SE hotkey. v3 hooks that `Win_set_modal` call (site `SocialWin_build.set_modal`,
0x4B3C4A): fit + repaint the measured buttons, then tail-jump into the modal. Thunk `t_se_labelfit` (font_face_law).
