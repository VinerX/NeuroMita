# src/handlers/llm_providers/g4f_provider.py
from __future__ import annotations

import importlib
import threading
from typing import Optional

from main_logger import logger
from core.events import get_event_bus, Events
from core.install_requirements import is_pip_spec_satisfied
from core.install_types import InstallPlan, InstallAction

from .base import LLMRequest
from .openai_compatible import OpenAICompatibleProvider


class G4FProvider(OpenAICompatibleProvider):
    name = "g4f"
    priority = 40

    _install_lock = threading.RLock()

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)

    def _get_model_to_use(self, req: LLMRequest) -> str:
        return (req.model or "gpt-3.5-turbo").strip()

    def _target_spec(self, req: LLMRequest) -> str:
        settings = getattr(req, "settings", None) or {}
        v = str(settings.get("G4F_VERSION", "0.4.7.7") or "0.4.7.7").strip()
        if not v or v.lower() == "latest":
            return "g4f"
        return f"g4f=={v}"

    def _build_install_runner(self, spec: str):
        def runner(*args, **kwargs):
            # runner called by InstallController with (pip_installer, callbacks, ctx)
            already = False
            try:
                already = bool(is_pip_spec_satisfied(spec))
            except Exception:
                already = False

            if already:
                return InstallPlan(actions=[], already_installed=True, already_installed_status="Already installed")

            return InstallPlan(
                actions=[
                    InstallAction(
                        type="pip",
                        description=f"Installing {spec}...",
                        progress=10,
                        packages=[spec],
                    )
                ],
                already_installed=False,
                ok_status="Done",
            )

        return runner

    def _ensure_g4f_installed_blocking(self, req: LLMRequest) -> bool:
        spec = self._target_spec(req)

        try:
            if is_pip_spec_satisfied(spec):
                return True
        except Exception:
            pass

        eb = get_event_bus()

        runner = self._build_install_runner(spec)

        payload = {
            "kind": "g4f",
            "item_id": "g4f",
            "task_id": "g4f:g4f",
            "timeout_sec": float((getattr(req, "settings", None) or {}).get("G4F_INSTALL_TIMEOUT_SEC", 3600.0) or 3600.0),
            "meta": {"kind": "g4f", "item_id": "g4f", "spec": spec},
            "runner": runner,
        }

        res = eb.emit_and_wait(Events.Install.RUN_BLOCKING, payload, timeout=float(payload["timeout_sec"]) + 5.0)
        ok = bool(res and res[0] is True)
        if not ok:
            logger.error(f"g4f install failed for spec={spec}")
            return False

        try:
            importlib.invalidate_caches()
        except Exception:
            pass

        try:
            return bool(is_pip_spec_satisfied(spec))
        except Exception:
            return True

    def _get_client(self, req: LLMRequest):
        try:
            from g4f.client import Client as g4fClient
            return g4fClient()
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"g4f import failed unexpectedly: {e}", exc_info=True)
            return None

        # ImportError path: block & install once
        with self._install_lock:
            ok = self._ensure_g4f_installed_blocking(req)
            if not ok:
                return None

            try:
                from g4f.client import Client as g4fClient
                return g4fClient()
            except Exception as e:
                logger.error(f"g4f still not importable after install: {e}", exc_info=True)
                return None