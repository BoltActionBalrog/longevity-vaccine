// uimod mouse wheel over modal lists -- the wheel scrolls the popup under the cursor even while
// the world map is showing (PRACX zooms the map instead). See wheel.cpp.
#pragma once

// Install the message hook. Call once from Init() (on the game's main thread). Touches no patcher
// artifact and patches no code, so it is safe on the PRACX-patched and the unpatched exe alike.
void InstallWheelCapture();
