#!/usr/bin/env python3
"""A screen recording under the face, for builder videos.

The creator records their screen and their face at the same time, as two
files, each with their voice. The face recording stays the recording: it is
transcribed and cut, and its sound is what plays. The screen recording goes on
a Screen track below it, fitted to a 16:9 frame with its own sound turned
right down, and the face sits small in the bottom-right corner - ordinary
clips the creator can move, resize or delete in OpenShot.

The two files start whenever the creator pressed record on each, so they are
lined up by the voice both recorded. Every moment of the face then plays over
the moment of the screen recorded with it, and an edit that cuts the face cuts
the screen the same way.
"""
from pathlib import Path

import numpy as np

from project.beats import _decode
from project.broll import MUTED_DB
from project.media import MediaError, probe
from project.operations import _shorten, main_index
from project.reconcile import merge_spans, source_key, subtract_spans

TRACK_ID = "Screen"
# ponytail: a 1440p or 4K screen shows at 1080p; offer a bigger frame when the creator uploads one.
FRAME = (1920, 1080)
FACE_SCALE = 0.25           # of the face's size fitted to the frame
MARGIN = 0.025              # between the face and the frame's edges, as a fraction of its width
RATE, HOP = 8000, 40        # the voice compared by its loudness every 5 ms
# On a test pair the best alignment scored 4.1 times the next best; on files sharing no voice, 1.12 at most.
CLEAR = 1.5

_PLACE = ("id", "source_in", "source_out", "timeline_start", "timeline_duration")


def _loudness(path: Path | str) -> np.ndarray:
    """How loud the sound is every HOP samples, in dB above its average over the second up to then:
    the rise and fall of each word, whatever the microphone and the room."""
    samples = _decode(path, RATE)
    frames = samples[:len(samples) // HOP * HOP].reshape(-1, HOP)
    level = 10 * np.log10(np.mean(np.square(frames, dtype=np.float64), axis=1) + 1e-10)
    window = RATE // HOP
    if len(level) < 2 * window:
        raise MediaError(f"{Path(path).name} is too short to line up by its sound")
    total = np.cumsum(np.insert(level, 0, 0.0))
    average = (total[window:] - total[:-window]) / window
    return level - np.concatenate([np.full(window - 1, average[0]), average])


def _sound_start(path: Path | str) -> float:
    """Where a file's sound starts, against its picture."""
    stream = next(s for s in probe(path)["streams"] if s.get("codec_type") == "audio")
    return float(stream.get("start_time") or 0.0)


def offset(face: Path | str, screen: Path | str) -> float:
    """Seconds into the screen recording at which the face recording starts, found from the voice
    both recorded: negative when the screen was started second."""
    a, b = _loudness(face), _loudness(screen)
    size = 1 << (len(a) + len(b)).bit_length()
    scores = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    best = int(np.argmax(scores))
    near = np.arange(best - RATE // HOP // 4, best + RATE // HOP // 4 + 1) % size      # within 0.25 s
    if scores[best] < CLEAR * np.delete(scores, near).max():
        raise MediaError(f"{Path(face).name} and {Path(screen).name} do not share a voice to line them "
                         f"up by: record your voice into both")
    lag = (best if best < len(b) else best - size) * HOP / RATE
    # Decoding starts each file at its first sound, which can sit a little after its picture's start.
    return round(lag + _sound_start(screen) - _sound_start(face), 6)


def face_transform(face_size: tuple[int, int]) -> dict:
    """The face small in the bottom-right corner, as an IR transform."""
    (width, height), (frame_width, frame_height) = face_size, FRAME
    shown = min(frame_width / width, frame_height / height) * FACE_SCALE
    margin = MARGIN * frame_width
    return {"scale": FACE_SCALE, "position": {
        "x": round(0.5 - (margin + width * shown / 2) / frame_width, 6),
        "y": round(0.5 - (margin + height * shown / 2) / frame_height, 6)}}


def lay_out(ir: dict, screen: Path | str, shift: float, length: float, face_size: tuple[int, int]) -> None:
    """Make the project a 16:9 frame with the face small in its corner, over the screen recording on a
    Screen track below it: each screen clip shows the moments recorded with the face clip above it, as
    far as the screen recording goes. `shift` is offset(face, screen) and `length` the screen
    recording's. Changes `ir` in place."""
    ir["project"]["width"], ir["project"]["height"] = FRAME
    main = main_index(ir)
    joins = 0.5 / ir["project"]["fps"]
    clips = []
    for face in ir["tracks"][main]["clips"]:
        face["transform"] = face_transform(face_size)
        start, end = max(face["source_in"] + shift, 0.0), min(face["source_out"] + shift, length)
        if end - start > joins:
            clips.append({"id": f"clip{len(clips) + 1}", "source": Path(screen).resolve().as_posix(),
                          "source_in": round(start, 6), "source_out": round(end, 6),
                          "timeline_start": round(face["timeline_start"] + start - shift - face["source_in"], 6),
                          "timeline_duration": round(end - start, 6), "volume_db": MUTED_DB})
    ir["tracks"].insert(main, {"id": TRACK_ID, "type": "screen", "clips": clips})


def _piece(clip: dict, face: dict, start: float, end: float, shift: float) -> dict:
    """The part of screen clip `clip` recorded with moments start-end of face clip `face`, where those
    moments play now."""
    piece = {k: v for k, v in clip.items() if k not in ("fade_in", "fade_out")}
    piece.update(source_in=round(start + shift, 6), source_out=round(end + shift, 6),
                 timeline_start=round(face["timeline_start"] + start - face["source_in"], 6),
                 timeline_duration=round(end - start, 6))
    # A fade stays on the clip's own edge.
    for fade, edge in (("fade_in", "source_in"), ("fade_out", "source_out")):
        if fade in clip and abs(piece[edge] - clip[edge]) < 1e-6:
            piece[fade] = clip[fade]
    return piece


def _rest(clip: dict) -> dict:
    """Everything about a clip but where it sits and its fades."""
    return {k: v for k, v in clip.items() if k not in _PLACE + ("fade_in", "fade_out")}


def _joined(pieces: list[dict], joins: float) -> list[dict]:
    """The pieces in timeline order as clips: one that plays on from the piece before joins it, and
    none overlaps the next."""
    clips: list[dict] = []
    for piece in sorted(pieces, key=lambda c: c["timeline_start"]):
        last = clips[-1] if clips else None
        if (last and last["source"] == piece["source"] and "fade_out" not in last and "fade_in" not in piece
                and abs(last["timeline_start"] + last["timeline_duration"] - piece["timeline_start"]) < joins
                and abs(last["source_out"] - piece["source_in"]) < joins and _rest(last) == _rest(piece)):
            last.update(source_out=piece["source_out"], timeline_duration=round(
                piece["timeline_start"] + piece["timeline_duration"] - last["timeline_start"], 6))
            if "fade_out" in piece:
                last["fade_out"] = piece["fade_out"]
            continue
        if last:
            _shorten(last, piece["timeline_start"])
        clips.append(dict(piece))
    clips = [c for c in clips if c["timeline_duration"] > joins]
    for n, clip in enumerate(clips, start=1):
        clip["id"] = f"clip{n}"
    return clips


def follow(before: dict, after: dict, lengths: dict[str, float]) -> int:
    """After an edit changed the main track, cut the Screen track the same way, so the screen still
    shows what was on it as each word was said.

    Each stretch of a screen clip is matched, through the main track as it was, to the moments of the
    face above it, and goes where those moments play now. So a stretch whose moments were cut goes
    too, a clip the creator deleted stays gone, and one they moved, zoomed or slid keeps that. Speech
    the edit put back gets the screen recorded with it wherever the screen plays right beside it, as
    far as the screen recording goes (`lengths`, keyed by source_key). Changes `after` in place;
    returns how many screen clips there are now.
    """
    old = before["tracks"][main_index(before)]["clips"]
    new = after["tracks"][main_index(after)]["clips"]
    joins = 0.5 / after["project"]["fps"]
    had: dict[str, list] = {}
    for clip in old:
        had.setdefault(source_key(clip["source"]), []).append((clip["source_in"], clip["source_out"]))
    count = 0
    for track in after["tracks"]:
        if track["type"] != "screen":
            continue
        pieces = []                                   # (piece, how far the screen runs ahead of the face)
        for clip in track["clips"]:
            t0, t1 = clip["timeline_start"], clip["timeline_start"] + clip["timeline_duration"]
            under = [o for o in old if o["timeline_start"] < t1 and t0 < o["timeline_start"] + o["timeline_duration"]]
            if not under:
                # ponytail: over a gap in the main track it stays put rather than moving with the gap.
                pieces.append((clip, None))
            for o in under:
                at = max(t0, o["timeline_start"])
                lo = o["source_in"] + at - o["timeline_start"]
                hi = o["source_in"] + min(t1, o["timeline_start"] + o["timeline_duration"]) - o["timeline_start"]
                shift = clip["source_in"] + at - t0 - lo
                for face in new:
                    start, end = max(lo, face["source_in"]), min(hi, face["source_out"])
                    if source_key(face["source"]) == source_key(o["source"]) and end - start > joins:
                        pieces.append((_piece(clip, face, start, end, shift), shift))
        for face in new:                              # what the edit put back
            for lo, hi in subtract_spans([(face["source_in"], face["source_out"])],
                                         merge_spans(had.get(source_key(face["source"]), []))):
                at, until = (face["timeline_start"] + t - face["source_in"] for t in (lo, hi))
                beside = next((p for p in pieces if p[1] is not None and (
                    abs(p[0]["timeline_start"] + p[0]["timeline_duration"] - at) < joins
                    or abs(p[0]["timeline_start"] - until) < joins)), None)
                if beside:
                    clip, shift = beside
                    start, end = max(lo, -shift), min(hi, lengths[source_key(clip["source"])] - shift)
                    if end - start > joins:
                        pieces.append((_piece(clip, face, start, end, shift), shift))
        track["clips"] = _joined([p for p, _ in pieces], joins)
        count += len(track["clips"])
    return count
