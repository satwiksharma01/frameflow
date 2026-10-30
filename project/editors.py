#!/usr/bin/env python3
"""The editors a Frameflow project can be opened in, and what differs between them.

OpenShot is the default: it has the simplest interface of the open-source
editors, and its projects are plain JSON. Shotcut stays supported for projects
already made with it. A project's file suffix says which editor it belongs to,
so changing one needs no flag.
"""
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project import compile_mlt, compile_osp, openshot_build, openshot_live
from project.engine_check import check_with_melt
from project.parse_mlt import ParseError as MltParseError, parse_mlt
from project.parse_mlt import unsupported_content as mlt_unsupported_content
from project.parse_osp import ParseError as OspParseError, parse_osp
from project.parse_osp import unsupported_content as osp_unsupported_content
from project.verify_cuts import render_audio, render_osp_audio


@dataclass(frozen=True)
class Editor:
    name: str
    suffix: str
    install_folder: str
    executable: str
    compile_file: Callable[[Path | str, Path | str], Path]
    parse: Callable[[Path | str], dict]
    unsupported_content: Callable[[Path | str], list[str]]
    render_audio: Callable[[Path | str, Path | str], Path]
    # Loads the project in the editor's engine without opening the editor.
    # OpenShot has none: its command-line launcher is the whole application.
    engine_check: Callable[[Path | str], bool] | None = None
    # A window of the editor Frameflow can drive while it is open: `save` writes
    # the creator's unsaved work to the project, `update` loads Frameflow's new
    # version - both only if that project is the one open. `show` puts any
    # project in the open window. Each returns False when it did nothing.
    live_save: Callable[[Path], bool] | None = None
    live_update: Callable[[Path], bool] | None = None
    live_show: Callable[[Path], bool] | None = None
    # The executable to launch, when it is not the installed one.
    launcher: Callable[[], Path | None] | None = None

    def save_open_window(self, project: Path) -> None:
        self._live(self.live_save, project, "saved your unsaved changes in the open window first")

    def update_open_window(self, project: Path) -> bool:
        return self._live(self.live_update, project,
                          f"updated in the open {self.name} window; Ctrl+Z there undoes it")

    def _live(self, call, project: Path, done: str) -> bool:
        if call is None:
            return False
        try:
            if call(project):
                print(f"    {done}")
                return True
        except RuntimeError as e:
            print(f"    ! {e}")
        return False

    def open(self, project: Path) -> None:
        if self._live(self.live_show, project, f"shown in the open {self.name} window"):
            return
        found = self.launcher() if self.launcher else None
        if found is None:
            candidates = [Path(r"C:\Program Files") / self.install_folder / self.executable]
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                candidates.append(Path(local_app_data) / "Programs" / self.install_folder / self.executable)
            found = next((c for c in candidates if c.exists()), None)
        if found is None:
            print(f"    {self.name} not found; open {project} manually")
            return
        subprocess.Popen([str(found), str(project)], env=openshot_build.environment())


def _openshot_launcher() -> Path | None:
    """Frameflow's build of OpenShot, which Frameflow can drive while it is open."""
    try:
        if not openshot_build.is_built():
            openshot_build.build()
    except (openshot_build.BuildError, OSError) as e:
        print(f"    ! could not build Frameflow's OpenShot ({e}); opening the installed one")
        return None
    return openshot_build.build_dir() / "openshot-qt.exe"


OPENSHOT = Editor("OpenShot", ".osp", "OpenShot Video Editor", "openshot-qt.exe",
                  compile_osp.compile_file, parse_osp, osp_unsupported_content, render_osp_audio,
                  live_save=openshot_live.save_if_open, live_update=openshot_live.update,
                  live_show=openshot_live.show,
                  launcher=_openshot_launcher)
SHOTCUT = Editor("Shotcut", ".mlt", "Shotcut", "shotcut.exe",
                 compile_mlt.compile_file, parse_mlt, mlt_unsupported_content, render_audio,
                 engine_check=check_with_melt)

EDITORS = {"openshot": OPENSHOT, "shotcut": SHOTCUT}
DEFAULT = "openshot"
PARSE_ERRORS = (MltParseError, OspParseError)


def editor_for(project: Path | str) -> Editor:
    suffix = Path(project).suffix.lower()
    for editor in EDITORS.values():
        if editor.suffix == suffix:
            return editor
    raise ValueError(f"{Path(project).name} is not a project Frameflow can change: it expects "
                     + " or ".join(f"{e.suffix} ({e.name})" for e in EDITORS.values()))
