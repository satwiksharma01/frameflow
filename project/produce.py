#!/usr/bin/env python3
"""Make a video from a prompt: any kind, with or without the creator on camera.

One prompt in, with whatever the creator has: a script, recordings, images or
clips, music. An editable project out, built from a storyboard the creator
approved. A coding agent (Claude Code, ...) is the editor, as in a first cut's
agent mode; each stage writes a request for it and checks what it writes back.

    python -m project.produce <folder> --prepare "<prompt>" [--script FILE]
           [--footage VIDEO ...] [--asset FILE ...] [--music FILE ...] [--look LUT ...]
        -> brief_request.md; the agent writes brief.json
    python -m project.produce <folder> --brief
        -> checks it, each fact's quote on its page (research.py); the creator confirms it
    python -m project.produce <folder> --storyboard
        -> storyboard_request.md; the agent writes storyboard.json, the creator confirms it
    python -m project.produce <folder> --build [--open]
        -> voiceover, graphics, stills as clips -> IR -> OpenShot project

The project has the picture on the main track (V1), titles and compositions
on Graphics, captions on Captions (fixed text, or what is said popping in word
by word), then Voice and Music as audio tracks. A storyboard's look grades the
picture - the main track and B-roll, not graphics or captions - as a LUT
effect on each clip. It is an ordinary Frameflow project afterwards: edit it by
hand, or with project.edit.
"""
import argparse
import functools
import hashlib
import json
import sys
from pathlib import Path

from project import beats, broll, captions, first_cut, hyperframes, look, openshot_build, reframe, research, voiceover
from project.cutpoints import frame_align
from project.editors import DEFAULT, EDITORS
from project.media import IMAGE_SUFFIXES, MediaError, analyze, level_db, loudness, probe, still_to_clip
from project.openshot_template import ProfileError
from project.transcribe import TranscriptionError
from project.validate import ValidationError, load_schema, validate
from project.verify_cuts import tokenize

INPUTS_FILE = "inputs.json"
BRIEF_FILE = "brief.json"
BRIEF_REQUEST = "brief_request.md"
STORYBOARD_FILE = "storyboard.json"
STORYBOARD_REQUEST = "storyboard_request.md"
IR_FILE = "project.ir.json"

SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
# Under narration, a visual's own sound is turned down this far: inaudible, but
# still a level OpenShot and Frameflow read back (a true mute is not one yet).
UNDER_NARRATION_DB = -60.0
VOICE_LEAD_SECONDS = 0.15
VOICE_TAIL_SECONDS = 0.35
CARD_SECONDS = 3.0      # how long a product card or lower third stays up, unless the storyboard says
BROLL_SECONDS = 3.0     # how long a cutaway to B-roll lasts, unless the storyboard says


class ProduceError(Exception):
    pass


def _read(folder: Path, name: str, kind: str | None = None) -> dict:
    path = folder / name
    if not path.exists():
        raise ProduceError(f"no {name} in {folder}; write it first")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProduceError(f"{path} is not valid JSON: {e}") from e
    if kind:
        try:
            validate(document, kind)
        except ValidationError as e:
            raise ProduceError(f"{path} needs fixing: {e}") from e
    return document


def _schema(kind: str) -> str:
    schema = load_schema(kind)
    for key in ("$schema", "$id"):
        schema.pop(key, None)
    return json.dumps(schema, indent=2)


# --- prepare -------------------------------------------------------------------------


def prepare(folder: Path, prompt: str, script: Path | None, footage: list[Path],
            assets: list[Path], music: list[Path], language: str = "auto", looks: list[Path] = ()) -> Path:
    for path in looks:      # before the footage, whose transcription takes minutes
        text = path.read_text(encoding="utf-8", errors="replace") if path.suffix.lower() == ".cube" else ""
        # OpenShot's Color Map reads both kinds of .cube (checked through its engine).
        if not any(f"LUT_{n}D_SIZE" in text for n in "13"):
            raise ProduceError(f"{path} is not a LUT: a look is a .cube file, as colour grading apps export them")
    folder.mkdir(parents=True, exist_ok=True)
    inputs = {"prompt": prompt, "script": script.read_text(encoding="utf-8") if script else None,
              "footage": [], "assets": [], "music": [],
              "looks": [{"path": path.resolve().as_posix()} for path in looks]}
    for video in footage:
        # Each recording is transcribed exactly as for a first cut, into its own folder.
        out = folder / "footage" / video.stem
        transcript = first_cut.prepare(video.resolve(), out, language)
        inputs["footage"].append({"name": video.name, "source": transcript["source"],
                                  "duration": analyze(transcript["source"]).duration_seconds,
                                  "folder": out.relative_to(folder).as_posix()})
    for path in assets:
        path = path.resolve()
        if path.suffix.lower() in IMAGE_SUFFIXES:
            inputs["assets"].append({"path": path.as_posix(), "kind": "image"})
        else:
            info = analyze(path)
            inputs["assets"].append({"path": path.as_posix(), "kind": "clip",
                                     "duration": info.duration_seconds,
                                     "size": f"{info.width}x{info.height}"})
    for path in music:
        inputs["music"].append({"path": path.resolve().as_posix(),
                                "duration": float(probe(path)["format"]["duration"])})
    first_cut._write_json(folder / INPUTS_FILE, inputs)
    (folder / BRIEF_REQUEST).write_text(brief_request(folder, inputs), encoding="utf-8")
    return folder / BRIEF_REQUEST


def _inventory(inputs: dict) -> str:
    lines = []
    for f in inputs["footage"]:
        lines.append(f"- recording `{f['name']}`, {f['duration']:.1f}s (transcript in `{f['folder']}/`)")
    for a in inputs["assets"]:
        detail = "image" if a["kind"] == "image" else f"clip, {a['duration']:.1f}s, {a['size']}"
        lines.append(f"- asset `{a['path']}` ({detail})")
    for m in inputs["music"]:
        lines.append(f"- music `{m['path']}`, {m['duration']:.1f}s")
    for look in inputs.get("looks", []):
        lines.append(f"- look `{look['path']}` (a LUT)")
    if inputs["script"]:
        lines.append("- a script (below)")
    return "\n".join(lines) or "- nothing: the video is made from titles, graphics and a voiceover"


def brief_request(folder: Path, inputs: dict) -> str:
    script = f"\n## The creator's script\n\n{inputs['script']}\n" if inputs["script"] else ""
    return f"""# Brief

Work out what the creator wants and write it to `{(folder / BRIEF_FILE).as_posix()}`, matching the schema below.

## The creator's prompt

{inputs['prompt']}

## What they provided

{_inventory(inputs)}
{script}
## How

- Pick the aspect from where it will be posted: 9:16 for Reels, Shorts and TikTok; 16:9 for YouTube and pitches; 1:1 for square feeds.
- If something essential is missing - who it is for, the product's name, the call to action - put it in `open_questions` rather than guessing.
- If the creator has a skill library, name the skills this video should use in `skills`, with why.
- For a pitch, or whenever the video will state facts about the world - numbers, dates, prices, who did what - research them with your web tools and put each in `facts`: the claim as the video will use it, who says it (`source`, as the narration would name them), the page (`url`), and the words on that page that support it (`quote`), at least four, copied exactly as the page has them rather than from a summary of it. Prefer the original - the report, the company's own page - over an article about it. State nothing from memory: a fact you cannot find stays out, or goes in `open_questions`. What the creator told you about their own product needs no source.
- Then run `python -m project.produce "{folder.as_posix()}" --brief`. It checks the brief and opens every source to look for its quote; fix what it reports.
- Then show the creator the brief in plain words, with any open questions, and each fact with its source and link, marking those Frameflow could not open for them to check. Wait for them to confirm before running:

  ```
  python -m project.produce "{folder.as_posix()}" --storyboard
  ```

## Brief schema

```json
{_schema("brief")}
```
"""


def check_brief(folder: Path) -> list[str]:
    """Check brief.json, every fact's quote looked for on its page. A line for the creator on each fact;
    ProduceError with what to fix."""
    brief = _read(folder, BRIEF_FILE, "brief")
    problems, lines = research.check(brief.get("facts", []))
    if problems:
        raise ProduceError(f"{folder / BRIEF_FILE} needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
    return lines


# --- storyboard ----------------------------------------------------------------------


def _openshot_looks() -> list[dict]:
    """The LUTs OpenShot ships with (CC0, from freshluts.com), in its folders by kind."""
    install = openshot_build.install_dir()
    return [{"path": p.as_posix()} for p in sorted((install / "colors").glob("*/*.cube"))] if install else []


def _looks(inputs: dict) -> list[dict]:
    """Every LUT a storyboard may name; the creator's first, so their own wins a shared file name."""
    return inputs.get("looks", []) + _openshot_looks()


def storyboard_request(folder: Path) -> Path:
    inputs = _read(folder, INPUTS_FILE)
    brief = _read(folder, BRIEF_FILE, "brief")
    if brief.get("open_questions"):
        raise ProduceError("the brief still has open questions; ask the creator, update brief.json "
                           "and remove them:\n" + "\n".join(f"  - {q}" for q in brief["open_questions"]))
    check_brief(folder)         # again, in case the brief changed after it was checked
    parts = [f"""# Storyboard

Write the video scene by scene to `{(folder / STORYBOARD_FILE).as_posix()}`, matching the schema below.

## The brief

```json
{json.dumps(brief, indent=2, ensure_ascii=False)}
```

## What the creator provided

{_inventory(inputs)}
"""]
    if inputs["script"]:
        parts.append(f"## The creator's script\n\nUse it as written unless the brief says otherwise.\n\n{inputs['script']}\n")
    for f in inputs["footage"]:
        transcript = json.loads((folder / f["folder"] / first_cut.TRANSCRIPT_FILE).read_text(encoding="utf-8"))
        timing = json.loads((folder / f["folder"] / first_cut.TIMING_FILE).read_text(encoding="utf-8"))
        said = "\n".join(f"- {s['start']:.2f}-{s['end']:.2f}s: {s['text'].strip()}" for s in transcript["segments"])
        pauses = ", ".join(f"{p['start']:.2f}-{p['end']:.2f}" for p in timing["pauses"])
        parts.append(f"## Recording `{f['name']}`\n\nWhat is said, in source seconds:\n\n{said}\n\n"
                     f"Measured pauses (start and end footage spans inside these): {pauses or 'none'}\n")
    voices = voiceover.voices()
    kit = {k: v for k, v in hyperframes.brand().items() if v is not None}
    brand_note = (f"- Titles, cards and captions use the creator's brand kit, {json.dumps(kit, default=str)}. "
                  "Use its font, colours and logo in any composition you write too, with the font and logo "
                  "files copied into the composition's folder.\n" if hyperframes.BRAND_FILE.exists() else "")
    found = [(Path(m["path"]).name, beats.beats(m["path"])) for m in inputs["music"]]
    music_note = ("- When the video is cut to its music - a fashion or lifestyle reel, a product montage - set the "
                  "music's `cut_to_beat`: each cut then moves to the nearest beat, unless that would cut into a word "
                  "that is heard, the narration or the end of a clip. Make scenes a whole number of beats long: "
                  + "; ".join(f"`{name}` is at {beats.tempo(t):.0f} BPM, a beat every {60 / beats.tempo(t):.2f} s"
                              if len(t) > 1 else f"`{name}` has no steady beat" for name, t in found)
                  + ".\n" if found else "")
    shipped: dict[str, list[str]] = {}
    for look in _openshot_looks():
        path = Path(look["path"])
        shipped.setdefault(path.parent.name.replace("_", " "), []).append(f"`{path.name}`")
    choices = []
    if inputs.get("looks"):
        choices.append("one of the creator's own LUTs ("
                       + ", ".join(f"`{Path(look['path']).name}`" for look in inputs["looks"]) + ")")
    if shipped:
        choices.append("one of OpenShot's (" + "; ".join(f"{kind}: {', '.join(names)}"
                                                        for kind, names in shipped.items()) + ")")
    look_note = ("- When the video has a mood to set - a fashion or lifestyle reel, a product ad - give it a `look`, "
                 "a colour grade on its footage, images and clips (titles, cards and captions keep their colours): "
                 + ", or ".join(choices) + ". Leave it out to keep the picture as shot.\n" if choices else "")
    facts_note = ("- Facts about the world come only from the brief's `facts`, said no more strongly than their "
                  "quotes. Where a number carries the point, the narration names its source as the brief does "
                  "(\"Goldman Sachs expects ...\"); links stay in the brief.\n" if brief.get("facts") else "")
    parts.append(f"""## How

- Open with a hook in the first two seconds, and end on the call to action from the brief.
- Keep the total near the brief's {brief['target_seconds']}s.
- Narration is read by a voice on this machine: {', '.join(voices) or 'none installed'}. Write it to be heard: short sentences, no symbols.
{facts_note}- Use the creator's own footage and assets wherever they fit; a `title` scene or a HyperFrames `composition` covers what they did not provide.
{brand_note}{music_note}{look_note}- For a reel or a short, set `spoken_captions` to true unless the brief says otherwise: what is said pops in word by word. A scene's own `caption` replaces them for that scene.
- When a product is named over footage or an image, give that scene a `product` card (its name, price and a line under it) with `when` set to the words that name it. A `lower_third` introduces a person on camera.
- Over footage of the creator talking, cut away to their images and clips as `broll` where what is said matches what they show (look at each image); the recording keeps playing underneath.
- Then show the creator the storyboard - the script, and each scene in a line - and wait for them to confirm before running:

  ```
  python -m project.produce "{folder.as_posix()}" --build --open
  ```

## Storyboard schema

```json
{_schema("storyboard")}
```
""")
    path = folder / STORYBOARD_REQUEST
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


# --- build ---------------------------------------------------------------------------


def _match(path: str, entries: list[dict], key: str) -> dict | None:
    """An input by its full path or its file name."""
    return next((e for e in entries if Path(e[key]).as_posix() == Path(path).as_posix()), None) or \
        next((e for e in entries if Path(e[key]).name == Path(path).name), None)


def check_storyboard(board: dict, inputs: dict) -> list[str]:
    """Everything wrong with a storyboard that its schema cannot say."""
    problems = []
    if "music" in board and not _match(board["music"]["path"], inputs["music"], "path"):
        problems.append(f"music {board['music']['path']!r} is not one of the creator's music files")
    if "look" in board:
        look = _match(board["look"]["path"], _looks(inputs), "path")
        if look is None:
            problems.append(f"look {board['look']['path']!r} is not one of the creator's LUTs or OpenShot's own")
        elif not Path(look["path"]).is_file():      # OpenShot would quietly leave the picture as it is
            problems.append(f"look {look['path']} is not there any more")
    for n, scene in enumerate(board["scenes"], start=1):
        visual, label = scene["visual"], f"scene {n} ({scene['visual']['type']})"
        if visual["type"] == "footage":
            f = _match(visual["source"], inputs["footage"], "name")
            if f is None:
                problems.append(f"{label}: {visual['source']!r} is not one of the recordings")
            elif not 0 <= visual["start"] < visual["end"] <= f["duration"] + 1e-3:
                problems.append(f"{label}: {visual['start']}-{visual['end']}s is not inside the "
                                f"{f['duration']:.2f}s recording")
        elif visual["type"] == "asset":
            a = _match(visual["path"], inputs["assets"], "path")
            if a is None:
                problems.append(f"{label}: {visual['path']!r} is not one of the creator's assets")
            elif a["kind"] == "clip" and visual.get("start", 0) >= a["duration"]:
                problems.append(f"{label}: starts after the end of the {a['duration']:.2f}s clip")
        elif visual["type"] == "composition" and not (Path(visual["path"]) / "index.html").exists():
            problems.append(f"{label}: {visual['path']} has no index.html")
        for b in scene.get("broll", []):
            if not _match(b["path"], inputs["assets"], "path"):
                problems.append(f"{label}: B-roll {b['path']!r} is not one of the creator's assets")
        if "broll" in scene and visual["type"] != "footage":
            problems.append(f"{label}: B-roll goes over footage; make the asset a scene of its own instead")
        if visual["type"] in ("title", "composition") or (visual["type"] == "asset" and a and a["kind"] == "image"):
            if "duration" not in scene and "narration" not in scene:
                problems.append(f"{label}: give it a duration, or narration to set one")
    return problems


def _cached(folder: Path, kind: str, key: str, suffix: str) -> Path:
    return folder / kind / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}{suffix}"


def _seconds(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


@functools.cache
def _level(path: Path | str) -> float:
    """The volume that brings this recording or voice line to the platforms' level."""
    return level_db(*loudness(path))


def _said_at(words: list[dict], phrase: str) -> float | None:
    """When the first word of `phrase` is said, where all its words are said in a row."""
    want = tokenize(phrase)
    said = [(w["start"], t) for w in words for t in tokenize(w["text"])]
    for i in range(len(said) - len(want) + 1):
        if want and [t for _, t in said[i:i + len(want)]] == want:
            return said[i][0]
    return None


def _to_beat(beat_times: list[float], cursor: float, length: float, needed: float,
             longest: float = float("inf"), words: list[dict] = (), offset: float = 0.0) -> float:
    """The scene's length, changed so the cut after it lands on the nearest beat it can, at most a beat away.

    The scene keeps what its narration needs and at least half its length, and takes no more of its
    footage or clip than there is. Over footage that is heard, the cut does not move across a word
    (`words` are timed in the recording, `offset` seconds from the timeline).
    """
    if len(beat_times) < 2:
        return length
    cut, beat = cursor + length, 60 / beats.tempo(beat_times)
    for b in sorted(beat_times, key=lambda b: abs(b - cut)):
        low, high = sorted((cut, b))
        if high - low > beat:
            break
        if max(needed, length / 2) <= b - cursor <= longest + 1e-6 and \
                not any(w["start"] - offset < high and low < w["end"] - offset for w in words):
            return round(b - cursor, 6)
    return length


def _crop_keys(folder: Path, footage: dict, width: int, height: int) -> list[dict]:
    """Where a recording's crop goes to keep the face in frame, worked out once per recording and size."""
    path = folder / footage["folder"] / f"framing-{width}x{height}.json"
    if not path.exists():
        info = analyze(footage["source"])
        first_cut._write_json(path, reframe.crop_keys(
            reframe.face_centres(footage["source"]), (width, height), (info.width, info.height),
            reframe.picture_area(footage["source"])))
    return json.loads(path.read_text(encoding="utf-8"))


def build_ir(folder: Path, board: dict, brief: dict, inputs: dict) -> dict:
    """The storyboard as an IR, making the voiceover and still clips it needs."""
    width, height = SIZES[brief["aspect"]]
    fps = brief.get("fps") or (round(analyze(inputs["footage"][0]["source"]).nominal_fps)
                               if inputs["footage"] else 30)
    voice_name = board.get("voice") or next(iter(voiceover.voices()), None)   # the first listed: Piper's when installed
    main, graphics, fixed_captions, voice, said, cutaways = [], [], [], [], [], []
    cursor, problems, cuts = 0.0, [], []
    cut_to_beat = board.get("music", {}).get("cut_to_beat")
    beat_times = [round(frame_align(b, fps), 6) for b in
                  beats.beats(_match(board["music"]["path"], inputs["music"], "path")["path"])] if cut_to_beat else []
    look = board.get("look")
    # The look grades the main track's picture, and B-roll takes it from there (broll.place); graphics keep their colours.
    lut = look and {"path": _match(look["path"], _looks(inputs), "path")["path"],
                    **({"intensity": look["intensity"]} if "intensity" in look else {})}

    for n, scene in enumerate(board["scenes"], start=1):
        visual = scene["visual"]
        spoken = None
        if "narration" in scene:
            wav = _cached(folder, "voice", f"{voice_name}|{scene['narration']}", ".wav")
            if not wav.exists() or not wav.with_suffix(".json").exists():
                voiceover.speak(scene["narration"], wav, voice_name)
            spoken = (wav, _seconds(wav))
        needed = spoken[1] + VOICE_LEAD_SECONDS + VOICE_TAIL_SECONDS if spoken else 0.0

        if visual["type"] == "footage":
            f = _match(visual["source"], inputs["footage"], "name")
            start, end = frame_align(visual["start"], fps), frame_align(visual["end"], fps)
            length = end - start
            if length + 1e-6 < needed:
                problems.append(f"scene {n}: the narration needs {needed:.1f}s but the footage span "
                                f"is {length:.1f}s; lengthen the span or shorten the narration")
            if beat_times:      # under narration the recording is not heard, so its words do not hold the cut
                words = [] if spoken else json.loads(
                    (folder / f["folder"] / first_cut.TIMING_FILE).read_text(encoding="utf-8"))["words"]
                length = _to_beat(beat_times, cursor, length, needed, f["duration"] - start, words, start - cursor)
                end = round(start + length, 6)
            clip = {"source": f["source"], "source_in": start, "source_out": end}
        else:
            length = _to_beat(beat_times, cursor, frame_align(max(scene.get("duration", 0.0), needed), fps), needed)
            clip = None
            if visual["type"] == "asset":
                a = _match(visual["path"], inputs["assets"], "path")
                if a["kind"] == "image":
                    mp4 = _cached(folder, "stills", f"{a['path']}|{width}x{height}|{fps}|{length}", ".mp4")
                    if not mp4.exists():
                        still_to_clip(a["path"], mp4, width, height, fps, length)
                    clip = {"source": mp4.resolve().as_posix(), "source_in": 0.0, "source_out": length}
                else:
                    start = frame_align(visual.get("start", 0.0), fps)
                    # As long as asked, else as long as the narration, else the rest of the clip.
                    length = frame_align(scene.get("duration") or needed or a["duration"] - start, fps)
                    if start + length > a["duration"] + 1e-3:
                        problems.append(f"scene {n}: the clip has {a['duration'] - start:.1f}s from "
                                        f"{start:.1f}s, but the scene needs {length:.1f}s")
                    length = _to_beat(beat_times, cursor, length, needed, a["duration"] - start)
                    clip = {"source": a["path"], "source_in": start, "source_out": start + length}
            else:
                params = ({"layout": "title"} if visual["type"] == "title"
                          else {"composition": str(Path(visual["path"]).resolve())})
                graphics.append({"timeline_start": cursor, "timeline_duration": length,
                                 "generator": "hyperframes", "generator_params": params,
                                 **({"text": visual["text"]} if visual["type"] == "title" else {})})
        if clip:
            clip.update(timeline_start=cursor, timeline_duration=round(clip["source_out"] - clip["source_in"], 6))
            if spoken:
                clip["volume_db"] = UNDER_NARRATION_DB
            elif visual["type"] == "footage" and (gain := _level(f["source"])):
                clip["volume_db"] = gain
            if brief["aspect"] != "16:9":       # a reel or a square post: footage fills the frame
                clip["transform"] = {"fill": True}
                if visual["type"] == "footage":     # ...with the speaker kept in it
                    x = reframe.clip_offset(_crop_keys(folder, f, width, height), start, end)
                    if x:
                        clip["transform"]["position"] = {"x": x}
            if lut:
                clip["effects"] = [{"type": "lut", "params": dict(lut)}]
            main.append(clip)
        heard = None        # what is said in the scene, on the timeline: the narration, else the footage's speech
        if board.get("spoken_captions") or "cards" in scene or "broll" in scene:
            if spoken:
                words = json.loads(spoken[0].with_suffix(".json").read_text(encoding="utf-8"))
                heard = captions.run(words, 0.0, length - VOICE_LEAD_SECONDS, cursor + VOICE_LEAD_SECONDS)
            elif visual["type"] == "footage":
                timing = json.loads((folder / f["folder"] / first_cut.TIMING_FILE).read_text(encoding="utf-8"))
                heard = captions.run(timing["words"], start, end, cursor)
        if "caption" in scene:
            fixed_captions.append({"timeline_start": cursor, "timeline_duration": length,
                                   "generator": "hyperframes", "text": scene["caption"]})
        elif board.get("spoken_captions") and heard:
            said.append(heard)
        for card in scene.get("cards", []):
            at = cursor
            if "when" in card:
                at = _said_at(heard["words"] if heard else [], card["when"])
                if at is None:
                    problems.append(f"{card['when']!r} is not said in scene {n}, so the {card['text']!r} card "
                                    f"has no moment to come up; use words from its narration or transcript")
                    continue
            at = round(frame_align(at, fps), 6)
            until = round(frame_align(min(at + card.get("duration", CARD_SECONDS), cursor + length), fps), 6)
            if any(g["timeline_start"] < until and at < g["timeline_start"] + g["timeline_duration"]
                   for g in graphics):
                problems.append(f"scene {n}: the {card['text']!r} card would be on screen with another graphic; "
                                f"put cards over footage or an asset, one at a time")
                continue
            graphics.append({"timeline_start": at, "timeline_duration": round(until - at, 6),
                             "generator": "hyperframes", "text": card["text"],
                             "generator_params": {"layout": card["kind"],
                                                  **{k: card[k] for k in ("subtitle", "price") if k in card}}})
        for b in scene.get("broll", []):
            at = cursor
            if "when" in b:
                at = _said_at(heard["words"] if heard else [], b["when"])
                if at is None:
                    problems.append(f"{b['when']!r} is not said in scene {n}, so the B-roll {b['path']!r} "
                                    f"has no moment to cut away at; use words from its transcript or narration")
                    continue
            cutaways.append({"label": f"scene {n}: B-roll {b['path']!r}", "at": at, "start": b.get("start", 0.0),
                             "path": _match(b["path"], inputs["assets"], "path")["path"],
                             "duration": min(b.get("duration", BROLL_SECONDS), cursor + length - at)})
        if spoken:
            voice.append({"source": spoken[0].resolve().as_posix(), "source_in": 0.0,
                          "source_out": spoken[1], "timeline_start": round(cursor + VOICE_LEAD_SECONDS, 6),
                          "timeline_duration": spoken[1],
                          **({"volume_db": gain} if (gain := _level(spoken[0])) else {})})
        cursor = round(cursor + length, 6)
        cuts.append(cursor)

    if problems:
        raise ProduceError("the storyboard needs fixing:\n" + "\n".join(f"  {p}" for p in problems))

    if cut_to_beat and len(cuts) > 1:
        off = [str(n) for n, c in enumerate(cuts[:-1], start=1) if not any(abs(c - b) < 1e-3 for b in beat_times)]
        print(f"    {len(cuts) - 1 - len(off)} of {len(cuts) - 1} cuts on the beat"
              + (f", at {beats.tempo(beat_times):.0f} BPM" if len(beat_times) > 1 else ": the music has no steady beat")
              + (f"; the cut after scene {', '.join(off)} stays put: a word, the narration or the end of a clip "
                 f"is in the way, or the music has stopped" if off and len(beat_times) > 1 else ""))
    tracks = [("V1", "video", main), ("Graphics", "graphics", graphics),
              ("Captions", "captions", fixed_captions), ("Voice", "audio", voice)]
    if "music" in board:
        m = _match(board["music"]["path"], inputs["music"], "path")
        level = board["music"].get("volume_db", -18.0 if voice else -6.0)
        length = min(cursor, m["duration"])
        tracks.append(("Music", "audio", [{"source": m["path"], "source_in": 0.0, "source_out": length,
                                           "timeline_start": 0.0, "timeline_duration": length,
                                           "volume_db": level,
                                           "fade_out": {"sound": min(2.0, length / 4)}}]))
    ir = {"schema_version": "0.2.0",
          "project": {"name": brief["title"], "width": width, "height": height, "fps": fps,
                      "source_frame_rate_mode": "cfr"},
          # Audio tracks go above the picture: the bottom track is the main one.
          "tracks": [{"id": tid, "type": kind,
                      "clips": [{"id": f"clip{i}", **c} for i, c in enumerate(clips, start=1)]}
                     for tid, kind, clips in tracks if clips or tid == "V1" or (tid == "Captions" and said)]}
    if cutaways:
        problems = broll.place(ir, cutaways, 0)
        if problems:
            raise ProduceError("the storyboard needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
        broll.make_stills(ir, folder)
    if said:
        first_cut._step("Rendering word-by-word captions with HyperFrames")
        print(f"    {captions.add(ir, said, folder)} lines")
    return ir


def build(folder: Path, open_it: bool = False) -> Path:
    inputs = _read(folder, INPUTS_FILE)
    brief = _read(folder, BRIEF_FILE, "brief")
    board = _read(folder, STORYBOARD_FILE, "storyboard")
    problems = check_storyboard(board, inputs)
    if problems:
        raise ProduceError(f"{folder / STORYBOARD_FILE} needs fixing:\n" + "\n".join(f"  {p}" for p in problems))

    first_cut._step("Recording the voiceover and preparing the pictures")
    ir = build_ir(folder, board, brief, inputs)
    if any(c.get("generator") == "hyperframes" for t in ir["tracks"] for c in t["clips"]):
        first_cut._step("Rendering titles and captions with HyperFrames")
        hyperframes.render_generated(ir, folder)

    first_cut._step("Building the project")
    editor = EDITORS[DEFAULT]
    ir_path = folder / IR_FILE
    first_cut._write_json(ir_path, ir)
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in brief["title"]).strip("-") or "video"
    project = editor.compile_file(ir_path, folder / f"{stem}{editor.suffix}")
    total = max((c["timeline_start"] + c["timeline_duration"] for t in ir["tracks"] for c in t["clips"]), default=0)
    print(f"    {len(board['scenes'])} scenes, {total:.1f}s (brief asked for about {brief['target_seconds']}s)")
    for tid in ("V1", "Graphics", "Captions", "Voice", "Music"):
        track = next((t for t in ir["tracks"] if t["id"] == tid), None)
        if track and track["clips"]:
            print(f"    {tid}: {len(track['clips'])} clip(s)")
    if "look" in board:
        print(f"    look: {Path(board['look']['path']).name}, a Color Map effect on each picture clip")
    look.report(project, ir)
    if open_it:
        editor.open(project)
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description="Make a video from a prompt, as an editable project.")
    parser.add_argument("folder", help="where this video's files go, e.g. output/jacket-reel")
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--prepare", metavar="PROMPT", help="start: the creator's prompt, in their words")
    stage.add_argument("--brief", action="store_true", help="check brief.json, every fact against its source")
    stage.add_argument("--storyboard", action="store_true", help="after the brief is confirmed")
    stage.add_argument("--build", action="store_true", help="after the storyboard is confirmed")
    parser.add_argument("--script", type=Path, help="a script the creator wrote")
    parser.add_argument("--footage", type=Path, nargs="*", default=[], help="the creator's recordings")
    parser.add_argument("--asset", type=Path, nargs="*", default=[], help="images or clips to use")
    parser.add_argument("--music", type=Path, nargs="*", default=[], help="music files to choose from")
    parser.add_argument("--look", type=Path, nargs="*", default=[], help="LUTs (.cube) to choose the look from")
    parser.add_argument("--language", default="auto", help="spoken language of the footage, or 'auto'")
    parser.add_argument("--open", action="store_true", help="open the project in OpenShot when built")
    args = parser.parse_args()
    folder = Path(args.folder)
    try:
        if args.prepare:
            missing = [p for p in [args.script, *args.footage, *args.asset, *args.music, *args.look]
                       if p and not p.exists()]
            if missing:
                raise ProduceError("not found: " + ", ".join(map(str, missing)))
            print(f"\nNext: read {prepare(folder, args.prepare, args.script, args.footage, args.asset, args.music, args.language, args.look)}")
        elif args.brief:
            first_cut._step("Checking the brief, and each fact on its page")
            for line in check_brief(folder):
                print(f"    {line}")
            print("\nNext: show the creator the brief, and wait for them to confirm it.")
        elif args.storyboard:
            print(f"\nNext: read {storyboard_request(folder)}")
        else:
            print(f"\nBuilt: {build(folder, args.open)}")
    except (ProduceError, MediaError, TranscriptionError, first_cut.NoSpeechError, voiceover.VoiceError,
            hyperframes.HyperFramesError, ProfileError) as e:
        sys.exit(f"\n{e}")


if __name__ == "__main__":
    main()
