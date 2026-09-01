from pathlib import Path
from importlib.util import find_spec
from tempfile import TemporaryDirectory
from unittest import TestCase, skipIf

from app.services.index_version import content_hash, file_hash, index_fingerprint


class IndexVersionTests(TestCase):
    def test_bytes_and_file_have_the_same_hash(self):
        payload = "同一份内容就该是同一个指纹，别整玄学。".encode("utf-8")

        with TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "note.md"
            file_path.write_bytes(payload)

            self.assertEqual(content_hash(payload), file_hash(file_path))

    def test_different_content_has_different_hash(self):
        self.assertNotEqual(content_hash(b"old"), content_hash(b"new"))

    @skipIf(find_spec("pydantic_settings") is None, "未安装完整后端依赖")
    def test_index_fingerprint_is_stable(self):
        self.assertEqual(index_fingerprint(), index_fingerprint())
        self.assertEqual(len(index_fingerprint()), 64)
