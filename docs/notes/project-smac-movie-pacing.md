---
name: project-smac-movie-pacing
description: Movie player widens CPU affinity per movie (watchdog vs DDrawCompat rotation) and skips late frames with sound as master; verified 4K 2026-11-12 and laptop 1080p 2026-11-18, GPU decode backlogged (only if a machine is choppy)
type: project
---

uimod.dll 12241ac5 (pure logic in
src\uimod\src\moviepace.h, tests work\tests\test_moviepace.py). User verified on a 4K display 2026-11-12, and at
1080p on a laptop 2026-11-18 ("works just fine"). GPU decode stays BACKLOG: the maintainer saw no stutter (had
assumed we already used the GPU) and wants it revisited ONLY if some machine shows choppy video.

Non-obvious facts:
- Every Z2K clip: H.264, no B-frames, all slices nal_ref_idc=3 -> skip_frame=NONREF is a no-op there; the real relief
  is skipping sws+present and the jump to an already-due keyframe (1 s late). Deblock skip only 4-6 %.
- DDrawCompat v0.5.4 re-pins from its own TIME_CRITICAL update thread every 100 ms (rotation on by default); polling
  from the player thread left decoders pinned up to a third of the time -> a 5 ms watchdog thread re-widens.
- Sound is the master clock: it starts with the first picture; one device buffer per demux pass (XAudio2 refuses past
  64 queued; smacxcloudbase ends with 81 AAC packets in a row).
- Offline harness that #includes the real movie.cpp (fake sink, instrumented BitBlt) was in a scratch files, not
  checked in -- rebuild it the same way for the GPU prototype.

Related: [[project-smac-movie-player]], [[feedback-ddrawcompat-affinity]], [[feedback-ffmpeg-slim-needs-asm]].
