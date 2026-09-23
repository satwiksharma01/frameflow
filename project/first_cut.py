#!/usr/bin/env python3
"""Create a first cut: raw video in, Shotcut project out.

    prepare: video -> frame-rate check (normalize VFR to CFR)
                   -> transcript + measured silences
    edit:    an editor decides keep/remove for every span
    build:   edit plan, validated -> IR -> MLT project (+ sidecar)
                   -> engine check -> [open in Shotcut]

Two ways to run the edit step:

  API mode (default) - one command; a model is called through the provider
  configured with FRAMEFLOW_PROVIDER / FRAMEFLOW_MODEL and its API key.

      python -m project.first_cut <video> [--brief "..."] [--open]

  Agent mode - no API key; a coding agent you already run (Claude Code,
  OpenCode, ...) acts as the editor. `--prepare` writes edit_request.md with
  the instructions and inputs; the agent writes edit_plan.json; `--build`
  validates it (reporting errors for the agent to fix) and builds the project.

      python -m project.first_cut <video> --prepare [--brief "..."]
      python -m project.first_cut <video> --build [--open]

Every intermediate file is written to the output folder so each step can be
inspected, and the editor's reason for every keep/remove decision is kept.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from project.compile_mlt import compile_file
from project.editor_agent import (
    NoSpeechError,
    build_agent_request,
    check_plan,
    ensure_speech,
    propose_edit_plan,
)
from project.engine_check import check_with_melt
from project.media import MediaError, analyze, choose_cfr_rate, normalize_to_cfr
from project.plan_to_ir import edit_plan_to_ir
from project.providers import ProviderError, get_provider
from project.cutpoints import snap_plan
from project.transcribe import (
    MICRO_PAUSE_MIN_SECONDS,
    TranscriptionError,
    build_timing_map,
    transcribe,
)
from project.verify_cuts import VerificationError, verify_joins

REPO_ROOT = Path(__file__).resolve().parent.parent

TRANSCRIPT_FILE = "transcript.json"
TIMING_FILE = "timing.json"
PLAN_FILE = "edit_plan.json"
REQUEST_FILE = "edit_request.md"


class PlanError(Exception):
    pass


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _step(message: str) -> None:
    print(f"==> {message}", flush=True)


def _open_in_shotcut(project: Path) -> None:
    candidates = [Path(r"C:\Program Files\Shotcut\shotcut.exe")]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Shotcut" / "shotcut.exe")
    shotcut = next((c for c in candidates if c.exists()), None)
    if shotcut is None:
        print(f"    Shotcut not found; open {project} manually")
        return
    subprocess.Popen([str(shotcut), str(project)])


def prepare(video: Path, out_dir: Path, language: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    _step(f"Checking frame rate of {video.name}")
    info = analyze(video)
    if not info.has_audio:
        # Checked before normalizing, which on a long file is minutes of work
        # that would be thrown away.
        raise NoSpeechError(
            f"{video.name} has no audio track, so there is no speech to edit. Files saved from "
            f"streaming sites are often video-only, with the audio served as a separate stream."
        )
    source = video
    if info.is_vfr:
        fps = choose_cfr_rate(info.measured_fps)
        source = out_dir / f"{video.stem}-cfr{fps}.mp4"
        print(f"    variable frame rate ({info.measured_fps:.2f} fps measured); normalizing to {fps} fps")
        normalize_to_cfr(video, source, fps)
    else:
        print(f"    constant {info.measured_fps:.2f} fps")

    _step("Transcribing and measuring silences")
    transcript = transcribe(source, language=language)
    _write_json(out_dir / TRANSCRIPT_FILE, transcript)
    print(f"    {len(transcript['segments'])} segments, {len(transcript['silences'])} silences")
    ensure_speech(transcript)

    _step("Mapping word timings and micro-pauses")
    timing = build_timing_map(source, language=language)
    _write_json(out_dir / TIMING_FILE, timing)
    print(f"    {len(timing['words'])} words, {len(timing['pauses'])} pauses over "
          f"{MICRO_PAUSE_MIN_SECONDS}s")
    return transcript


def load_plan(out_dir: Path, transcript: dict) -> dict:
    """Read an edit plan written by an agent, raising PlanError with everything to fix."""
    path = out_dir / PLAN_FILE
    if not path.exists():
        raise PlanError(f"no edit plan at {path}; write it first (see {out_dir / REQUEST_FILE})")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlanError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(plan, dict):
        raise PlanError(f"{path} must contain a JSON object")
    problems = check_plan(plan, transcript)
    if problems:
        raise PlanError(f"{path} needs fixing:\n" + "\n".join(problems))
    return plan


def build(video: Path, out_dir: Path, plan: dict, verify: bool = True) -> Path:
    transcript = json.loads((out_dir / TRANSCRIPT_FILE).read_text(encoding="utf-8"))
    source = Path(transcript["source"])
    info = analyze(source)
    kept = sum(d["end"] - d["start"] for d in plan["decisions"] if d["action"] == "keep")
    print(f"    {len(plan['decisions'])} decisions; keeps {kept:.1f}s of {info.duration_seconds:.1f}s")

    timing_path = out_dir / TIMING_FILE
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else None
    if timing:
        _step("Placing cut points in measured pauses")
        plan, notes = snap_plan(plan, timing["pauses"], info.nominal_fps)
        moved = [n for n in notes if n.status == "snapped"]
        print(f"    {len(moved)} of {len(plan['decisions']) - 1} boundaries moved "
              f"(largest {max((abs(n.moved_ms) for n in moved), default=0)}ms)")
        for note in notes:
            if note.status in ("no-pause", "tight", "unchanged"):
                print(f"    ! boundary at {note.planned:.2f}s: {note.detail}")
        _write_json(out_dir / PLAN_FILE, plan)

    # After snapping, so the timestamps match where the cuts actually land.
    unsure = [d for d in plan["decisions"] if d.get("confidence") == "low"]
    if unsure:
        print(f"    {len(unsure)} decision(s) the editor was unsure about:")
        for d in unsure:
            print(f"    ? {d['action']} {d['start']:.2f}-{d['end']:.2f}s: {d['reason']}")

    _step("Building the project")
    ir = edit_plan_to_ir(
        # The declared rate is the exact one (e.g. 30000/1001, not a rounded
        # 30). For a CFR source it matches the measured average by definition.
        plan, source, info.width, info.height, info.nominal_fps,
        "cfr" if source.resolve() == video.resolve() else "normalized_from_vfr", video.stem,
        source_duration=info.duration_seconds,
    )
    ir_path = out_dir / "project.ir.json"
    _write_json(ir_path, ir)
    project = compile_file(ir_path, out_dir / f"{video.stem}.mlt")

    _step("Checking the project in the MLT engine")
    if check_with_melt(project):
        print("    loaded cleanly")
    else:
        print("    melt not found; skipped")

    if verify and timing:
        _step("Listening to every cut")
        try:
            checks = verify_joins(ir, timing, project)
        except VerificationError as e:
            print(f"    skipped: {e}")
        else:
            suspect = [c for c in checks if not c.ok]
            print(f"    {len(checks) - len(suspect)} of {len(checks)} joins sound clean")
            for check in suspect:
                print(f"    ! {check.summary}")

    return project


def first_cut(video: Path, out_dir: Path, brief: str | None, provider_name: str | None,
              model: str | None, base_url: str | None, language: str,
              verify: bool = True) -> Path:
    provider = get_provider(provider_name, model, base_url)
    transcript = prepare(video, out_dir, language)

    _step(f"Proposing the edit with {provider.name} / {provider.model}")
    plan = propose_edit_plan(transcript, provider, brief)
    _write_json(out_dir / PLAN_FILE, plan)
    if provider.served_by and provider.served_by != provider.model:
        print(f"    served by {provider.served_by} (fallback)")
    return build(video, out_dir, plan, verify=verify)


def _command(video: Path, out: str | None, *flags: str) -> str:
    parts = ["python", "-m", "project.first_cut", f'"{video}"', *flags]
    if out:
        parts += ["--out", f'"{out}"']
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a first cut of a raw recording.")
    parser.add_argument("video")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true",
                      help="agent mode: transcribe and write edit_request.md for a coding agent")
    mode.add_argument("--build", action="store_true",
                      help="agent mode: validate edit_plan.json and build the project")
    parser.add_argument("--brief", help="what you want from this cut, e.g. 'tight, under 60 seconds'")
    parser.add_argument("--provider", help="API mode: anthropic (default) or openai; or FRAMEFLOW_PROVIDER")
    parser.add_argument("--model", help="API mode: model id; or FRAMEFLOW_MODEL")
    parser.add_argument("--base-url", help="API mode: OpenAI-compatible endpoint; or FRAMEFLOW_BASE_URL")
    parser.add_argument("--language", default="auto", help="spoken language code, or 'auto'")
    parser.add_argument("--out", help="output folder (default: output/<video name>)")
    parser.add_argument("--open", action="store_true", help="open the result in Shotcut")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip listening to each cut (faster, but a clipped word can slip through)")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"no such file: {video}")
    out_dir = Path(args.out) if args.out else REPO_ROOT / "output" / video.stem

    try:
        if args.prepare:
            transcript = prepare(video, out_dir, args.language)
            request = out_dir / REQUEST_FILE
            request.write_text(build_agent_request(
                transcript, args.brief, out_dir / PLAN_FILE, _command(video, args.out, "--build"),
            ), encoding="utf-8")
            print(f"\nEdit request: {request}")
            print(f"Next: have your agent follow it and write {out_dir / PLAN_FILE}, then run --build.")
            return

        if args.build:
            transcript_path = out_dir / TRANSCRIPT_FILE
            if not transcript_path.exists():
                sys.exit(f"no transcript at {transcript_path}; run with --prepare first")
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            project = build(video, out_dir, load_plan(out_dir, transcript),
                            verify=not args.no_verify)
        else:
            project = first_cut(video, out_dir, args.brief, args.provider, args.model,
                                args.base_url, args.language, verify=not args.no_verify)
    except (NoSpeechError, ProviderError, PlanError, MediaError, TranscriptionError) as e:
        sys.exit(f"\nStopped: {e}\nIntermediate files are in {out_dir}")

    print(f"\nFirst cut: {project}")
    if args.open:
        _open_in_shotcut(project)


if __name__ == "__main__":
    main()
