"""Inspect a synthetic edit plan without media, a model provider or Shotcut.

Run from the repository root: python -m examples.demo_timeline
This demonstrates the timeline contract, not transcription or a playable export.
"""
import json
from pathlib import Path

from project.plan_to_ir import edit_plan_to_ir
from project.validate import validate


def main() -> None:
    out = Path("output/demo")
    plan = {
        "source_duration_seconds": 10.0,
        "decisions": [
            {"action": "keep", "start": 0.0, "end": 2.8, "reason": "Introduction"},
            {"action": "remove", "start": 2.8, "end": 4.8, "reason": "Illustrative pause"},
            {"action": "keep", "start": 4.8, "end": 10.0, "reason": "Main explanation"},
        ],
    }
    validate(plan, "edit_plan")
    ir = edit_plan_to_ir(plan, out / "synthetic-recording.mp4", 1920, 1080,
                         30.0, "cfr", "Synthetic timeline demo", 10.0)
    out.mkdir(parents=True, exist_ok=True)
    for filename, document in (("edit_plan.json", plan), ("timeline.json", ir)):
        (out / filename).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("Synthetic example: no recording is read and no provider is called.")
    for clip in ir["tracks"][0]["clips"]:
        print(f"{clip['id']}: source {clip['source_in']:.1f}-{clip['source_out']:.1f}s"
              f" -> timeline {clip['timeline_start']:.1f}s"
              f" (duration {clip['timeline_duration']:.1f}s)")
    total = sum(clip["timeline_duration"] for clip in ir["tracks"][0]["clips"])
    print(f"Source: 10.0s | Kept: {total:.1f}s | Removed: {10 - total:.1f}s")
    print(f"Wrote {out / 'edit_plan.json'} and {out / 'timeline.json'}")
    print("The source path is illustrative; these files are not a playable video project.")


if __name__ == "__main__":
    main()
