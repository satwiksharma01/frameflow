#!/usr/bin/env python3
"""Frameflow's build of OpenShot: the installed OpenShot, plus a small patch.

OpenShot's application code ships as plain Python beside its executable, so
Frameflow does not need to rebuild it to change it. The build copies the
executable, its DLLs and the `classes` package into a folder of its own,
patches that copy, and points junctions at everything else in the install. The
installed OpenShot is never modified and still runs as before.

The patch (project/openshot_patch) adds two things:
  - a script runner: with FRAMEFLOW_RUN set, the build runs that Python file
    with OpenShot's own engine (libopenshot) loaded, and exits without
    opening a window. Frameflow uses it to render a project's audio exactly
    as OpenShot plays it.
  - a control server: when the window is open, it listens on localhost for
    Frameflow's requests to save the project or load a new version of it,
    applied as one step the creator can undo.

Usage:
    python -m project.openshot_build          # build, or rebuild after an OpenShot update
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from project.openshot_template import OPENSHOT_VERSION

PATCH = Path(__file__).parent / "openshot_patch"
# Where the build's own copy of OpenShot's code is patched to start the server.
_APP_HOOK = "        self._show_main_window(self.window)\n"


class BuildError(Exception):
    pass


def install_dir() -> Path | None:
    candidates = [Path(r"C:\Program Files\OpenShot Video Editor")]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "OpenShot Video Editor")
    return next((c for c in candidates if (c / "openshot-qt.exe").exists()), None)


def build_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "Frameflow" / f"OpenShot-{OPENSHOT_VERSION['openshot-qt']}"


def is_built() -> bool:
    return (build_dir() / "classes" / "frameflow_bridge.py").exists()


def build() -> Path:
    source = install_dir()
    if source is None:
        raise BuildError("OpenShot is not installed; install OpenShot "
                         f"{OPENSHOT_VERSION['openshot-qt']} first")
    target = build_dir()
    if target.exists():
        _remove(target)
    target.mkdir(parents=True)

    for entry in source.iterdir():
        if entry.name == "classes":
            shutil.copytree(entry, target / "classes")
        elif entry.is_file():
            shutil.copy2(entry, target / entry.name)
        else:
            # A junction needs no admin rights and costs no space.
            subprocess.run(["cmd", "/c", "mklink", "/J", str(target / entry.name), str(entry)],
                           check=True, capture_output=True)

    classes = target / "classes"
    for patch in PATCH.iterdir():
        if patch.suffix == ".py":
            shutil.copy2(patch, classes / patch.name)
    app = classes / "app.py"
    text = app.read_text(encoding="utf-8")
    if text.count(_APP_HOOK) != 1:
        raise BuildError(f"this OpenShot's classes/app.py is not the {OPENSHOT_VERSION['openshot-qt']} "
                         "Frameflow's patch was written for")
    app.write_text(text.replace(_APP_HOOK, _APP_HOOK + "        from classes import frameflow_bridge\n"
                                "        frameflow_bridge.start(self)\n"), encoding="utf-8")
    return target


def _remove(target: Path) -> None:
    # Unlink the junctions first: rmtree would follow them into the install.
    for entry in target.iterdir():
        if entry.is_junction():
            entry.rmdir()
    shutil.rmtree(target)


def environment(**extra: str) -> dict:
    # OpenShot is built on MSYS2's Python, which fails to load OpenGL and
    # crashes on start when it inherits Git Bash's MSYSTEM.
    env = {k: v for k, v in os.environ.items() if k != "MSYSTEM"}
    env.update(extra)
    return env


def run_script(script: Path, *args: str, cwd: Path | None = None,
               timeout: float = 3600) -> subprocess.CompletedProcess:
    """Run a Python file with OpenShot's engine loaded and no window."""
    if not is_built():
        build()
    return subprocess.run(
        [str(build_dir() / "openshot-qt-cli.exe"), *args],
        env=environment(FRAMEFLOW_RUN=str(Path(script).resolve())),
        cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout,
    )


def main() -> None:
    try:
        print(f"built {build()}")
    except BuildError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
