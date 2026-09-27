from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_SRC = Path(__file__).resolve().parents[2]
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from managers.unity_retry_store import UnityRetryStore


CHARACTER = "Mita"
MESSAGE_ID = "incoming-1"


class UnityRetryStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="nm_retry_")
        self._prev_root = os.environ.get("NEUROMITA_HISTORIES_DIR")
        os.environ["NEUROMITA_HISTORIES_DIR"] = self._tmp
        UnityRetryStore._delivered_in_process.clear()
        UnityRetryStore._unreadable_paths.clear()
        UnityRetryStore._session_id = "session-current"

    def tearDown(self):
        if self._prev_root is None:
            os.environ.pop("NEUROMITA_HISTORIES_DIR", None)
        else:
            os.environ["NEUROMITA_HISTORIES_DIR"] = self._prev_root
        UnityRetryStore._delivered_in_process.clear()
        UnityRetryStore._unreadable_paths.clear()

    def _add(self, task_uid: str = "task-A") -> None:
        UnityRetryStore.add(CHARACTER, {
            "message_id": MESSAGE_ID,
            "character_id": CHARACTER,
            "active_task_uid": task_uid,
            "request": {"user_input": "hi"},
            "task_data": {"client_id": "c1"},
        })

    def _status(self) -> str:
        record = UnityRetryStore.get(CHARACTER, MESSAGE_ID)
        return str((record or {}).get("status") or "")

    def _result(self) -> dict:
        return {"response": "answer", "character_stats": {}}

    def test_answer_fail_then_retry_regenerates(self):
        self._add()
        self.assertEqual(self._status(), "generating")
        UnityRetryStore.finish_failed_attempt(CHARACTER, MESSAGE_ID, "task-A", "boom")
        self.assertEqual(self._status(), "needs_generation")
        claimed = UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.get("claimed_from_status"), "needs_generation")
        self.assertEqual(self._status(), "generating")
        self.assertTrue(UnityRetryStore.set_active_task(CHARACTER, MESSAGE_ID, "task-B"))
        self.assertTrue(UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating"},
            status="generated_pending_delivery",
            task_uid="task-B",
            expected_task_uid="task-B",
            result=self._result(),
        ))
        self.assertEqual(self._status(), "generated_pending_delivery")

    def test_restart_during_initial_generation(self):
        self._add()
        UnityRetryStore._session_id = "session-next"
        recovered = UnityRetryStore.recover_interrupted_attempts()
        self.assertEqual(recovered, 1)
        record = UnityRetryStore.get(CHARACTER, MESSAGE_ID)
        self.assertEqual(record.get("status"), "needs_generation")
        self.assertEqual(record.get("active_task_uid"), "")
        self.assertTrue(str(record.get("error") or "").strip())

    def test_restart_during_retry_keeps_delivery_pending(self):
        self._add()
        UnityRetryStore.finish_failed_attempt(CHARACTER, MESSAGE_ID, "task-A", "boom")
        UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        self.assertEqual(self._status(), "generating")
        UnityRetryStore._session_id = "session-next"
        UnityRetryStore.recover_interrupted_attempts()
        self.assertEqual(self._status(), "needs_generation")

    def test_delivery_retry_survives_restart_without_regeneration(self):
        self._add()
        UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating"},
            status="generated_pending_voiceover",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        )
        UnityRetryStore.mark_voiceover_failed(CHARACTER, MESSAGE_ID, "task-A", "tts down")
        self.assertEqual(self._status(), "generated_pending_delivery")
        UnityRetryStore._session_id = "session-next"
        UnityRetryStore.recover_interrupted_attempts()
        self.assertEqual(self._status(), "generated_pending_delivery")
        claimed = UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        self.assertEqual(claimed.get("claimed_from_status"), "generated_pending_delivery")

    def test_rapid_double_click_claims_once(self):
        self._add()
        UnityRetryStore.finish_failed_attempt(CHARACTER, MESSAGE_ID, "task-A", "boom")
        first = UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        second = UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_list_read_does_not_reset_active_claim(self):
        self._add()
        UnityRetryStore.finish_failed_attempt(CHARACTER, MESSAGE_ID, "task-A", "boom")
        UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        UnityRetryStore.list_for_character(CHARACTER)
        self.assertEqual(self._status(), "generating")
        self.assertIsNone(UnityRetryStore.claim(CHARACTER, MESSAGE_ID))

    def test_delivery_failure_after_committed_generation(self):
        self._add()
        UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating"},
            status="generated_pending_delivery",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        )
        self.assertTrue(UnityRetryStore.mark_delivery_failed(
            CHARACTER, MESSAGE_ID, "task-A", "socket down"
        ))
        record = UnityRetryStore.get(CHARACTER, MESSAGE_ID)
        self.assertEqual(record.get("status"), "generated_pending_delivery")
        self.assertEqual(record.get("active_task_uid"), "task-A")
        self.assertTrue(record.get("result"))

    def test_late_status_from_old_task_is_fenced(self):
        self._add()
        self.assertTrue(UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating"},
            status="generated_pending_delivery",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        ))
        UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        UnityRetryStore.set_active_task(CHARACTER, MESSAGE_ID, "task-B")
        self.assertFalse(UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"delivery_retrying"},
            status="generated_pending_delivery",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        ))
        record = UnityRetryStore.get(CHARACTER, MESSAGE_ID)
        self.assertEqual(record.get("active_task_uid"), "task-B")

    def test_successful_delivery_is_terminal_tombstone(self):
        self._add()
        UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating"},
            status="generated_pending_delivery",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        )
        UnityRetryStore.claim(CHARACTER, MESSAGE_ID)
        UnityRetryStore.set_active_task(CHARACTER, MESSAGE_ID, "task-B")
        UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"delivery_retrying"},
            status="generated_pending_delivery",
            task_uid="task-B",
            expected_task_uid="task-B",
            result=self._result(),
        )
        self.assertTrue(UnityRetryStore.complete_delivery(CHARACTER, MESSAGE_ID, "task-B"))
        self.assertIsNone(UnityRetryStore.get(CHARACTER, MESSAGE_ID))
        self.assertFalse(UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating", "delivery_retrying", "generated_pending_delivery"},
            status="generated_pending_delivery",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        ))
        self.assertTrue(UnityRetryStore.is_superseded_attempt(CHARACTER, MESSAGE_ID, "task-A"))
        self.assertIsNone(UnityRetryStore.claim(CHARACTER, MESSAGE_ID))

    def test_complete_delivery_sets_tombstone_when_write_fails(self):
        self._add()
        UnityRetryStore.transition(
            CHARACTER, MESSAGE_ID,
            expected_statuses={"generating"},
            status="generated_pending_delivery",
            task_uid="task-A",
            expected_task_uid="task-A",
            result=self._result(),
        )
        original_write = UnityRetryStore._write
        UnityRetryStore._write = classmethod(lambda cls, character_id, records: False)
        try:
            self.assertFalse(UnityRetryStore.complete_delivery(CHARACTER, MESSAGE_ID, "task-A"))
        finally:
            UnityRetryStore._write = original_write
        self.assertTrue(UnityRetryStore.is_superseded_attempt(CHARACTER, MESSAGE_ID, "task-A"))
        self.assertIsNone(UnityRetryStore.claim(CHARACTER, MESSAGE_ID))

    def test_corrupt_json_file_is_quarantined(self):
        path = UnityRetryStore._path(CHARACTER)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(UnityRetryStore.list_for_character(CHARACTER), [])
        self.assertFalse(path.exists())
        quarantined = list(path.parent.glob("unity_retry_outbox.json.corrupt-*"))
        self.assertEqual(len(quarantined), 1)

    def test_protected_path_refuses_overwrite(self):
        path = UnityRetryStore._path(CHARACTER)
        UnityRetryStore._unreadable_paths.add(str(path))
        self.assertFalse(UnityRetryStore._write(CHARACTER, []))
        self.assertFalse(path.exists())

    def test_generated_pending_delivery_without_response_is_unretryable(self):
        path = UnityRetryStore._path(CHARACTER)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": UnityRetryStore.VERSION,
            "records": [{
                "message_id": MESSAGE_ID,
                "character_id": CHARACTER,
                "created_at": time.time(),
                "status": "generated_pending_delivery",
                "active_task_uid": "task-A",
                "result": {},
            }],
        }), encoding="utf-8")
        record = UnityRetryStore.get(CHARACTER, MESSAGE_ID)
        self.assertEqual(record.get("status"), "unretryable")
        self.assertIsNone(UnityRetryStore.claim(CHARACTER, MESSAGE_ID))

    def test_broken_base64_payload_is_unretryable(self):
        path = UnityRetryStore._path(CHARACTER)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": UnityRetryStore.VERSION,
            "records": [{
                "message_id": MESSAGE_ID,
                "character_id": CHARACTER,
                "created_at": time.time(),
                "status": "needs_generation",
                "active_task_uid": "",
                "request": {"image": {"__unity_retry_bytes__": "@@not-base64@@"}},
            }],
        }), encoding="utf-8")
        record = UnityRetryStore.get(CHARACTER, MESSAGE_ID)
        self.assertEqual(record.get("status"), "unretryable")
        self.assertNotIn("request", record)


if __name__ == "__main__":
    unittest.main()
