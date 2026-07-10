from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class StartupTrace:
    def __init__(self) -> None:
        self._started_perf = time.perf_counter()
        self._started_wall = datetime.now(timezone.utc)
        self._lock = threading.RLock()
        self._marks: list[dict[str, Any]] = []
        self._base_dir = ""
        self._mode = "unknown"
        self._owner_pid: int | None = None

    def claim_owner(self) -> bool:
        env_key = "NEUROMITA_STARTUP_TRACE_OWNER_PID"
        configured = str(os.environ.get(env_key, "") or "").strip()
        current = os.getpid()
        if configured:
            try:
                self._owner_pid = int(configured)
            except ValueError:
                self._owner_pid = current
            return self._owner_pid == current
        os.environ[env_key] = str(current)
        self._owner_pid = current
        return True

    @property
    def enabled(self) -> bool:
        return self._owner_pid == os.getpid()

    def configure(self, *, base_dir: str = "", mode: str = "") -> None:
        if not self.enabled:
            return
        with self._lock:
            if base_dir:
                self._base_dir = os.path.abspath(base_dir)
            if mode:
                self._mode = str(mode)

    def mark(self, name: str, **data: Any) -> float:
        if not self.enabled:
            return 0.0
        elapsed_ms = (time.perf_counter() - self._started_perf) * 1000.0
        record = {
            "name": str(name),
            "elapsed_ms": round(elapsed_ms, 3),
            "thread": threading.current_thread().name,
        }
        if data:
            record["data"] = data
        with self._lock:
            self._marks.append(record)
        return elapsed_ms

    @contextmanager
    def phase(self, name: str, **data: Any) -> Iterator[None]:
        started = time.perf_counter()
        self.mark(f"{name}.start", **data)
        try:
            yield
        except Exception as exc:
            self.mark(
                f"{name}.failed",
                duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        else:
            self.mark(
                f"{name}.done",
                duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            marks = [dict(item) for item in self._marks]
        return {
            "schema": 1,
            "pid": os.getpid(),
            "mode": self._mode,
            "started_at": self._started_wall.isoformat(),
            "total_elapsed_ms": round(
                (time.perf_counter() - self._started_perf) * 1000.0,
                3,
            ),
            "marks": marks,
        }

    def write(self, *, suffix: str = "latest") -> str:
        if not self.enabled or not self._base_dir:
            return ""
        logs_dir = Path(self._base_dir) / "Logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        target = logs_dir / f"startup_trace_{suffix}.json"
        payload = self.snapshot()
        fd, temp_path = tempfile.mkstemp(
            prefix=".startup-trace-",
            suffix=".json.tmp",
            dir=str(logs_dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp_path, target)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
        return str(target)


startup_trace = StartupTrace()
