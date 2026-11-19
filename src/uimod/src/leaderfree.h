#pragma once

// An AI probe team freeing a captured faction leader reset a LIVING faction to a colony pod (base-game bug: the AI's
// pick read slot index + 1 as the faction), and the jailer was told "you liberated" them. Byte-checked, cave-free, both
// exes. Under Thinker Mod the pick stands down (Thinker fixes it itself); the jailer's message is pinned to Thinker 5.5.
// Call after InstallThinkerCompat(). See leaderfree.cpp.
void InstallLeaderFreeFix();
