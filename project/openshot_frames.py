"""Render chosen frames of an OpenShot project with OpenShot's own engine.

Runs inside Frameflow's build of OpenShot (project/openshot_build.py), whose
Python is OpenShot's 3.8 with libopenshot loaded - so nothing newer than 3.8
here, and nothing from Frameflow. The working directory must be the project's
folder: libopenshot resolves the project's relative media paths against it.

    openshot-qt-cli.exe <project.osp> <jobs.json>     (with FRAMEFLOW_RUN=this file)

jobs.json lists {"frame": n, "layers": [layer numbers] or null for all, "out": path.png}.
Each set of layers is drawn alone, over the timeline's black.
"""
import json
import sys

import openshot


def main(project_path, jobs_path):
    with open(project_path, encoding="utf-8") as f:
        project = json.load(f)
    with open(jobs_path, encoding="utf-8") as f:
        jobs = json.load(f)
    by_layers = {}
    for job in jobs:
        key = None if job["layers"] is None else tuple(sorted(job["layers"]))
        by_layers.setdefault(key, []).append(job)
    for layers, group in by_layers.items():
        drawn = dict(project)
        if layers is not None:
            drawn["clips"] = [c for c in project["clips"] if c["layer"] in layers]
        fps = openshot.Fraction(project["fps"]["num"], project["fps"]["den"])
        timeline = openshot.Timeline(project["width"], project["height"], fps,
                                     project["sample_rate"], project["channels"], project["channel_layout"])
        timeline.SetJson(json.dumps(drawn))
        timeline.Open()
        for job in sorted(group, key=lambda j: j["frame"]):
            timeline.GetFrame(job["frame"]).Save(job["out"], 1.0, "PNG", 100)
        timeline.Close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
