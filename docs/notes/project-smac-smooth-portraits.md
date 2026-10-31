---
name: project-smac-smooth-portraits
description: Leader portraits: smooth composite enlarge in uimod.dll (portrait.cpp + portrait_law.h, law scaling_laws.portrait_enlarge), DLL 915b3586 (v2) deployed 2026-09-21, AWAITING user verify, NOT committed; AI upscaling and plain bilinear were REJECTED by the maintainer
type: project
---

User 2026-09-21: leader portraits look blocky on the face at non-4K. They are scanlined through the WHOLE image, so the citizen-face hybrid ([[project-smac-punishment-sphere]] sibling work) does not apply.

**Tried and rejected by the maintainer (do not re-propose):**
- Field-bilinear composite with a nearest-RGB palette fit: turned the dark greys on face/body a dull green. The colour drift was the FIT, not the resample — the game palette has few neutral dark greys; error diffusion cures it.
- Real-ESRGAN (dev-box toolchain `work/video-upscale/tools/realesrgan`): realesrgan-x4plus and realesr-animevideov3 on all 14 leaders (`work/_portrait_preview/all14/composites`). "Anime is the clear winner" but many were net worse; neither meets the quality bar. AI-upscaling the vanilla art is off the table unless a better model appears. (Superseded 2026-09-29: the maintainer supplied an HD art set; see [[project-smac-replaceable-portraits]].)

**Chosen (option C):** de-scanline (v2: dark rows GAINED back up by 256/ratio -- v1 rebuilt them from the bright field and smeared every one-row black accent (pupils, nostrils, mouth corners are single index-54/55 texels in the shipped art) into a 3-row blotch: 'black artifacting' on Santiago in the combat console; a despeckle rule would erase pupils, rejected; measured dark/bright luma ~0.75 SMAC, ~0.77-0.79 SMACX) -> Lanczos-3 (Q14 taps) -> light unsharp (3x3 binomial, 0.60, threshold 2) -> scanlines back at DEVICE density (device-row parity = art_reblit_row's convention) -> serpentine Floyd-Steinberg (0.85, weights 2/4/3) into indices 10..245; frame rows/cols = edge-pinned NN.

**Where:** law `scaling_laws.portrait_enlarge` (source of truth); bit-exact C++ port `src/uimod/src/portrait_law.h` (`tests/test_portrait_port.py` compiles `tools/portrait_selftest.cpp` with VS x86 and diffs against the law, incl. real portraits); hook `portrait.cpp` detours the entries of thunk_parity_reblit (pcave2+0x13360) and thunk_art_reblit (+0x29C80), and skips src == g_art_spr (+0x29FC0: the flic / popup-picture scratch view) — every portrait draw ends in one of them — gated on .pcave2 + entry bytes `55 89 E5 83 EC 50`; PORTRAIT-shaped art only (h > w >= PORTRAIT_MIN_W = 32 since 2026-09-21e -- the 9-wide BIOSCAN colour bar was being smoothed; key <= 0xFF), everything else falls back to the thunk; cache keyed on pixels + size + ratio + the dest palette table (dest+0xA4). Opt-out `[UIMod] SmoothPortraits=0`.

**How to apply:** a bake that moves either thunk needs the two offsets in portrait.cpp updated (the DLL logs and falls back otherwise). Preview before asm/C++: the maintainer judges these by eye — build side-by-side sheets from the real PCX first (scripts pattern in scratch; outputs in `work/_portrait_preview/`). A plain nearest-colour palette fit always posterises smooth art in this palette; dither.
