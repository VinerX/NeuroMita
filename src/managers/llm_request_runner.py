# src/managers/llm_request_runner.py
from __future__ import annotations

import concurrent.futures
import os
import threading
from typing import Any, Callable, Optional

from main_logger import logger
from core.events import Events
from core.executors import PoolSaturated, Pools, executors
from handlers.llm_providers.errors import (
    LLMProviderError,
    build_configuration_error,
    build_provider_error,
    coerce_provider_error,
)
from utils import _, save_combined_messages

from managers.api_preset_resolver import ApiPresetResolver, PresetSettings
from handlers.llm_providers.base import LLMResponse, StreamCallback
from handlers.llm_providers.base import RequestCancellation
from handlers.llm_providers.streaming import (
    StreamDeadlineExceeded,
    StreamDeadlinePolicy,
    StreamEventChannel,
    StreamSupervisor,
)
from managers.provider_manager import ProviderManager


class LLMRequestRunner:
    """
    Отвечает только за:
    - retry loop
    - timeout выполнения provider_manager.generate
    - задержку между попытками
    - ротацию ключей через ApiPresetResolver

    NOTE: GPT4FREE_LAST_ATTEMPT removed from logic.
    """

    def __init__(
        self,
        settings: Any,
        preset_resolver: ApiPresetResolver,
        event_bus: Any,
    ):
        self.settings = settings
        self.preset_resolver = preset_resolver
        self.event_bus = event_bus
        self._run_state = threading.local()
        self._shutdown_event = threading.Event()
        self.last_error = None
        self._abort_chain = False
        self.provider_manager = ProviderManager()

    @property
    def last_error(self) -> Optional[LLMProviderError]:
        return getattr(self._run_state, "last_error", None)

    @last_error.setter
    def last_error(self, value: Optional[LLMProviderError]) -> None:
        self._run_state.last_error = value

    @property
    def _abort_chain(self) -> bool:
        return bool(getattr(self._run_state, "abort_chain", False))

    @_abort_chain.setter
    def _abort_chain(self, value: bool) -> None:
        self._run_state.abort_chain = bool(value)

    def run(
        self,
        *,
        messages: list,
        preset_id: Optional[int],
        stream_callback: Optional[StreamCallback],
        build_request: Callable[[PresetSettings, str], Any],
        max_attempts: int,
        retry_delay: float,
        request_timeout: float,
        suppress_failure_events: bool = False,
    ) -> Optional[LLMResponse]:
        if messages is None:
            messages = []
        self.last_error = None
        self._abort_chain = False

        try:
            preset_chain = self.preset_resolver.resolve_chain(preset_id)
        except Exception as e:
            logger.error(f"[LLMRequestRunner] Failed to resolve preset chain: {e}", exc_info=True)
            return LLMResponse(text=None, error_message=f"Failed to resolve preset: {e}")

        if not preset_chain:
            logger.error("[LLMRequestRunner] Empty preset chain (no main, no fallbacks).")
            return LLMResponse(text=None, error_message="Empty preset chain (no main, no fallbacks).")

        total_presets = len(preset_chain)
        last_response: Optional[LLMResponse] = None
        stream_channel_holder: list[Optional[StreamEventChannel]] = [None]
        for chain_idx, base_preset in enumerate(preset_chain, start=1):
            preset_label = base_preset.preset_name or f"preset#{chain_idx}"
            if chain_idx > 1:
                logger.warning(
                    f"[LLMRequestRunner] Switching to fallback {chain_idx}/{total_presets}: "
                    f"'{preset_label}' model='{base_preset.api_model}'"
                )

            response = self._run_on_preset(
                base_preset=base_preset,
                messages=messages,
                build_request=build_request,
                pm=self.provider_manager,
                max_attempts=int(max_attempts),
                retry_delay=float(retry_delay),
                request_timeout=float(request_timeout),
                suppress_failure_events=bool(suppress_failure_events),
                chain_pos=chain_idx,
                chain_total=total_presets,
                stream_channel_holder=stream_channel_holder,
            )
            last_response = response
            if response and response.text:
                self.last_error = None
                if stream_channel_holder[0] is not None:
                    stream_channel_holder[0].complete(response)
                if chain_idx > 1:
                    logger.info(f"[LLMRequestRunner] Fallback preset '{preset_label}' succeeded.")
                return response
            if self._abort_chain:
                break

        # Вся цепочка пресетов исчерпана — терминальный отказ генерации.
        terminal_summary = (
            self.last_error.to_console_summary()
            if self.last_error is not None
            else "unknown generation failure"
        )
        logger.error("All generation attempts failed across preset chain: %s", terminal_summary)
        if self.last_error and not suppress_failure_events:
            provider_error = self.last_error.to_payload()
            self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {
                "error": self.last_error.to_user_message(),
                "details": self.last_error.to_console_summary(),
                "provider_error": provider_error,
            })
        if stream_channel_holder[0] is not None and self.last_error is not None:
            stream_channel_holder[0].fail(self.last_error)
        if last_response is not None:
            return last_response
        return LLMResponse(text=None, error_message="All generation attempts failed.")

    def _run_on_preset(
        self,
        *,
        base_preset: PresetSettings,
        messages: list,
        build_request: Callable[[PresetSettings, str], Any],
        pm: Any,
        max_attempts: int,
        retry_delay: float,
        request_timeout: float,
        suppress_failure_events: bool,
        chain_pos: int,
        chain_total: int,
        stream_channel_holder: list[Optional[StreamEventChannel]],
    ) -> LLMResponse:
        preset_tag = f"[{chain_pos}/{chain_total} {base_preset.preset_name}]"

        last_error_message: Optional[str] = None
        last_provider_name: Optional[str] = None
        last_model_name: Optional[str] = None

        for attempt in range(1, max_attempts + 1):
            logger.info(f"{preset_tag} Generation attempt {attempt}/{max_attempts}")

            if self._debug_dumps_enabled():
                try:
                    _base = os.environ.get("NEUROMITA_BASE_DIR", "")
                    _log_path = os.path.join(_base, "SavedMessages", "last_attempt_log") if _base else "SavedMessages/last_attempt_log"
                    executors().try_submit(Pools.DEBUG_DUMP, save_combined_messages, list(messages), _log_path)
                except Exception:
                    pass

            preset_attempt = self.preset_resolver.apply_key_rotation(base_preset, attempt)
            effective_model = (preset_attempt.api_model or "").strip()
            last_provider_name = preset_attempt.provider_name
            last_model_name = effective_model

            try:
                req = build_request(preset_attempt, effective_model)
            except Exception as e:
                logger.error(f"{preset_tag} Failed to build request: {e}", exc_info=True)
                last_error_message = f"Failed to build request: {e}"
                self.last_error = build_provider_error(
                    provider=getattr(preset_attempt, "provider_name", "unknown"),
                    provider_message=last_error_message,
                    url=getattr(preset_attempt, "api_url", None),
                )
                req = None

            if req is None:
                if attempt < max_attempts:
                    if not suppress_failure_events:
                        self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT)
                    if self._shutdown_event.wait(max(0.0, float(retry_delay))):
                        self._abort_chain = True
                        break
                continue

            req.extra = dict(getattr(req, "extra", None) or {})
            req.extra.setdefault("http_timeout_seconds", float(request_timeout))
            if req.stream:
                req.extra.setdefault("http_read_timeout_seconds", 300.0)
                if stream_channel_holder[0] is None:
                    stream_channel_holder[0] = StreamEventChannel(req)
                req.extra["_stream_event_channel"] = stream_channel_holder[0]
            cancellation = RequestCancellation()
            req.extra["_request_cancellation"] = cancellation

            validation_error = self._validate_request(req)
            if validation_error is not None:
                self.last_error = validation_error
                last_error_message = validation_error.to_user_message()
                logger.error(
                    f"{preset_tag} Generation attempt {attempt} aborted before provider call: "
                    f"{validation_error.to_console_summary()}"
                )
                break

            try:
                response = self._call_with_timeout(
                    pm.generate,
                    args=(req,),
                    timeout=request_timeout,
                    cancellation=cancellation,
                    stream_policy=(StreamDeadlinePolicy.for_request(req) if req.stream else None),
                )
                if response and response.text:
                    self.last_error = None
                    return response

                if response:
                    last_provider_name = response.provider_name or last_provider_name
                    last_model_name = response.model or last_model_name
                    finish_reason = f", finish_reason={response.finish_reason}" if response.finish_reason else ""
                    last_error_message = response.error_message or f"Provider returned empty response{finish_reason}."
                    self.last_error = build_provider_error(
                        provider=last_provider_name or getattr(req, "provider_name", "unknown"),
                        provider_message=last_error_message,
                        url=getattr(req, "api_url", None),
                    )
                    logger.debug(
                        "Generation attempt %s returned no text; delegated to retry policy: "
                        "provider=%s, model=%s%s, error=%s",
                        attempt,
                        last_provider_name,
                        last_model_name,
                        finish_reason,
                        last_error_message,
                    )
                else:
                    last_error_message = "Provider returned no response object."
                    self.last_error = build_provider_error(
                        provider=getattr(req, "provider_name", "unknown"),
                        provider_message=last_error_message,
                        url=getattr(req, "api_url", None),
                    )
                    logger.debug(
                        "Generation attempt %s returned no response object; delegated to retry policy.",
                        attempt,
                    )
            except concurrent.futures.TimeoutError:
                last_error_message = cancellation.reason or f"Attempt {attempt} timed out after {request_timeout}s."
                retryable_before_response = bool(
                    (req.stream and not cancellation.response_body_started)
                    or (
                        not req.stream
                        and not cancellation.response_headers_received
                    )
                )
                self._abort_chain = not retryable_before_response
                logger.debug("%s %s", preset_tag, last_error_message)
                self.last_error = LLMProviderError(
                    provider=getattr(req, "provider_name", "unknown"),
                    friendly_message=_("Ошибка сети - Сервер не ответил вовремя.", "Network error - The server did not respond in time."),
                    provider_message=last_error_message,
                    retryable=retryable_before_response,
                    code=(
                        "stream.timeout_before_body"
                        if req.stream and retryable_before_response
                        else "request.timeout_before_response"
                        if retryable_before_response
                        else "timeout.attempt"
                    ),
                    phase="stream" if req.stream else "request",
                    url=getattr(req, "api_url", None),
                )
            except Exception as e:
                last_error_message = f"Error during generation attempt {attempt}: {e}"
                self.last_error = coerce_provider_error(
                    getattr(req, "provider_name", "unknown"),
                    e,
                    url=getattr(req, "api_url", None),
                )

            if req.stream and cancellation.response_body_started and self.last_error is not None:
                self._abort_chain = True
                self.last_error.retryable = False
                self.last_error.code = self.last_error.code or (
                    "stream.interrupted_after_output"
                    if cancellation.has_meaningful_stream_event
                    else "stream.interrupted_after_body_started"
                )
                self.last_error.phase = self.last_error.phase or "stream"

            should_retry = bool(
                attempt < max_attempts and (
                    self.last_error is None or bool(getattr(self.last_error, "retryable", False))
                )
            )
            if should_retry:
                logger.warning(
                    "%s Generation attempt %s/%s failed; retrying: %s",
                    preset_tag,
                    attempt,
                    max_attempts,
                    self.last_error.to_console_summary() if self.last_error else last_error_message,
                )
                if not suppress_failure_events:
                    error_payload = self.last_error.to_payload() if self.last_error else None
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE_ATTEMPT, {
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "provider_error": error_payload,
                    })
                retry_wait = self._resolve_retry_delay(retry_delay, self.last_error)
                if self._shutdown_event.wait(retry_wait):
                    self._abort_chain = True
                    break
            elif attempt < max_attempts and self.last_error is not None:
                logger.debug(
                    f"{preset_tag} Stopping retries after non-retryable failure: "
                    f"{self.last_error.to_console_summary()}"
                )
                break

        logger.debug("%s Preset attempts exhausted: %s", preset_tag, last_error_message or "unknown failure")
        return LLMResponse(
            text=None,
            model=last_model_name,
            provider_name=last_provider_name,
            error_message=(
                self.last_error.to_user_message()
                if self.last_error
                else last_error_message or "All generation attempts failed."
            ),
            error_details=(self.last_error.to_payload() if self.last_error else None),
        )

    def _call_with_timeout(
        self,
        func,
        args=(),
        kwargs=None,
        timeout: float = 30.0,
        cancellation: RequestCancellation | None = None,
        stream_policy: StreamDeadlinePolicy | None = None,
    ):
        """Вызвать func с ограничением по времени.

        Раньше здесь был `with ThreadPoolExecutor(...)`: его __exit__ делает
        shutdown(wait=True), поэтому после TimeoutError вызывающий всё равно
        досиживал до конца HTTP-запроса — таймаут был декоративным. Плюс на
        каждую попытку создавался новый пул.
        """
        if kwargs is None:
            kwargs = {}
        pool = executors().pool(Pools.LLM_HTTP)
        try:
            future = pool.try_submit(func, *args, **kwargs)
        except PoolSaturated as exc:
            raise RuntimeError(
                "LLM HTTP pool is saturated by unfinished provider requests"
            ) from exc
        if stream_policy is None:
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                self._abort_future(
                    future,
                    pool,
                    cancellation,
                    reason=f"Provider attempt exceeded {timeout:.1f}s.",
                    grace_timeout=timeout,
                )

        supervisor = StreamSupervisor(cancellation, stream_policy)
        while True:
            try:
                supervisor.raise_if_expired()
            except StreamDeadlineExceeded as exc:
                self._abort_future(
                    future,
                    pool,
                    cancellation,
                    reason=str(exc),
                    grace_timeout=supervisor.poll_interval,
                )
            try:
                return future.result(timeout=supervisor.poll_interval)
            except concurrent.futures.TimeoutError:
                if future.done():
                    return future.result()

    @staticmethod
    def _abort_future(future, pool, cancellation, *, reason: str, grace_timeout: float):
        if cancellation is not None:
            cancellation.cancel(reason)
        future.cancel()
        try:
            future.result(timeout=min(1.0, max(0.1, float(grace_timeout) * 0.05)))
        except concurrent.futures.TimeoutError:
            if not future.done():
                abandoned = pool.abandon(future)
                if abandoned:
                    logger.warning(
                        "LLM provider did not stop within the cancellation grace period; "
                        "the detached daemon worker will be ignored and its pool slot was replaced "
                        "| retired_workers=%s/%s",
                        pool.retired_workers,
                        pool.max_retired_workers,
                    )
                else:
                    retired_workers = pool.retired_workers
                    retired_limit = pool.max_retired_workers
                    replacement_reason = (
                        "retired-worker limit reached"
                        if retired_limit is not None and retired_workers >= retired_limit
                        else "replacement worker could not be started"
                    )
                    logger.error(
                        "LLM provider did not stop and its worker could not be replaced (%s); "
                        "the occupied pool slot will not be replaced until the provider returns "
                        "| retired_workers=%s/%s",
                        replacement_reason,
                        retired_workers,
                        retired_limit,
                    )
        except Exception:
            pass
        raise concurrent.futures.TimeoutError(reason)

    def _debug_dumps_enabled(self) -> bool:
        env_value = str(os.environ.get("NEUROMITA_DEBUG_DUMPS", "")).strip().lower()
        if env_value in {"1", "true", "yes", "on"}:
            return True
        try:
            return bool(self.settings.get("DEBUG_SAVE_LLM_DUMPS", False))
        except Exception:
            return False

    def _resolve_retry_delay(
        self,
        retry_delay: float,
        error: Optional[LLMProviderError],
    ) -> float:
        try:
            maximum = max(0.0, float(self.settings.get("LLM_MAX_RETRY_DELAY_SECONDS", 120.0)))
        except Exception:
            maximum = 120.0
        provider_delay = float(getattr(error, "retry_after_seconds", 0.0) or 0.0)
        return min(maximum, max(0.0, float(retry_delay), provider_delay))

    def close(self) -> None:
        self._shutdown_event.set()
        self.provider_manager.close()

    def _validate_request(self, req) -> Optional[LLMProviderError]:
        provider = getattr(req, "provider_name", "unknown") or "unknown"
        url = getattr(req, "api_url", None)
        model = str(getattr(req, "model", "") or "").strip()

        if not str(provider).strip():
            return build_configuration_error(
                "unknown",
                "API provider not configured",
                url=url,
            )
        if not str(url or "").strip():
            return build_configuration_error(
                provider,
                "API preset not configured: missing API URL",
                url=url,
            )
        if not model:
            return build_configuration_error(
                provider,
                "API preset not configured: missing API model",
                url=url,
            )
        # Ключ требуем только у официальных облачных провайдеров (openai/gemini).
        # 'common' — это произвольный OpenAI-совместимый эндпоинт: помимо
        # localhost-серверов (LM Studio / Ollama) бывают и безключевые шлюзы,
        # self-hosted и LAN/туннели, поэтому ключ для него не обязателен.
        if (
            provider in {"openai", "gemini"}
            and str(url or "").startswith(("http://", "https://"))
            and "localhost" not in str(url or "").lower()
            and "127.0.0.1" not in str(url or "").lower()
            and not str(getattr(req, "api_key", "") or "").strip()
        ):
            return build_configuration_error(
                provider,
                "API preset not configured: missing API key",
                url=url,
            )
        return None
