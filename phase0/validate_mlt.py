#!/usr/bin/env python3
"""Validate a generated MLT project file.

Two checks, weakest to strongest:
  1. Well-formed XML (always runs).
  2. Loads in the real MLT engine via `melt` (runs only if melt/Shotcut is
     installed - Shotcut ships melt.exe alongside itself).

Usage:
    python validate_mlt.py <project.mlt>
"""
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CANDIDATE_MELT_PATHS = [
    "melt",
    "melt.exe",
    r"C:\Program Files\Shotcut\melt.exe",
    r"C:\Program Files (x86)\Shotcut\melt.exe",
]
local_app_data = os.environ.get("LOCALAPPDATA")
if local_app_data:
    CANDIDATE_MELT_PATHS.append(str(Path(local_app_data) / "Programs" / "Shotcut" / "melt.exe"))


def find_melt() -> str | None:
    for candidate in CANDIDATE_MELT_PATHS:
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return candidate
    return None


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: validate_mlt.py <project.mlt>")
        sys.exit(1)
    path = Path(sys.argv[1])

    try:
        ET.parse(path)
        print(f"[PASS] well-formed XML: {path}")
    except ET.ParseError as e:
        print(f"[FAIL] not well-formed XML: {e}")
        sys.exit(1)

    melt = find_melt()
    if not melt:
        print(
            "[SKIP] melt engine not found on PATH or common Shotcut install dirs "
            "- install Shotcut to run this check"
        )
        return

    print(f"[INFO] running melt engine check via {melt}")
    result = subprocess.run(
        [melt, str(path), "-consumer", "null"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # melt exits 0 even when a referenced producer fails to load (it falls
    # back to blank frames), so the exit code alone is not trustworthy.
    if "failed to load producer" in result.stderr:
        print("[FAIL] melt could not load one or more referenced source files:")
        print(result.stderr[-2000:])
        sys.exit(1)
    if result.returncode != 0:
        print(f"[FAIL] melt exited with code {result.returncode}")
        print(result.stderr[-2000:])
        sys.exit(1)
    print("[PASS] melt engine loaded and processed the project without error")


if __name__ == "__main__":
    main()
