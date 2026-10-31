// uimod: which mouse button drag-scrolls the map under PRACX. PRACX's WndProc keys its drag scroll on the
// WM_RBUTTONDOWN / WM_RBUTTONUP message numbers (and keeps the drag alive with GetAsyncKeyState(VK_RBUTTON));
// rewriting those six immediates in prax.dll moves the whole mechanism to the middle button, or disables it,
// and lets real right-button messages pass through PRACX to the engine untouched. See praxdrag.cpp.
#pragma once

// Binds prax.dll (if loaded) and byte-checks the six sites. Call from Init() before InstallModernControls.
void InstallPraxDrag(bool pracx);
bool PraxDragAvailable();                     // PRACX is loaded and every site matched the stock bytes
// Apply a drag button: 2 = right (PRACX stock bytes), 1 = middle, 0 = none. No-op when unavailable.
void PraxDragApply(int button);
