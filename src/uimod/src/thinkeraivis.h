// thinkeraivis.h -- the AI perception filter's Thinker half (PRACX + Thinker target). See thinkeraivis.cpp.
#pragma once

// Port aivis.cpp's filter and bump into thinker.dll 5.5's own planner. Call after InstallThinkerCompat() (decides
// whether thinker.dll is loaded) and InstallAiVisibility() (the predicate, the setting, the engine half). A no-op
// without thinker.dll; self-disables with one log line on any other Thinker build or any unexpected byte.
void InstallThinkerAiVis();
