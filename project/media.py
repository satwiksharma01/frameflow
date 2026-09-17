#!/usr/bin/env python3
"""Media probing and constant-frame-rate normalization.

Phase 0 found that screen recordings (Windows Game DVR and similar) are
routinely variable frame rate, and that Shotcut itself considers VFR sources
unreliable for editing. Any timestamp Claude reasons over has to come from a
CFR source, or cut points drift. This module is the gate that enforces that.

Usage:
    python -m project.media <video>                    # report frame rate
    python -m project.media <video> --normalize <out>  # transcode to CFR
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

# Integer rates only. A normalized intermediate exists to make frame math
# trustworthy, so there is no reason to inherit NTSC fractional rates and
# their drop-frame complications.
STANDARD_RATES = [24, 25, 30, 50, 60]

# Relative gap between the container's declared rate and the measured average
# beyond which a file is treated as variable frame rate.
VFR_TOLERANCE = 0.02

# A measured average this close above a standard rate is that rate plus timing
# jitter, not a faster capture. Windows Camera recordings measure 30.0-30.3 fps
# for what is a 30 fps capture; without this they would round up to 50 fps and
# duplicate ~40% of their frames.
RATE_JITTER_TOLERANCE = 0.02


class MediaError(Exception):
    pass


@dataclass
class FrameRateInfo:
    nominal_fps: float
    measured_fps: float
    is_vfr: bool
    width: int
    height: int
    duration_seconds: float

    @property
    def mode(self) -> str:
        """The value to write into the IR's project.source_frame_rate_mode."""
        return "normalized_from_vfr" if self.is_vfr else "cfr"


def _find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "ffmpeg" / "bin" / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    raise MediaError(f"{name} not found on PATH or in the local ffmpeg install")


def probe(video_path: Path | str) -> dict:
    result = subprocess.run(
        [_find_tool("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(video_path)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed on {video_path}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _parse_rate(value: str | None) -> float:
    if not value or value in ("0/0", "N/A"):
        return 0.0
    return float(Fraction(value))


def analyze(video_path: Path | str) -> FrameRateInfo:
    data = probe(video_path)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"no video stream found in {video_path}")

    duration = float(video.get("duration") or data["format"]["duration"])
    nominal = _parse_rate(video.get("r_frame_rate"))

    # Prefer an average derived from the real frame count; fall back to the
    # container's own avg_frame_rate when the count is unavailable.
    nb_frames = video.get("nb_frames")
    if nb_frames and duration > 0:
        measured = int(nb_frames) / duration
    else:
        measured = _parse_rate(video.get("avg_frame_rate"))

    if measured <= 0:
        raise MediaError(f"could not determine a frame rate for {video_path}")

    is_vfr = nominal > 0 and abs(nominal - measured) / measured > VFR_TOLERANCE
    return FrameRateInfo(
        nominal_fps=nominal,
        measured_fps=measured,
        is_vfr=is_vfr,
        width=int(video["width"]),
        height=int(video["height"]),
        duration_seconds=duration,
    )


def choose_cfr_rate(measured_fps: float) -> int:
    """Smallest standard rate at or above the measured average, allowing for jitter.

    Rounding up rather than to the nearest rate avoids discarding real frames
    during the transcode - but an average only fractionally above a standard
    rate is jitter, and rounding it up would duplicate frames instead.
    """
    for rate in STANDARD_RATES:
        if measured_fps <= rate * (1 + RATE_JITTER_TOLERANCE):
            return rate
    return STANDARD_RATES[-1]


def normalize_to_cfr(video_path: Path | str, output_path: Path | str, fps: int) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [_find_tool("ffmpeg"), "-y", "-i", str(video_path),
         "-fps_mode", "cfr", "-r", str(fps),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k",
         str(output_path)],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0:
        raise MediaError(f"ffmpeg normalization failed: {result.stderr[-2000:]}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe or normalize a video's frame rate.")
    parser.add_argument("video")
    parser.add_argument("--normalize", metavar="OUTPUT", help="transcode to CFR at this path")
    args = parser.parse_args()

    info = analyze(args.video)
    print(f"resolution:  {info.width}x{info.height}")
    print(f"duration:    {info.duration_seconds:.4f}s")
    print(f"declared:    {info.nominal_fps:.4f} fps")
    print(f"measured:    {info.measured_fps:.4f} fps")
    print(f"frame rate:  {'VARIABLE' if info.is_vfr else 'constant'}")

    if not args.normalize:
        if info.is_vfr:
            print(f"\nthis source needs normalizing to {choose_cfr_rate(info.measured_fps)} fps "
                  f"before its timestamps can be trusted")
        return

    if not info.is_vfr:
        print("\nsource is already constant frame rate; nothing to normalize")
        return

    target = choose_cfr_rate(info.measured_fps)
    print(f"\nnormalizing to {target} fps -> {args.normalize}")
    normalize_to_cfr(args.video, args.normalize, target)
    after = analyze(args.normalize)
    print(f"result:      {after.measured_fps:.4f} fps measured, "
          f"{'still VARIABLE' if after.is_vfr else 'constant'}")
    if after.is_vfr:
        sys.exit(1)


if __name__ == "__main__":
    main()
