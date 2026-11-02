#!/usr/bin/env python3
"""The OpenShot-specific scaffolding an .osp file needs to open as a project.

Everything here was read off a project OpenShot 4.0.1 itself saved
(examples/openshot-saved.osp), and tests/test_openshot.py checks it still
matches that file. This module is the single definition of those conventions,
used by the compiler to write them and by the parser to recognise them.

Two of them are load-bearing rather than cosmetic:
  - version: OpenShot migrates older projects on load (clip locations changed
    meaning in 4.0.0 and again in 4.0.1), and the clip defaults below are in
    4.0.1's form. Declaring an older version would have them rewritten.
  - profile: OpenShot looks the project's profile up by its description, among
    its own profile files. A description it has no file for falls back to
    "HD 720p 30 fps", overwriting the project's size and frame rate - checked
    by opening a compiled project in 4.0.1. Newer OpenShot can carry a custom
    profile inside the project; 4.0.1 cannot.
"""
import math
import os
from pathlib import Path

OPENSHOT_VERSION = {"openshot-qt": "4.0.1", "libopenshot": "1.0.1"}

# Track N is layer N * LAYER_STEP; a higher layer draws on top.
LAYER_STEP = 1_000_000

# What OpenShot's own new project uses for the timeline length, in seconds.
DEFAULT_DURATION = 300


def keyframe(value: float, x: float = 1.0) -> dict:
    """A property that holds one value for the whole clip, as OpenShot writes it."""
    return {"Points": [{
        "co": {"X": x, "Y": value},
        "handle_left": {"X": 0.5, "Y": 1.0},
        "handle_right": {"X": 0.5, "Y": 0.0},
        "handle_type": 0,
        "interpolation": 0,
    }]}


# Every property of a clip OpenShot 4.0.1 adds, with the value it gives a clip
# nobody has adjusted. -1 means "automatic" for has_audio and has_video, and
# "unset" for the perspective corners and channel routing.
CLIP_DEFAULTS = {
    "alpha": keyframe(1.0),
    "anchor": 0,
    "channel_filter": keyframe(-1.0),
    "channel_mapping": keyframe(-1.0),
    "composite": 0,
    "corner_radius": keyframe(0.0),
    "display": 0,
    "effects": [],
    "gravity": 4,
    "has_audio": keyframe(-1.0),
    "has_video": keyframe(-1.0),
    "location_coordinate_system": "auto",
    "location_x": keyframe(0.0),
    "location_y": keyframe(0.0),
    "margin": keyframe(0.0),
    "mixing": 0,
    "origin_x": keyframe(0.5),
    "origin_y": keyframe(0.5),
    "parentObjectId": "",
    **{f"perspective_c{n}_{axis}": keyframe(-1.0) for n in range(1, 5) for axis in "xy"},
    "reader_orientation_mode": "reader",
    "rotation": keyframe(0.0),
    "scale": 1,
    "scale_x": keyframe(1.0),
    "scale_y": keyframe(1.0),
    "shear_x": keyframe(0.0),
    "shear_y": keyframe(0.0),
    # OpenShot writes this one with integers, unlike every other keyframe.
    "time": keyframe(1, x=1),
    "volume": keyframe(1.0),
    "wave_color": {"alpha": keyframe(255.0), "blue": keyframe(255.0),
                   "green": keyframe(123.0), "red": keyframe(0.0)},
    "waveform": False,
    "waveform_mode": 1,
}


# The Color Map / Lookup effect as OpenShot 4.0.1 puts it on a clip - libopenshot's
# EffectInfo().CreateEffect("ColorMap").Json() - less the random id it gets. It
# grades the picture through a 3D LUT (.cube) before the clip is scaled or moved.
COLOR_MAP = {
    "apply_before_clip": True,
    "class_name": "ColorMap",
    "description": "Adjust colors using 3D LUT lookup tables (.cube format)",
    "duration": 0.0,
    "end": 0.0,
    "has_audio": False,
    "has_tracked_object": False,
    "has_video": True,
    "intensity": keyframe(1.0),
    "intensity_b": keyframe(1.0),
    "intensity_g": keyframe(1.0),
    "intensity_r": keyframe(1.0),
    "layer": 0,
    "lut_path": "",
    "mask_invert": False,
    "mask_loop_mode": 0,
    "mask_reader": {},
    "mask_source_id": "",
    "mask_time_mode": 1,
    "name": "Color Map / Lookup",
    "order": 0,
    "parent_effect_id": "",
    "position": 0.0,
    "start": 0.0,
    "type": "ColorMap",
}


# libopenshot's scale modes: cover the frame, cropping what overflows, or fit inside it.
SCALE_CROP, SCALE_FIT = 0, 1

# Keyframe interpolation codes, by the IR's names for them.
CURVES = {"smooth": 0, "linear": 1, "hold": 2}


def location_units(width: int, height: int, source_width: int, source_height: int,
                   fill: bool = True) -> tuple[float, float]:
    """OpenShot's location values per fraction of the frame, for a clip that fills
    it or fits inside it.

    In 4.0.1 a filled clip's location is relative to its own scaled size and the
    frame's together: 1 moves it exactly off screen, half the frame plus half
    the picture. So a move of a fraction f of the frame is f * 2 * frame /
    (frame + picture) in OpenShot's units. A fitted clip's location is a
    fraction of the frame itself, at any size (rendered at 0.25 to 3 times).
    """
    if not fill:
        return 1.0, 1.0
    scale = max(width / source_width, height / source_height)
    return (2 * width / (width + source_width * scale), 2 * height / (height + source_height * scale))


class ProfileError(Exception):
    pass


def ratio(num: int, den: int) -> dict:
    g = math.gcd(num, den)
    return {"num": num // g, "den": den // g}


def profile_dirs() -> list[Path]:
    """Where OpenShot looks for profiles, in the order it looks: the user's own
    first, then the ones it ships with."""
    candidates = [Path.home() / ".openshot_qt" / "profiles",
                  Path(r"C:\Program Files\OpenShot Video Editor\profiles")]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "OpenShot Video Editor" / "profiles")
    return [d for d in candidates if d.is_dir()]


def profile_description(width: int, height: int, fps_num: int, fps_den: int) -> str:
    """The description of the OpenShot profile with exactly these settings.

    Read from OpenShot's own profile files rather than a copy of them, so it
    names a profile the installed OpenShot will find. Each set of settings
    belongs to exactly one of the 423 profiles 4.0.1 ships.
    """
    dirs = profile_dirs()
    if not dirs:
        raise ProfileError("OpenShot's profiles were not found; is OpenShot installed? "
                           "Without one the project would open as HD 720p 30 fps.")
    dar = ratio(width, height)
    wanted = {"width": str(width), "height": str(height),
              "frame_rate_num": str(fps_num), "frame_rate_den": str(fps_den),
              "progressive": "1", "sample_aspect_num": "1", "sample_aspect_den": "1",
              "display_aspect_num": str(dar["num"]), "display_aspect_den": str(dar["den"])}
    for folder in dirs:
        for path in sorted(folder.iterdir(), reverse=True):     # OpenShot's own order
            if not path.is_file():
                continue
            settings = dict(
                (key.strip(), value.strip())
                for key, _, value in (line.partition("=") for line in
                                      path.read_text(encoding="utf-8", errors="replace").splitlines())
            )
            if all(settings.get(k) == v for k, v in wanted.items()):
                return settings["description"]
    # ponytail: no nearest-profile fallback; add one when a real recording needs it.
    raise ProfileError(f"OpenShot has no profile for {width}x{height} at {fps_num}/{fps_den} fps, "
                       "so it would open the project as HD 720p 30 fps.")


def layer(index: int, label: str) -> dict:
    """Track index+1. The label is what OpenShot shows as the track's name."""
    return {"id": f"L{index + 1}", "label": label, "number": (index + 1) * LAYER_STEP,
            "y": 0, "lock": False}


def build_root(width: int, height: int, fps_num: int, fps_den: int, duration: float) -> dict:
    """Everything in the project except its files, clips and layers."""
    return {
        # OpenShot's own placeholder; it assigns a real id when it loads one.
        "id": "T0",
        "fps": {"num": fps_num, "den": fps_den},
        "display_ratio": ratio(width, height),
        "pixel_ratio": {"num": 1, "den": 1},
        "width": width,
        "height": height,
        "sample_rate": 48000,
        "channels": 2,
        "channel_layout": 3,
        "settings": {},
        "clips": [],
        "effects": [],
        "files": [],
        "duration": max(DEFAULT_DURATION, math.ceil(duration)),
        "scale": 15.0,
        "tick_pixels": 100,
        "playhead_position": 0,
        "profile": profile_description(width, height, fps_num, fps_den),
        "export_settings": None,
        "layers": [],
        "markers": [],
        "progress": [],
        "history": {"undo": [], "redo": []},
        "version": OPENSHOT_VERSION,
    }
