#!/usr/bin/env python3
"""Talk to the OpenShot window Frameflow's build of OpenShot has open.

The control server inside it (openshot_patch/frameflow_bridge.py) writes its
port and token to ~/.openshot_qt/frameflow_bridge.json. When no such window is
running, every call here returns None and Frameflow works with files alone.
"""
import json
import os
import socket
from pathlib import Path

BRIDGE_FILE = Path.home() / ".openshot_qt" / "frameflow_bridge.json"


def request(command: str, **fields) -> dict | None:
    try:
        bridge = json.loads(BRIDGE_FILE.read_text(encoding="utf-8"))
        with socket.create_connection(("127.0.0.1", bridge["port"]), timeout=10) as s:
            s.sendall((json.dumps({"cmd": command, "token": bridge["token"], **fields}) + "\n").encode())
            reply = b""
            while not reply.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                reply += chunk
    except (OSError, ValueError, KeyError):
        return None         # no window open, or one from before it last closed
    answer = json.loads(reply) if reply else None
    if answer is not None and not answer.get("ok"):
        raise RuntimeError(f"OpenShot refused {command}: {answer.get('error')}")
    return answer


def _open_status(project: Path) -> dict | None:
    """The window's status, if this project is the one open in it."""
    status = request("status")
    if status and status.get("project") and (
            os.path.normcase(Path(status["project"]).resolve()) == os.path.normcase(Path(project).resolve())):
        return status
    return None


def _is_open(project: Path) -> bool:
    return _open_status(project) is not None


def save_if_open(project: Path) -> bool:
    """Save the creator's unsaved work first, so Frameflow reads what they see."""
    status = _open_status(project)
    if not (status and status.get("unsaved")):
        return False
    request("save")
    return True


def update(project: Path) -> bool:
    """Apply the version Frameflow just wrote, if this project is open in the window."""
    if not _is_open(project):
        return False
    return request("load", path=str(Path(project).resolve())) is not None


def show(project: Path) -> bool:
    """Put the project in front of the creator, in the open window if there is one."""
    return request("load", path=str(Path(project).resolve())) is not None
