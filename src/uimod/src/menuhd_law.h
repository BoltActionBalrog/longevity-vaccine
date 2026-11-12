#pragma once
// menuhd_law.h -- the HD main menu's layout law, ported from work/scripts/scaling_laws.py (menu_hd_layout).
// tests/test_menuhd_law.py pins the port against the Python at many screen sizes.

namespace menuhd_law {

constexpr int kMenuW = 1024, kMenuH = 768, kStripW = 404;

struct Layout { int num, den, coreH, y0, stripW, stripX; };

// One uniform scale num/den: height-bound on screens at least 4:3 wide, else width-bound with the 4:3 core centred.
inline Layout MenuLayout(int w, int h)
{
    Layout l;
    if (static_cast<long long>(w) * kMenuH >= static_cast<long long>(h) * kMenuW) { l.num = h; l.den = kMenuH; }
    else { l.num = w; l.den = kMenuW; }
    l.coreH = static_cast<int>(static_cast<long long>(kMenuH) * l.num / l.den);
    l.y0 = (h - l.coreH) / 2;
    l.stripW = static_cast<int>(static_cast<long long>(kStripW) * l.num / l.den);
    l.stripX = w - l.stripW;
    return l;
}

} // namespace menuhd_law
