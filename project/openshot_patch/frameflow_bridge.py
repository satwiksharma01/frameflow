"""Frameflow's control server inside OpenShot (GPLv3, like OpenShot).

Started by the patched classes/app.py once the main window is up. It listens
on localhost only, on a port chosen by the system, and writes that port and a
fresh token to ~/.openshot_qt/frameflow_bridge.json for Frameflow to find.

One JSON object per line in each direction. Every request carries the token.
  {"cmd": "status"}            -> the open project's path, and unsaved changes
  {"cmd": "save"}              -> save the open project to its own file
  {"cmd": "load", "path": p}   -> show the version of p Frameflow just wrote

Loading the project that is already open applies the difference as one
transaction, so the creator sees the change in place and one Ctrl+Z undoes
it. Any other project is opened as if from File > Open.

Runs on Qt's main thread, as OpenShot's own timeline edits do.
"""
import json
import os
import secrets

from PyQt5.QtNetwork import QHostAddress, QTcpServer

from classes import info
from classes.app import get_app
from classes.logger import log

BRIDGE_FILE = os.path.join(info.USER_PATH, "frameflow_bridge.json")
# What a Frameflow edit changes; everything else in the project is left alone.
_LISTS = ("layers", "files", "clips")

_server = None


def start(app):
    global _server
    _server = QTcpServer(app)
    if not _server.listen(QHostAddress.LocalHost, 0):
        log.error("Frameflow bridge could not listen: %s", _server.errorString())
        return
    token = secrets.token_hex(16)
    _server.newConnection.connect(lambda: _accept(token))
    with open(BRIDGE_FILE, "w", encoding="utf-8") as f:
        json.dump({"port": _server.serverPort(), "token": token, "pid": os.getpid()}, f)
    app.aboutToQuit.connect(_stop)
    log.info("Frameflow bridge listening on port %s", _server.serverPort())


def _stop():
    try:
        os.remove(BRIDGE_FILE)
    except OSError:
        pass


def _accept(token):
    socket = _server.nextPendingConnection()
    buffer = bytearray()

    def read():
        buffer.extend(bytes(socket.readAll()))
        while b"\n" in buffer:
            line, _, rest = bytes(buffer).partition(b"\n")
            buffer[:] = rest
            socket.write((json.dumps(_answer(line, token)) + "\n").encode("utf-8"))
            socket.flush()

    socket.readyRead.connect(read)
    socket.disconnected.connect(socket.deleteLater)


def _answer(line, token):
    try:
        request = json.loads(line.decode("utf-8"))
        if request.get("token") != token:
            return {"ok": False, "error": "wrong token"}
        return _handle(request)
    except Exception as ex:
        log.error("Frameflow bridge request failed", exc_info=1)
        return {"ok": False, "error": str(ex)}


def _handle(request):
    app = get_app()
    project = app.project
    command = request.get("cmd")
    if command == "status":
        return {"ok": True, "project": project.current_filepath,
                "unsaved": bool(project.needs_save())}
    if command == "save":
        if not project.current_filepath:
            return {"ok": False, "error": "the open project has never been saved"}
        app.window.save_project(project.current_filepath)
        return {"ok": True, "project": project.current_filepath}
    if command == "load":
        path = request["path"]
        if project.current_filepath and _same(path, project.current_filepath):
            changed = _apply(project.read_from_file(path, path_mode="absolute"))
            return {"ok": True, "applied": changed}
        app.window.OpenProjectSignal.emit(path)
        return {"ok": True, "opened": path}
    return {"ok": False, "error": "unknown command {!r}".format(command)}


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _apply(new):
    """Turn the open project into `new`, as one undoable transaction."""
    import uuid
    updates = get_app().updates
    old = {name: {item["id"]: item for item in get_app().project.get(name) or []} for name in _LISTS}
    fresh = {name: {item["id"]: item for item in new.get(name) or []} for name in _LISTS}
    changed = 0
    updates.transaction_id = str(uuid.uuid4())
    try:
        # Clips go first, so no clip is ever left on a missing layer or file.
        for name in reversed(_LISTS):
            for item_id in old[name]:
                if item_id not in fresh[name]:
                    updates.delete([name, {"id": item_id}])
                    changed += 1
        for name in _LISTS:
            for item_id, item in fresh[name].items():
                if item_id not in old[name]:
                    updates.insert([name], item)
                    changed += 1
                elif item != old[name][item_id]:
                    updates.update([name, {"id": item_id}], item)
                    changed += 1
    finally:
        updates.transaction_id = None
    return changed
