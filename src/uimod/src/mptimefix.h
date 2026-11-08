#pragma once

// The multiplayer time widget ("No Time Control", the turn timer) flashed black when it was redrawn between timer
// ticks (base-game bug): two locals of MultiWin_draw_time are written only on the tick path. Byte-checked, both
// exes. See mptimefix.cpp.
void InstallMpTimeFix();
