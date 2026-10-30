"""Finding and fetching the transcription engine and model."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import transcribe


class TestFindingAModel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.cache = root / "openwhispr"
        self.cache.mkdir()
        for patch in (mock.patch.object(transcribe, "DEFAULT_MODEL", root / "models" / "default.bin"),
                      mock.patch.object(transcribe, "OPENWHISPR_MODELS", self.cache),
                      mock.patch.dict("os.environ", {"FRAMEFLOW_WHISPER_MODEL": ""})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_openwhisprs_best_model_is_used_when_frameflow_has_none(self):
        for name in ("base", "large-v3-turbo", "small"):
            (self.cache / f"ggml-{name}.bin").write_bytes(b"m")
        self.assertEqual(transcribe.find_model(), self.cache / "ggml-large-v3-turbo.bin")

    def test_frameflows_own_model_comes_first(self):
        (self.cache / "ggml-base.bin").write_bytes(b"m")
        transcribe.DEFAULT_MODEL.parent.mkdir()
        transcribe.DEFAULT_MODEL.write_bytes(b"m")
        self.assertEqual(transcribe.find_model(), transcribe.DEFAULT_MODEL)

    def test_no_model_anywhere_says_how_to_get_one(self):
        with self.assertRaises(transcribe.TranscriptionError) as cm:
            transcribe.find_model()
        self.assertIn("--install", str(cm.exception))


class TestDownloading(unittest.TestCase):
    def fetch(self, body: bytes, sha256: str) -> tuple[Exception | None, list[str]]:
        """What went wrong, if anything, and the files left behind."""
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [body, b""]
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(transcribe.urllib.request, "urlopen", return_value=response):
            error = None
            try:
                transcribe._download("https://example.invalid/file", Path(tmp) / "file.bin", sha256)
            except transcribe.TranscriptionError as e:
                error = e
            return error, sorted(p.name for p in Path(tmp).iterdir())

    def test_a_matching_file_is_kept(self):
        self.assertEqual(self.fetch(b"engine", hashlib.sha256(b"engine").hexdigest()), (None, ["file.bin"]))

    def test_a_file_that_does_not_match_is_thrown_away(self):
        error, left = self.fetch(b"tampered", hashlib.sha256(b"engine").hexdigest())
        self.assertIn("checksum", str(error))
        self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
