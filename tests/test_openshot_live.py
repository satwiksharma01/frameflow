"""Frameflow's build of OpenShot and the window it can drive."""
import importlib.util
import json
import socket
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

PATCH = Path(__file__).resolve().parent.parent / "project" / "openshot_patch"


def _load_bridge(project):
    """frameflow_bridge with OpenShot's modules replaced by just enough to run _apply."""
    updates = mock.Mock(transaction_id=None)
    app = types.SimpleNamespace(updates=updates, project=project)
    stubs = {
        "PyQt5": types.ModuleType("PyQt5"),
        "PyQt5.QtNetwork": types.SimpleNamespace(QHostAddress=None, QTcpServer=None),
        "classes": types.ModuleType("classes"),
        "classes.info": types.SimpleNamespace(USER_PATH=tempfile.gettempdir()),
        "classes.app": types.SimpleNamespace(get_app=lambda: app),
        "classes.logger": types.SimpleNamespace(log=mock.Mock()),
    }
    stubs["classes"].info = stubs["classes.info"]
    with mock.patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("frameflow_bridge", PATCH / "frameflow_bridge.py")
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
    return bridge, updates


class TestApplyingANewVersion(unittest.TestCase):
    def test_the_difference_is_one_transaction_clips_removed_first(self):
        old = {"layers": [{"id": "L1"}], "files": [{"id": "F1"}],
               "clips": [{"id": "C1", "position": 0}, {"id": "C2", "position": 5}]}
        new = {"layers": [{"id": "L1"}], "files": [{"id": "F1"}, {"id": "F2"}],
               "clips": [{"id": "C1", "position": 1}, {"id": "C3", "position": 5}]}
        bridge, updates = _load_bridge(types.SimpleNamespace(get=lambda name: old[name]))
        seen = []
        for kind in ("insert", "update", "delete"):
            getattr(updates, kind).side_effect = (
                lambda *args, kind=kind: seen.append((kind, args, updates.transaction_id)))

        self.assertEqual(bridge._apply(new), 4)
        self.assertEqual([(k, a) for k, a, _ in seen], [
            ("delete", (["clips", {"id": "C2"}],)),
            ("insert", (["files"], {"id": "F2"})),
            ("update", (["clips", {"id": "C1"}], {"id": "C1", "position": 1})),
            ("insert", (["clips"], {"id": "C3", "position": 5})),
        ])
        self.assertEqual(len({tid for _, _, tid in seen}), 1)    # one Ctrl+Z
        self.assertIsNotNone(seen[0][2])
        self.assertIsNone(updates.transaction_id)


class TestLiveClient(unittest.TestCase):
    def setUp(self):
        from project import openshot_live
        self.live = openshot_live
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge_file = Path(self.tmp.name) / "frameflow_bridge.json"
        patcher = mock.patch.object(openshot_live, "BRIDGE_FILE", self.bridge_file)
        patcher.start()
        self.addCleanup(patcher.stop)

    def serve(self, answer):
        """A one-request server standing in for OpenShot's window."""
        server = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(server.close)
        received = []

        def run():
            conn, _ = server.accept()
            with conn:
                received.append(json.loads(conn.makefile().readline()))
                conn.sendall((json.dumps(answer) + "\n").encode())

        threading.Thread(target=run, daemon=True).start()
        self.bridge_file.write_text(json.dumps({"port": server.getsockname()[1], "token": "t0k"}))
        return received

    def test_no_window_means_no_answer(self):
        self.assertIsNone(self.live.request("status"))

    def test_a_request_carries_the_token(self):
        received = self.serve({"ok": True, "project": "x.osp", "unsaved": False})
        self.assertEqual(self.live.request("status")["project"], "x.osp")
        self.assertEqual(received, [{"cmd": "status", "token": "t0k"}])

    def test_an_edit_leaves_a_window_showing_another_project_alone(self):
        received = self.serve({"ok": True, "project": str(Path(self.tmp.name) / "other.osp")})
        self.assertFalse(self.live.update(Path(self.tmp.name) / "mine.osp"))
        self.assertEqual([r["cmd"] for r in received], ["status"])

    def test_a_window_with_nothing_unsaved_is_not_saved(self):
        mine = Path(self.tmp.name) / "mine.osp"
        received = self.serve({"ok": True, "project": str(mine), "unsaved": False})
        self.assertFalse(self.live.save_if_open(mine))
        self.assertEqual([r["cmd"] for r in received], ["status"])

    def test_a_refusal_is_raised(self):
        self.serve({"ok": False, "error": "the open project has never been saved"})
        with self.assertRaises(RuntimeError):
            self.live.request("save")


class TestBuild(unittest.TestCase):
    def test_the_build_patches_a_copy_and_leaves_the_install_alone(self):
        from project import openshot_build
        source = openshot_build.install_dir()
        if source is None:
            self.skipTest("OpenShot is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "OpenShot"
            with mock.patch.object(openshot_build, "build_dir", lambda: target):
                openshot_build.build()
                app = (target / "classes" / "app.py").read_text(encoding="utf-8")
                self.assertIn("frameflow_bridge.start(self)", app)
                self.assertTrue((target / "lib").is_junction())
                openshot_build._remove(target)
        self.assertNotIn("frameflow", (source / "classes" / "app.py").read_text(encoding="utf-8"))
        self.assertTrue((source / "lib").exists())


if __name__ == "__main__":
    unittest.main()
