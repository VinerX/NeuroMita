from __future__ import annotations

import json
import os
import shutil
import unittest
import uuid
from pathlib import Path


class SharedImageTransferTests(unittest.TestCase):
    def setUp(self):
        self._workspace_tmp_root = os.path.join(os.getcwd(), ".tmp_test_shared_image_transfer")
        os.makedirs(self._workspace_tmp_root, exist_ok=True)
        self._tmp_dir = os.path.join(self._workspace_tmp_root, uuid.uuid4().hex)
        os.makedirs(self._tmp_dir, exist_ok=True)
        self._old_base = os.environ.get("NEUROMITA_BASE_DIR")
        self._old_shared = os.environ.get("NEUROMITA_SHARED_TRANSFER_DIR")
        os.environ["NEUROMITA_BASE_DIR"] = self._tmp_dir
        os.environ["NEUROMITA_SHARED_TRANSFER_DIR"] = os.path.join(self._tmp_dir, "SharedTransfer")

    def tearDown(self):
        if self._old_base is None:
            os.environ.pop("NEUROMITA_BASE_DIR", None)
        else:
            os.environ["NEUROMITA_BASE_DIR"] = self._old_base

        if self._old_shared is None:
            os.environ.pop("NEUROMITA_SHARED_TRANSFER_DIR", None)
        else:
            os.environ["NEUROMITA_SHARED_TRANSFER_DIR"] = self._old_shared

        shutil.rmtree(self._tmp_dir, ignore_errors=True)
        try:
            os.rmdir(self._workspace_tmp_root)
        except OSError:
            pass

    def test_collects_relative_shared_image_and_deletes_temp_file(self):
        from game_connections.shared_image_transfer import ensure_shared_transfer_dirs, collect_context_images

        dirs = ensure_shared_transfer_dirs()
        image_path = dirs["images"] / "frame_a.jpg"
        payload = b"frame-bytes-a"
        image_path.write_bytes(payload)

        images = collect_context_images({"image_paths": ["frame_a.jpg"]})

        self.assertEqual(images, [payload])
        self.assertFalse(image_path.exists())

    def test_manifest_paths_resolve_relative_to_manifest_location(self):
        from game_connections.shared_image_transfer import ensure_shared_transfer_dirs, collect_context_images

        dirs = ensure_shared_transfer_dirs()
        client_dir = dirs["root"] / "clients" / "client_1"
        client_dir.mkdir(parents=True, exist_ok=True)

        image_path = client_dir / "frame_b.jpg"
        manifest_path = dirs["manifests"] / "batch.json"
        payload = b"frame-bytes-b"
        image_path.write_bytes(payload)
        manifest_path.write_text(
            json.dumps({
                "image_paths": ["../clients/client_1/frame_b.jpg"],
                "delete_after_read": True,
            }),
            encoding="utf-8",
        )

        images = collect_context_images({"image_manifest_path": "batch.json"}, client_id="client:1")

        self.assertEqual(images, [payload])
        self.assertFalse(image_path.exists())
        self.assertFalse(manifest_path.exists())

    def test_rejects_paths_outside_shared_root(self):
        from game_connections.shared_image_transfer import collect_context_images

        outside = Path(self._tmp_dir) / "outside.jpg"
        outside.write_bytes(b"outside")

        images = collect_context_images({"image_paths": [str(outside)]})

        self.assertEqual(images, [])
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()
