// uimod Punishment Sphere display: a sphere base shows the drones it is suppressing (PSYCH tab last row,
// base screen citizens row, F4 Base Operations), each drone face badged. Display only. See pssphere.cpp.
#pragma once

// Byte-checked, all-or-nothing; works on the unpatched and the patched exe. Call once from Init().
void InstallPunishmentSphereView();

// The current base's would-be citizen totals (talents / workers / drones / specialists) when it has a sphere or a
// nerve staple and fresh totals exist; false otherwise. For painters that print those numbers (thinkertext.cpp).
bool PsSphereWouldBePop(int* talents, int* workers, int* drones, int* specialists);
