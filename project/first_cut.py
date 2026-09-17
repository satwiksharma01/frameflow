#!/usr/bin/env python3
"""Create a first cut: raw video in, Shotcut project out.

    video -> frame-rate check (normalize VFR to CFR)
          -> transcript + measured silences
          -> edit plan from the model, validated
          -> IR -> MLT project (+ sidecar) -> engine check -> [open in Shotcut]

Every intermediate file is written to the output folder so each step can be
inspected, and the model's reason for every keep/remove decision is kept.

Usage:
    python -m project.first_cut <video> [--brief "..."] [--provider anthropic|openai]
                                [--model M] [--base-url URL] [--out DIR] [--open]
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from project.compile_mlt import compile_file
from project.editor_agent import NoSpeechError, propose_edit_plan
from project.engine_check import check_with_melt
from project.media import analyze, choose_cfr_rate, normalize_to_cfr
from project.plan_to_ir import edit_plan_to_ir
from project.providers import ProviderError, get_provider
from project.transcribe import transcribe

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def first_cut(video: Path, out_dir: Path, brief: str | None, provider_name: str | None,
              model: str | None, base_url: str | None, language: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    provider = get_provider(provider_name, model, base_url)

    _step(f"Checking frame rate of {video.name}")
    info = analyze(video)
    source = video
    if info.is_vfr:
        fps = choose_cfr_rate(info.measured_fps)
        source = out_dir / f"{video.stem}-cfr{fps}.mp4"
        print(f"    variable frame rate ({info.measured_fps:.2f} fps measured); normalizing to {fps} fps")
        normalize_to_cfr(video, source, fps)
        info = analyze(source)
    else:
        print(f"    constant {info.measured_fps:.2f} fps")

    _step("Transcribing and measuring silences")
    transcript = transcribe(source, language=language)
    _write_json(out_dir / "transcript.json", transcript)
    print(f"    {len(transcript['segments'])} segments, {len(transcript['silences'])} silences")

    _step(f"Proposing the edit with {provider.name} / {provider.model}")
    plan = propose_edit_plan(transcript, provider, brief)
    _write_json(out_dir / "edit_plan.json", plan)
    if provider.served_by and provider.served_by != provider.model:
        print(f"    served by {provider.served_by} (fallback)")
    kept = sum(d["end"] - d["start"] for d in plan["decisions"] if d["action"] == "keep")
    print(f"    {len(plan['decisions'])} decisions; keeps {kept:.1f}s of {info.duration_seconds:.1f}s")

    _step("Building the project")
    ir = edit_plan_to_ir(
        # The declared rate is the exact one (e.g. 30000/1001, not a rounded
        # 30). For a CFR source it matches the measured average by definition.
        plan, source, info.width, info.height, info.nominal_fps,
        "normalized_from_vfr" if source != video else "cfr", video.stem,
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

    return project


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a first cut of a raw recording.")
    parser.add_argument("video")
    parser.add_argument("--brief", help="what you want from this cut, e.g. 'tight, under 60 seconds'")
    parser.add_argument("--provider", help="anthropic (default) or openai; or FRAMEFLOW_PROVIDER")
    parser.add_argument("--model", help="model id; or FRAMEFLOW_MODEL")
    parser.add_argument("--base-url", help="OpenAI-compatible endpoint; or FRAMEFLOW_BASE_URL")
    parser.add_argument("--language", default="auto", help="spoken language code, or 'auto'")
    parser.add_argument("--out", help="output folder (default: output/<video name>)")
    parser.add_argument("--open", action="store_true", help="open the result in Shotcut")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"no such file: {video}")
    out_dir = Path(args.out) if args.out else REPO_ROOT / "output" / video.stem

    try:
        project = first_cut(video, out_dir, args.brief, args.provider, args.model,
                            args.base_url, args.language)
    except (NoSpeechError, ProviderError) as e:
        sys.exit(f"\nStopped: {e}\nIntermediate files are in {out_dir}")
    print(f"\nFirst cut: {project}")
    if args.open:
        _open_in_shotcut(project)


if __name__ == "__main__":
    main()
