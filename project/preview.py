"""A small video of a build, picture and sound, for the app to play.

OpenShot's own engine renders it (openshot_render.py --video), so what plays in
the app is what the project plays in OpenShot, at 540 px on its shorter side.
"""
import os
import subprocess
from pathlib import Path

from project import openshot_build

SHORT_SIDE = 540


class PreviewError(Exception):
    pass


def size(width: int, height: int) -> tuple[int, int]:
    """The preview's width and height: SHORT_SIDE on the shorter side, the other in proportion, both even."""
    scale = SHORT_SIDE / min(width, height)
    return round(width * scale / 2) * 2, round(height * scale / 2) * 2


def render(project: Path, out: Path, width: int, height: int) -> Path:
    """Render `project` to `out`, whole or not at all: it is written beside it first, then moved into place."""
    if openshot_build.install_dir() is None:
        raise PreviewError("OpenShot is not installed")
    project, out = Path(project).resolve(), Path(out).resolve()
    part = out.with_suffix(".part.mp4")
    try:
        result = openshot_build.run_script(Path(__file__).parent / "openshot_render.py", str(project), str(part),
                                           "--video", str(width), str(height), cwd=project.parent)
        if result.returncode != 0 or not part.exists():
            raise PreviewError(f"OpenShot could not render the preview: {result.stderr[-2000:]}")
        os.replace(part, out)
    # Its hour ran out, or Frameflow's OpenShot could not be built first: the build's checks still stand.
    except (subprocess.SubprocessError, openshot_build.BuildError, OSError) as e:
        raise PreviewError(f"OpenShot could not render the preview: {e}") from e
    finally:
        part.unlink(missing_ok=True)
    return out
