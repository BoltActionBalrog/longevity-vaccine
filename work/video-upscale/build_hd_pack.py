"""Offline AI-upscale asset pipeline: movies\\*.wve -> movies\\hd\\<name>.mp4.

DEVELOPER-ONLY tooling. End users never run this; they receive the finished .mp4
pack it produces. Per clip:

  1. decode the .wve to PNG frames (full, encode-capable ffmpeg)
  2. upscale every frame with the configured tool (Real-ESRGAN by default)
  3. re-encode the upscaled frames + the original audio to H.264/AAC .mp4,
     preserving the source fps and native aspect (uniform scale only)

Everything is driven by pipeline.ini so the upscaler/encoder can be swapped, and
models can be MIXED across cinematics via --only/--list subsets and per-clip
[clip:<name>] override sections. Output is idempotent: a clip whose .mp4 already
exists is skipped unless --force.

  run-build-hd-pack.bat                         # all 61 clips
  run-build-hd-pack.bat --only opening,gaians   # just these two
  run-build-hd-pack.bat --only gaians --force   # re-pick a model for one clip
  run-build-hd-pack.bat --list mylist.txt       # clips named in a file

The pipeline tools (a full ffmpeg.exe + realesrgan-ncnn-vulkan.exe + models) live
in work\\video-upscale\\tools\\ (gitignored); see README.md.
"""
from __future__ import annotations

import argparse
import configparser
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Reuse the single source of truth for the game-install path.
_PIPELINE_DIR = Path(__file__).resolve().parent          # ...\work\video-upscale
sys.path.insert(0, str(_PIPELINE_DIR.parent / "scripts"))  # ...\work\scripts
import config  # noqa: E402

_INI = _PIPELINE_DIR / "pipeline.ini"
_DEFAULT_OUT = _PIPELINE_DIR.parent.parent / "dist" / "movies-hd"  # ...\dist\movies-hd


def _resolve_tool(value: str) -> str:
    """Resolve a tool path: absolute stays, relative is anchored at the pipeline dir."""
    p = Path(value)
    if not p.is_absolute():
        p = _PIPELINE_DIR / p
    return str(p)


def _run(cmd: list[str], log, cwd: str | None = None) -> bool:
    """Run a command, streaming a one-line echo to the log; True on exit 0."""
    log(f"  $ {subprocess.list2cmdline(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        log(f"  ! tool not found: {e}")
        return False
    if r.returncode != 0:
        # Echo the tail of the tool output so failures are diagnosable.
        tail = "\n".join((r.stdout or "").splitlines()[-12:])
        log(f"  ! exit {r.returncode}\n{tail}")
    return r.returncode == 0


def _count_pngs(d: Path) -> int:
    return sum(1 for _ in d.glob("*.png"))


class Pipeline:
    """pipeline.ini reader with [pipeline] defaults + [clip:<name>] overrides."""

    def __init__(self, ini_path: Path):
        self.cp = configparser.ConfigParser()
        if not ini_path.exists():
            raise FileNotFoundError(f"missing config: {ini_path}")
        self.cp.read(ini_path, encoding="utf-8")
        if not self.cp.has_section("pipeline"):
            raise ValueError(f"{ini_path}: no [pipeline] section")
        # CLI overrides (forced, win over both [clip:<name>] and [pipeline]); used to
        # sweep one model across clips into its own folder for A/B evaluation.
        self.force_model: str | None = None
        self.force_crf: str | None = None
        self.out_override: Path | None = None

    def _get(self, clip: str, key: str, fallback: str | None = None) -> str | None:
        sec = f"clip:{clip}"
        if self.cp.has_option(sec, key):
            return self.cp.get(sec, key)
        if self.cp.has_option("pipeline", key):
            return self.cp.get("pipeline", key)
        return fallback

    def ffmpeg(self) -> str:
        return _resolve_tool(self._get("", "Ffmpeg", "ffmpeg") or "ffmpeg")

    def ffprobe(self) -> str:
        return _resolve_tool(self._get("", "Ffprobe", "ffprobe") or "ffprobe")

    def out_dir(self) -> Path:
        if self.out_override is not None:
            return self.out_override
        v = self.cp.get("pipeline", "OutDir", fallback="")
        return Path(_resolve_tool(v)) if v else _DEFAULT_OUT

    def movies_dir(self) -> Path:
        v = self.cp.get("pipeline", "MoviesDir", fallback="")
        return Path(v) if v else (config.game_dir() / "movies")

    # Per-clip resolved settings (CLI --model > clip override > [pipeline] default).
    def model(self, clip: str) -> str:
        if self.force_model:
            return self.force_model
        return self._get(clip, "Model", "realesrgan-x4plus")

    def scale(self, clip: str) -> str:
        return self._get(clip, "Scale", "4")

    def crf(self, clip: str) -> str:
        if self.force_crf:
            return self.force_crf
        return self._get(clip, "Crf", "18")

    def upscale_cmd(self, clip: str, indir: Path, outdir: Path) -> list[str]:
        tmpl = self._get(clip, "UpscaleCmd")
        if not tmpl:
            raise ValueError("pipeline.ini: UpscaleCmd is required")
        subst = {"in": str(indir), "out": str(outdir),
                 "scale": self.scale(clip), "model": self.model(clip)}
        tokens = [t.format_map(subst) for t in tmpl.split()]
        tokens[0] = _resolve_tool(tokens[0])  # anchor a relative tool path
        return tokens


def _probe_fps(ffprobe: str, src: Path, log) -> str:
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=avg_frame_rate", "-of", "csv=p=0", str(src)]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True).stdout.strip()
    except FileNotFoundError:
        out = ""
    # avg_frame_rate is "num/den" (e.g. "15/1"); fall back to 15 on anything odd.
    m = re.match(r"^(\d+)/(\d+)$", out)
    if m and int(m.group(2)) != 0 and int(m.group(1)) != 0:
        return f"{m.group(1)}/{m.group(2)}"
    log(f"  (avg_frame_rate unreadable [{out!r}] -> defaulting to 15)")
    return "15/1"


def _mp4_frame_count(ffprobe: str, mp4: Path) -> int:
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
           "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(mp4)]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True).stdout.strip()
        return int(out)
    except (FileNotFoundError, ValueError):
        return -1


def build_clip(pl: Pipeline, name: str, force: bool, keep_frames: bool, log) -> bool:
    src = pl.movies_dir() / f"{name}.wve"
    out_mp4 = pl.out_dir() / f"{name}.mp4"

    log(f"[{name}]")
    if not src.exists():
        log(f"  ! source not found: {src}")
        return False
    if out_mp4.exists() and not force:
        log(f"  = already built ({out_mp4.name}) -- skipping (use --force to rebuild)")
        return True

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = pl.ffmpeg(), pl.ffprobe()
    fps = _probe_fps(ffprobe, src, log)
    log(f"  model={pl.model(name)} scale={pl.scale(name)} crf={pl.crf(name)} fps={fps}")

    work = Path(tempfile.mkdtemp(prefix=f"hd_{name}_"))
    indir, outdir = work / "in", work / "out"
    indir.mkdir(); outdir.mkdir()
    try:
        # 1. decode -> PNG frames (lossless intermediate; %06d covers any clip length)
        if not _run([ffmpeg, "-y", "-i", str(src),
                     str(indir / "%06d.png")], log):
            return False
        n_in = _count_pngs(indir)
        if n_in == 0:
            log("  ! decoded 0 frames")
            return False

        # 2. upscale every frame (uniform scale -> aspect preserved). Run from the
        #    tool's own dir so it finds adjacent resources (e.g. realesrgan's models\).
        up_cmd = pl.upscale_cmd(name, indir, outdir)
        if not _run(up_cmd, log, cwd=str(Path(up_cmd[0]).parent)):
            return False
        n_out = _count_pngs(outdir)
        if n_out != n_in:
            log(f"  ! frame-count mismatch after upscale: in={n_in} out={n_out}")
            return False

        # 3. encode upscaled frames + original audio (optional) -> H.264/AAC mp4.
        #    -map 1:a:0? makes audio optional (some clips are silent).
        tmp_mp4 = work / f"{name}.mp4"
        if not _run([ffmpeg, "-y",
                     "-framerate", fps, "-i", str(outdir / "%06d.png"),
                     "-i", str(src),
                     "-map", "0:v:0", "-map", "1:a:0?",
                     "-c:v", "libx264", "-crf", pl.crf(name), "-pix_fmt", "yuv420p",
                     "-c:a", "aac", "-b:a", "192k",
                     str(tmp_mp4)], log):
            return False

        # 4. verify the encoded video carries every frame, then publish atomically.
        n_mp4 = _mp4_frame_count(ffprobe, tmp_mp4)
        if n_mp4 != n_in:
            log(f"  ! frame-count mismatch in mp4: frames={n_in} mp4={n_mp4}")
            return False
        shutil.move(str(tmp_mp4), str(out_mp4))
        log(f"  OK {out_mp4}  ({n_in} frames, {out_mp4.stat().st_size:,} bytes)")
        return True
    finally:
        if keep_frames:
            log(f"  (frames kept at {work})")
        else:
            shutil.rmtree(work, ignore_errors=True)


def _all_clip_names(movies: Path) -> list[str]:
    return sorted(p.stem for p in movies.glob("*.wve"))


def _selected(args, movies: Path, log) -> list[str]:
    names: list[str] = []
    if args.only:
        names += [n for n in re.split(r"[,\s]+", args.only.strip()) if n]
    if args.list:
        lf = Path(args.list)
        if not lf.exists():
            log(f"ERROR: --list file not found: {lf}")
            return []
        for ln in lf.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip()  # drop full-line AND inline # comments
            if ln:
                names.append(ln)
    if not names:
        return _all_clip_names(movies)
    # Normalize: strip any extension the user typed.
    return [Path(n).stem for n in names]


def main() -> int:
    ap = argparse.ArgumentParser(description="AI-upscale movies\\*.wve -> movies\\hd\\*.mp4")
    ap.add_argument("--only", default=None,
                    help="Comma/space-separated clip name(s) to build (ext optional). Default: all.")
    ap.add_argument("--list", default=None,
                    help="Path to a file of clip names (one per line; # comments allowed).")
    ap.add_argument("--force", action="store_true",
                    help="Rebuild clips whose .mp4 already exists (e.g. to re-pick a model).")
    ap.add_argument("--keep-frames", action="store_true",
                    help="Keep the decoded/upscaled PNG scratch dirs for inspection.")
    ap.add_argument("--config", default=str(_INI), help="Path to pipeline.ini.")
    ap.add_argument("--model", default=None,
                    help="Force this upscale model for ALL clips this run (overrides "
                         "[clip:] and [pipeline]). For sweeping one model into its own folder.")
    ap.add_argument("--out", default=None,
                    help="Override OutDir for this run (e.g. dist\\eval\\<model>).")
    ap.add_argument("--crf", default=None,
                    help="Force this H.264 CRF for ALL clips this run (overrides [clip:]/[pipeline]).")
    args = ap.parse_args()

    def log(msg: str = ""):
        print(msg, flush=True)

    try:
        pl = Pipeline(Path(args.config))
    except (FileNotFoundError, ValueError) as e:
        log(f"ERROR: {e}")
        return 2
    pl.force_model = args.model
    pl.force_crf = args.crf
    pl.out_override = Path(args.out) if args.out else None

    movies = pl.movies_dir()
    if not movies.exists():
        log(f"ERROR: movies dir not found: {movies}")
        return 2

    names = _selected(args, movies, log)
    if not names:
        return 2

    log(f"Movies  : {movies}")
    log(f"Out dir : {pl.out_dir()}")
    log(f"Clips   : {len(names)}  ({'force' if args.force else 'resume'})")
    log("")

    ok, fail = [], []
    for name in names:
        if build_clip(pl, name, args.force, args.keep_frames, log):
            ok.append(name)
        else:
            fail.append(name)
        log("")

    log(f"=== done: {len(ok)} ok, {len(fail)} failed ===")
    if fail:
        log("failed: " + ", ".join(fail))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
