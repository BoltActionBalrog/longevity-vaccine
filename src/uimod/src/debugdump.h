// uimod developer diagnostic -- Pause dumps popup geometry to uimod.log. OFF unless `uimod_debug.flag` sits next
// to the exe. Read-only (no patches, no engine calls, VirtualQuery-guarded reads). See debugdump.cpp.
#pragma once

void InstallDebugDump();   // call once from Init()
void DebugDumpPoll();      // call from the thread's message hook (cheap no-op when disabled)
