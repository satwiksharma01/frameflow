"""Load a compiled project in the real MLT engine (`melt`, bundled with Shotcut).

melt exits 0 even when a referenced source fails to load - it silently
substitutes blank frames - so stderr is checked as well as the exit code.
"""
import os
import shutil
import subprocess
from pathlib import Path


class EngineCheckError(Exception):
    pass


def find_melt() -> str | None:
    for name in ("melt", "melt.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [Path(r"C:\Program Files\Shotcut\melt.exe")]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Shotcut" / "melt.exe")
    return next((str(c) for c in candidates if c.exists()), None)


def check_with_melt(mlt_path: Path | str) -> bool:
    """Raise if the engine rejects the project; return False if melt is unavailable."""
    melt = find_melt()
    if melt is None:
        return False
    result = subprocess.run(
        [melt, str(mlt_path), "-consumer", "null"],
        capture_output=True, text=True, errors="replace", timeout=3600,
    )
    if "failed to load producer" in result.stderr:
        raise EngineCheckError(f"melt could not load a referenced source:\n{result.stderr[-2000:]}")
    if result.returncode != 0:
        raise EngineCheckError(f"melt exited with code {result.returncode}:\n{result.stderr[-2000:]}")
    return True
