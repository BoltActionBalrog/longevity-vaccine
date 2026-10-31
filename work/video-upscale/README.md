# AI-upscale asset pipeline (developer-only)

Turns the game's original 1997 EA FMV cinematics (`movies\*.wve`) into a
high-resolution H.264 pack (`dist\movies-hd\<name>.mp4`) that the in-process movie
player (uimod.dll) plays when `[UIMod] UpscaledVideos=1`.

**This is build-time, developer-only tooling.** End users never run it and never
install an upscaler — they receive only the finished `.mp4` files (the installer
copies them into `<game>\movies\hd\`).

## How it works

Per clip, `build_hd_pack.py`:

1. **decodes** the `.wve` to PNG frames (full, encode-capable ffmpeg),
2. **upscales** every frame with the configured tool (Real-ESRGAN by default) —
   uniform scale only, so each clip's native aspect is preserved,
3. **re-encodes** the upscaled frames plus the original audio to H.264/AAC
   `.mp4`, preserving the source fps, and verifies the frame count end-to-end.

Output is idempotent: a clip whose `.mp4` already exists is skipped unless
`--force`.

## One-time setup: drop in the tools

The heavy binaries are **not** committed (gitignored under `tools\`). Place them so
the paths in `pipeline.ini` resolve:

```
work\video-upscale\tools\
  ffmpeg\bin\ffmpeg.exe          full, encode-capable ffmpeg (NOT the slim runtime build)
  ffmpeg\bin\ffprobe.exe
  realesrgan\realesrgan-ncnn-vulkan.exe
  realesrgan\models\             the model param/bin files (realesr-animevideov3, etc.)
```

Sources (record exact versions/sha when you ship a release):
- ffmpeg (any recent full Windows build, e.g. gyan.dev / BtbN).
- Real-ESRGAN ncnn-vulkan release (xinntao/Real-ESRGAN-ncnn-vulkan) — a single
  Vulkan exe + `models\`, no Python/CUDA, runs on any modern GPU.

## Run

```
..\run-build-hd-pack.bat                          all 61 clips
..\run-build-hd-pack.bat --only opening,gaians    just these two
..\run-build-hd-pack.bat --only gaians --force    rebuild one clip (re-pick a model)
..\run-build-hd-pack.bat --list mylist.txt        clips named in a file (one per line)
..\run-build-hd-pack.bat --keep-frames --only opening   keep the PNG scratch to inspect
```

## Mixing models across cinematics

The default model is **`realesrgan-x4plus`** (chosen after an A/B sweep across the
test set — it gave the crispest result on these clips). `pipeline.ini` has
`[pipeline]` defaults plus optional `[clip:<name>]` override sections. A clip resolves each setting as `[clip:<name>]` → `[pipeline]`, so you can
give specific cinematics a different `Model`/`Scale`/`Crf`/`UpscaleCmd`:

```ini
[clip:openingx]
Model = realesr-general-x4v3

[clip:gaians]
Crf = 16
```

For ad-hoc experiments use the subset selectors (`--only` / `--list`) with `--force`;
for choices you want to keep, record them as `[clip:<name>]` sections so they're
reproducible rather than living in shell history. `UpscaleCmd` is the swap point if
you'd rather use a different upscaler entirely (video2x, waifu2x, Topaz, …) —
placeholders `{in} {out} {scale} {model}`.

## Output

`dist\movies-hd\<name>.mp4` (gitignored — large). Ship this folder as the HD pack
the installer deploys.
