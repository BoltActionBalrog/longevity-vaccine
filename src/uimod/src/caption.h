// Post-movie caption: vanilla's title + typewriter benefit text over the held last frame
// (movlist.txt section #<MOVIENAME>), which the amovie entry hook bypasses.
#pragma once
#include <windows.h>
#include <functional>

struct CaptionTarget {
    HDC  memDC;          // DC with the full-screen 32-bit back buffer selected (last frame composed)
    int  scrW, scrH;
    RECT dst;            // where the movie frame sits in the back buffer
    int  nativeW, nativeH; // ORIGINAL clip size; vanilla shows it 1:1 centred on a 640x480 surface
};

// Draws the caption into t.memDC, calling `present` after every typed character and during the
// hold; `pumpSkip` pumps messages and returns true once the user asked to skip. No-op when the
// movie has no movlist section (vanilla draws nothing then either).
// Offline-harness seam (work\tests\movie_caption): read this movlist.txt instead of the game's,
// use the fallback colours instead of the game palette, and skip the typewriter/hold waits.
void CaptionTestOverride(const char* movlistPath);

void RunMovieCaption(const char* name, const CaptionTarget& t,
                     const std::function<void()>& present,
                     const std::function<bool()>& pumpSkip);
