// uimod tech breakthrough window -- its text boxes (quote / description, unlock lists) open scrolled to
// the TOP instead of the engine's chat-log "last page" (vanilla bug). See techwin.cpp.
#pragma once

// Retarget the three byte-checked call sites. Call once from Init(). Cave-free and artifact-free: safe on
// the PRACX-patched and the unpatched exe alike; self-disables with a log line on unexpected bytes.
void InstallTechWinTopAnchor();
