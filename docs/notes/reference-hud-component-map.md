---
name: reference-hud-component-map
description: HUD group numbering (0-12) from refs\Annotate\Hud_annotated.png — the shared language for in-game HUD elements
type: reference
---

We label in-game HUD elements by GROUP # from `D:\SmacxUi\refs\Annotate\Hud_annotated.png` (annotated 2026-07-04 on a 4K build-889305ba screenshot). Re-read the PNG for exact boxes. Numbering:

- **0** HUD strip window (MainWin, native 1024×257 bottom-centered)
- **1** MENU button (top-left wing)
- **2** COMMLINK button (top-right wing)
- **3** Left unit/status panel (unit art + name/stats text)
- **4** Tile-info panel (terrain thumb, Elev/Rainy text, map coords)
- **5** Center readouts (Mission Year/Econ/Psych/Labs ×2 columns + M/I mini buttons at its right edge)
- **6** Unit row (unit icons + 0-1-1 labels, below 5)
- **7** TURN COMPLETE banner + turn.flc slot (right panel top)
- **8** Minimap area (WorldWin, right panel middle)
- **9** Mission Year/Energy text box (right panel bottom-left)
- **10** Map-mode mini buttons (right panel bottom-right, globe icons)
- **11** Chat/notification ticker (NetMsg popup, floats centered above strip)
- **12** Time-control widget "No Time Control" (MP-only, floats above COMMLINK)

Status at build 889305ba (steps 1+3 baked): 0/1/2 fully scaled; 7/9 text scaled; 3/4/5 rects scaled but TEXT TINY → those draw via fonts OTHER than the 3 MainWin fonts (trace next); 5's M/I buttons flat blue = native sprite in scaled rect; 6/10 native sprites; 7's turn.flc slot empty; 8 content tiny/misplaced (WorldWin own literals, GraphicWin_init_2 (780,88,1019,207) @0x4C4A58); 11/12 untouched. Details in [[project-smac-hud-scaling]].
