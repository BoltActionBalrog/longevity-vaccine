// Movie frame: a picture around the cinematics instead of black bars (movieframe.cpp).
#pragma once
#include <windows.h>
#include <cstdint>
#include <vector>

struct MovieFrame {
    std::vector<uint32_t> px;   // BGRA, w x h, top-down: the frame scaled to the screen, its screen area black
    int  w = 0, h = 0;
    RECT screen{};              // the screen area inside it (where the movie plays)
};

constexpr int kMovieFrameDefault = 1;   // [UIMod] MovieFrame

// <game>\movies\frame\*.png (or .jpg / .bmp): the one closest to the screen's shape, scaled to cover w x h (or to fit
// it, black around, when covering would crop more than 12%). Its screen is the pure magenta (255, 0, 255) area of the
// picture. Decoded once and kept for that screen size. Null -- no frame, black bars as before -- when there is no
// such file, it can't be decoded, it has no magenta area, memory runs out, or the frame is switched off.
const MovieFrame* LoadMovieFrame(int w, int h);

// The movie's place inside the frame's screen: uniform scale, as large as fits, centred.
RECT MovieFrameFit(const MovieFrame& f, int clipW, int clipH);

bool MovieFrameAvailable();   // a frame picture is on disk
int  MovieFrameGet();
void MovieFrameSet(int on);   // the next movie follows it; off frees the kept frame
void MovieFrameSave();
