"""Render an OpenShot project's audio with OpenShot's own engine.

Runs inside Frameflow's build of OpenShot (project/openshot_build.py), whose
Python is OpenShot's 3.8 with libopenshot loaded - so nothing newer than 3.8
here, and nothing from Frameflow. The working directory must be the project's
folder: libopenshot resolves the project's relative media paths against it.

    openshot-qt-cli.exe <project.osp> <out.wav> [--layer N]     (with FRAMEFLOW_RUN=this file)

--layer N renders only the Nth layer from the bottom, counting from 0.
"""
import json
import math
import sys

import openshot


def main(project_path, out_path, layer_index=None):
    with open(project_path, encoding="utf-8") as f:
        project = json.load(f)
    if layer_index is not None:
        # The words checked at each join are the main track's; other tracks' sound would cover them.
        number = sorted(layer["number"] for layer in project["layers"])[layer_index]
        project["clips"] = [c for c in project["clips"] if c["layer"] == number]
    fps = openshot.Fraction(project["fps"]["num"], project["fps"]["den"])
    timeline = openshot.Timeline(project["width"], project["height"], fps,
                                 project["sample_rate"], project["channels"], project["channel_layout"])
    timeline.SetJson(json.dumps(project))
    timeline.Open()

    end = max(c["position"] + c["end"] - c["start"] for c in project["clips"])
    last_frame = int(math.ceil(end * fps.ToDouble()))

    writer = openshot.FFmpegWriter(out_path)
    writer.SetAudioOptions(True, "pcm_s16le", project["sample_rate"], project["channels"],
                           project["channel_layout"], 0)
    writer.Open()
    writer.WriteFrame(timeline, 1, last_frame)
    writer.Close()
    timeline.Close()


if __name__ == "__main__":
    options = sys.argv[3:]
    main(sys.argv[1], sys.argv[2], int(options[options.index("--layer") + 1]) if "--layer" in options else None)
