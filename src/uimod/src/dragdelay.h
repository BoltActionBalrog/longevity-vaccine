// uimod drag-move hold delay (accessibility): how long the left button must be held on the map before
// the goto line (drag-move) starts. See dragdelay.cpp.
#pragma once

constexpr int kDragDelayDefault = 333;    // vanilla: MapWin_on_left_down's move-mode delay
constexpr int kDragDelayMin     = 100;
constexpr int kDragDelayMax     = 2000;
constexpr int kDragDelayPositions = 20;   // slider positions 0..19 (see DragDelayMsFromPos)

// Byte-checks the delay site and applies the [UIMod] DragMoveHoldMs setting. Both exes, cave-free.
void InstallDragDelay();

bool DragDelayAvailable();                // the site byte check passed
int  DragDelayGet();                      // current delay (ms)
void DragDelaySet(int ms);                // clamp + live-apply (rewrites the two imm32s)
void DragDelaySave();                     // persist the current value

// Slider mapping: 100..300 in 25s, 333 (vanilla, the default), then ~20% steps to 2000 (table in dragdelay.cpp).
int  DragDelayMsFromPos(int pos);
int  DragDelayPosFromMs(int ms);          // nearest position
