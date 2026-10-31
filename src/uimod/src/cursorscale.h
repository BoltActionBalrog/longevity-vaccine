#pragma once

// The engine's map cursors (CURSOR.PCX: go-to, patrol, airdrop, artillery, ...) at vanilla x g/16 on the patched
// exe. Byte-checked; a no-op on the unpatched exe and at g <= 16. See cursorscale.cpp.
void InstallCursorScale();
