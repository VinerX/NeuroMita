from __future__ import annotations
from core.error_utils import format_exception

import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from main_logger import logger
from core.message_content import MessageContentCodec
from handlers.llm_providers.errors import build_provider_error, build_stream_error, coerce_provider_error
from handlers.llm_providers.param_mapper import filter_jsonable_params
from schemas.structured_response import StructuredResponse

from .base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    StreamCallback,
    StreamChannel,
    check_request_cancelled,
    normalize_usage_payload,
)
from .streaming import StreamAccumulator, iter_json_values, iter_sse_data, track_response_body


class GeminiProvider(BaseProvider):
    name = "gemini"
    priority = 20
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False
    tools_dialect_id: str = "gemini"

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)

    def generate(self, req: LLMRequest) -> LLMResponse:
        return self.generate_request_gemini(req)

    @staticmethod
    def _should_send_native_structured_output(capabilities: dict | None) -> bool:
        """Keep application JSON parsing separate from Gemini schema transport."""
        caps = capabilities or {}
        if not caps.get("structured_output", False):
            return False
        model_profile = caps.get("model_profile")
        return not (
            isinstance(model_profile, dict)
            and not bool(model_profile.get("native_structured_output", True))
        )

    @staticmethod
    def _request_url(req: LLMRequest, *, stream: bool) -> str:
        url = str(req.api_url or "")
        if not stream:
            return url
        parsed = urlsplit(url)
        path = parsed.path.replace(":generateContent", ":streamGenerateContent")
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.setdefault("alt", "sse")
        return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query), parsed.fragment))

    def _supports_system_instruction(self, model: str) -> bool:
        m = (model or "").lower()
        if "gemma" in m and "gemini" not in m:
            return False
        return True

    def _system_parts_to_text(self, system_parts: list) -> str:
        chunks = []
        for p in system_parts or []:
            if isinstance(p, dict) and p.get("text"):
                chunks.append(str(p["text"]))
            else:
                try:
                    chunks.append(json.dumps(p, ensure_ascii=False))
                except Exception:
                    chunks.append(str(p))
        return "\n".join([c for c in chunks if c and str(c).strip()]).strip()

    def _inject_system_into_contents(self, system_parts: list, contents: list) -> list:
        sys_text = self._system_parts_to_text(system_parts)
        if not sys_text:
            return contents

        prefix = f"[SYSTEM INFO]\n{sys_text}\n\n"

        if not contents:
            return [{
                "role": "user",
                "parts": [{"text": prefix}],
            }]

        for msg in contents:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            parts = msg.get("parts") or []
            if not isinstance(parts, list):
                parts = []

            inserted = False
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    part["text"] = f"{prefix}{part.get('text', '')}"
                    inserted = True
                    break

            if not inserted:
                parts.insert(0, {"text": prefix})

            msg["parts"] = parts
            return contents

        return [{"role": "user", "parts": [{"text": prefix}]}] + contents

    _INLINE_SYSTEM_TAG = "[SYSTEM INFO]"

    @staticmethod
    def _parts_have_payload(parts: list) -> bool:
        for part in parts or []:
            if not isinstance(part, dict):
                continue
            if "text" in part:
                if str(part.get("text") or "").strip():
                    return True
                continue
            return True  # inline_data / functionCall и прочее непустое по определению
        return False

    @classmethod
    def _prefix_parts_with_tag(cls, parts: list) -> list:
        """Помечает parts тегом, чтобы служебный блок не читался как речь игрока."""
        out = [dict(p) if isinstance(p, dict) else p for p in parts]
        for part in out:
            if isinstance(part, dict) and "text" in part:
                part["text"] = f"{cls._INLINE_SYSTEM_TAG}\n{part.get('text', '')}"
                return out
        out.insert(0, {"text": cls._INLINE_SYSTEM_TAG})
        return out

    def _format_messages_for_gemini_api(self, messages):
        system_parts = []
        contents = []
        # system до первого сообщения диалога — статическая инструкция, ей место
        # в system_instruction. Всё, что идёт дальше, позиционно: такой блок
        # относится к соседним репликам, и в system_instruction он оторвался бы
        # от своего места и уехал в начало запроса. Поэтому едет в contents.
        dialogue_started = False

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                parts = self._format_content_to_parts(content)
                if not self._parts_have_payload(parts):
                    continue
                if dialogue_started:
                    contents.append({"role": "user", "parts": self._prefix_parts_with_tag(parts)})
                else:
                    system_parts.extend(parts)
                continue

            dialogue_started = True
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": self._format_content_to_parts(content)})

        result = {"contents": contents}
        if system_parts:
            result["system_instruction"] = {"parts": system_parts}
        return result

    def _format_content_to_parts(self, content):
        parts = []
        if isinstance(content, str):
            parts.append({"text": content})
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = MessageContentCodec.part_type(item)
                if item_type == "text":
                    parts.append({"text": item.get("text", "")})
                elif item_type == "image_url":
                    image_url = item.get("image_url", {}).get("url", "")
                    if "," in image_url:
                        base64_data = image_url.split(",", 1)[1]
                        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64_data}})
                else:
                    # Незнакомую часть Gemini не примет, но и терять её молча нельзя:
                    # отдаём плейсхолдером (кодек залогирует тип один раз).
                    placeholder = MessageContentCodec.placeholder(item)
                    if placeholder:
                        parts.append({"text": placeholder})
        elif isinstance(content, dict):
            if "functionCall" in content or "functionResponse" in content:
                parts.append(content)
        return parts

    def _map_unified_params_to_generation_config(
        self,
        unified: dict,
        model: str,
        model_profile: dict | None = None,
    ) -> dict:
        u = unified or {}
        cfg = {}
        profile = model_profile if isinstance(model_profile, dict) else None
        allowed_params = None
        excluded_params: set[str] = set()
        if profile is not None:
            allowed_params = {
                str(name).strip()
                for name in (profile.get("parameters") or [])
                if str(name).strip()
            }
            excluded_params = {
                str(name).strip()
                for name in (profile.get("excluded_parameters") or [])
                if str(name).strip()
            }

        def allows(name: str) -> bool:
            return (allowed_params is None or name in allowed_params) and name not in excluded_params

        if "temperature" in u and allows("temperature"):
            cfg["temperature"] = u["temperature"]
        if "max_tokens" in u and allows("max_tokens"):
            cfg["maxOutputTokens"] = u["max_tokens"]
        if "presence_penalty" in u and allows("presence_penalty"):
            cfg["presencePenalty"] = u["presence_penalty"]
        if "frequency_penalty" in u and allows("frequency_penalty"):
            cfg["frequencyPenalty"] = u["frequency_penalty"]
        if "top_p" in u and allows("top_p"):
            cfg["topP"] = u["top_p"]
        if "top_k" in u and allows("top_k"):
            cfg["topK"] = u["top_k"]

        thinking_profile = profile.get("thinking") if profile is not None else None
        if not isinstance(thinking_profile, dict):
            thinking_profile = None
        transport = str((thinking_profile or {}).get("transport") or "budget").strip().lower()

        if transport == "level":
            if "enable_thinking" in u:
                allowed_levels = {
                    str(level).strip().lower()
                    for level in (thinking_profile.get("allowed_levels") or [])
                    if str(level).strip()
                }
                if bool(u.get("enable_thinking")):
                    level = str(
                        u.get("reasoning_effort")
                        or thinking_profile.get("default_level")
                        or ""
                    ).strip().lower()
                else:
                    level = str(thinking_profile.get("disabled_level") or "").strip().lower()

                if level and (not allowed_levels or level in allowed_levels):
                    thinking_cfg = {"thinkingLevel": level}
                    if bool(u.get("enable_thinking")) and bool(thinking_profile.get("include_thoughts", True)):
                        thinking_cfg["includeThoughts"] = True
                    cfg["thinkingConfig"] = thinking_cfg
                    logger.debug("[GeminiProvider] profile thinkingLevel=%s", level)
            return filter_jsonable_params(cfg)

        if transport == "budget" and "enable_thinking" in u:
            enabled = bool(u.get("enable_thinking"))
            if enabled:
                budget = u.get("gemini_thinking_budget")
                thinking_cfg: dict = {
                    "includeThoughts": bool((thinking_profile or {}).get("include_thoughts", True))
                }
                if budget is not None:
                    budget = int(budget)
                    if budget != -1:
                        min_budget = (thinking_profile or {}).get("min_budget")
                        max_budget = (thinking_profile or {}).get("max_budget")
                        if min_budget is not None:
                            budget = max(int(min_budget), budget)
                        if max_budget is not None:
                            budget = min(int(max_budget), budget)
                    thinking_cfg["thinkingBudget"] = budget
                cfg["thinkingConfig"] = thinking_cfg
                logger.debug(
                    "[GeminiProvider] profile thinking budget enabled: %s",
                    thinking_cfg.get("thinkingBudget", "dynamic/default"),
                )
            else:
                disabled_budget = (thinking_profile or {}).get("disabled_budget")
                if disabled_budget is not None:
                    cfg["thinkingConfig"] = {"thinkingBudget": int(disabled_budget)}
                    logger.debug(
                        "[GeminiProvider] profile thinking reduced/disabled: %s",
                        disabled_budget,
                    )

        return filter_jsonable_params(cfg)

    def generate_request_gemini(self, req: LLMRequest) -> LLMResponse:
        if req.depth > 3:
            logger.error("Превышена глубина рекурсии для Gemini tool calls")
            return LLMResponse(text=None, provider_name=self.name)

        formatted = self._format_messages_for_gemini_api(req.messages)

        data = {}

        contents = formatted.get("contents") or []
        system_parts = []
        if "system_instruction" in formatted:
            system_parts = (formatted.get("system_instruction") or {}).get("parts") or []

        if system_parts and not self._supports_system_instruction(req.model):
            contents = self._inject_system_into_contents(system_parts, contents)
        else:
            if system_parts:
                data["system_instruction"] = {"parts": system_parts}

        data["contents"] = contents or []
        if not data["contents"]:
            data["contents"] = [{
                "role": "user",
                "parts": [{"text": "Generate an appropriate reaction."}],
            }]

        if data["contents"] and data["contents"][-1].get("role") != "user":
            last_msg = data["contents"][-1]
            last_msg["role"] = "user"
            for part in last_msg.get("parts", []):
                if "text" in part:
                    part["text"] = f"[SYSTEM INFO] {part['text']}"

        gen_cfg = self._map_unified_params_to_generation_config(
            req.extra,
            req.model,
            (req.capabilities or {}).get("model_profile"),
        )

        caps = req.capabilities or {}
        if self._should_send_native_structured_output(caps):
            gen_cfg["responseMimeType"] = "application/json"
            mode = caps.get("structured_output_mode", "gemini_schema")
            if mode != "gemini_prompt":
                model_cls = req.structured_model or StructuredResponse
                has_custom = bool(caps.get("has_custom_params")) or bool(caps.get("custom_params"))
                excl = set() if has_custom else {"custom_fields"}
                if not caps.get("schema_reasoning", True):
                    excl.add("reasoning")
                excl.update(str(name) for name in caps.get("structured_exclude_fields") or () if str(name).strip())
                segment_excl = set(caps.get("structured_segment_exclude_fields") or ())
                if not caps.get("schema_intents", False):
                    segment_excl.add("intents")
                schema = model_cls.gemini_schema_dict(
                    exclude_fields=excl or None,
                    exclude_segment_fields=segment_excl or None,
                    require_fields=set(caps.get("structured_required_fields") or ()) or None,
                )
                gen_cfg["responseJsonSchema"] = schema
                logger.debug("[GeminiProvider] Structured output: responseJsonSchema passed (gemini_schema mode)")
            else:
                logger.debug("[GeminiProvider] Structured output: prompt-guided only (gemini_prompt mode)")
        elif caps.get("structured_output", False):
            logger.debug("[GeminiProvider] Structured output: native schema disabled by model profile")

        if gen_cfg:
            data["generationConfig"] = gen_cfg

        need_stream = bool(req.stream and caps.get("streaming", True))

        headers = {"Content-Type": "application/json"}
        if isinstance(req.headers, dict):
            for k, v in req.headers.items():
                if k and v is not None:
                    headers[str(k)] = str(v)

        gen_cfg_log = data.get("generationConfig", {})
        logger.info(f"[GeminiProvider] need_stream={need_stream}, generationConfig keys: {list(gen_cfg_log.keys())}")

        import time as _time

        _t0 = _time.time()
        request_url = self._request_url(req, stream=need_stream)
        try:
            response = self.http_transport.post_json(
                req,
                request_url,
                headers=headers,
                payload=data,
                stream=need_stream,
            )
        except Exception as e:
            provider_error = coerce_provider_error(self.name, e, url=request_url)
            logger.debug(
                "[GeminiProvider] Transport failure delegated to request runner: %s",
                provider_error.to_console_summary(),
            )
            raise provider_error from e
        logger.info(f"[GeminiProvider] Response received in {_time.time()-_t0:.1f}s, status={response.status_code}")

        if response.status_code != 200:
            if need_stream:
                response.read()
            try:
                payload = response.json()
            except Exception:
                payload = response.text[:500]
            provider_error = build_provider_error(
                self.name,
                status_code=response.status_code,
                payload=payload,
                response_headers=response.headers,
                url=request_url,
            )
            logger.debug("[GeminiProvider] HTTP failure delegated to request runner: %s", provider_error.to_console_summary())
            logger.debug(f"[GeminiProvider] raw error payload: {payload}")
            response.close()
            raise provider_error

        if need_stream:
            return self._handle_gemini_stream(response, req)

        try:
            response_data = response.json()
            parts = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])

            think_texts = []
            text_parts_list = []

            for part in parts:
                if not isinstance(part, dict):
                    continue
                if part.get("thought"):
                    t = part.get("text", "")
                    if t:
                        think_texts.append(t)
                else:
                    t = part.get("text", "")
                    if t:
                        text_parts_list.append(t)

            response_text = "".join(text_parts_list) or "..."

            result = LLMResponse(
                text=response_text,
                usage=self._extract_usage(response_data),
                model=(response_data.get("modelVersion") if isinstance(response_data, dict) else None) or req.model,
                provider_name=self.name,
                raw=response_data if isinstance(response_data, dict) else {},
                reasoning="\n".join(think_texts) or None,
            )
            response.close()
            return result
        except Exception as e:
            provider_error = build_provider_error(
                self.name,
                provider_message=f"Gemini response parse error: {format_exception(e)}",
                payload=getattr(response, "text", None),
                url=req.api_url,
            )
            logger.debug(
                "[GeminiProvider] Parse failure delegated to request runner: %s",
                provider_error.to_console_summary(),
            )
            try:
                response.close()
            except Exception:
                pass
            raise provider_error from e

    def _handle_gemini_stream(
        self,
        response,
        req: LLMRequest,
    ) -> LLMResponse:
        accumulator = StreamAccumulator(req, provider=self.name, model=req.model)
        response_model = None
        finish_reason = None

        try:
            content_type = str(response.headers.get("content-type") or "").lower()
            if "text/event-stream" in content_type:
                def iter_sse_values():
                    for data in iter_sse_data(track_response_body(req, response.iter_lines())):
                        if data.strip() == "[DONE]":
                            continue
                        try:
                            yield json.loads(data)
                        except json.JSONDecodeError as e:
                            raise build_stream_error(
                                self.name,
                                payload=data[:500],
                                provider_message=f"Invalid JSON in Gemini stream: {format_exception(e)}",
                                code="stream.invalid_json",
                                url=str(getattr(response, "url", req.api_url) or req.api_url),
                            ) from e

                values = iter_sse_values()
            else:
                values = iter_json_values(track_response_body(req, response.iter_text()))

            for result in values:
                check_request_cancelled(req)
                if not isinstance(result, dict):
                    raise build_stream_error(
                        self.name,
                        payload=result,
                        provider_message="Gemini stream chunk is not a JSON object.",
                        code="stream.invalid_payload",
                        url=str(getattr(response, "url", req.api_url) or req.api_url),
                    )
                if result.get("error"):
                    raise build_stream_error(
                        self.name,
                        payload=result,
                        url=str(getattr(response, "url", req.api_url) or req.api_url),
                    )
                response_model = response_model or result.get("modelVersion")
                usage = self._extract_usage(result)
                if usage is not None:
                    accumulator.set_usage(usage)
                candidate = (result.get("candidates") or [{}])[0] or {}
                finish_reason = candidate.get("finishReason") or finish_reason
                parts = (candidate.get("content") or {}).get("parts") or []
                for part in parts if isinstance(parts, list) else []:
                    if not isinstance(part, dict):
                        continue
                    if part.get("thought"):
                        accumulator.add_reasoning(part.get("text"))
                    else:
                        accumulator.add_text(part.get("text"))

            return accumulator.complete(finish_reason=finish_reason, model=response_model)
        except Exception as e:
            # Обрыв/ошибка посреди стрима — не маскируем под успех, кидаем ошибку,
            # чтобы runner ушёл в retry/фоллбэк, а не вернул обрезанный ответ.
            if isinstance(e, json.JSONDecodeError):
                provider_error = build_stream_error(
                    self.name,
                    provider_message=f"Invalid JSON in Gemini stream: {format_exception(e)}",
                    code="stream.invalid_json",
                    url=str(getattr(response, "url", req.api_url) or req.api_url),
                )
            else:
                provider_error = coerce_provider_error(self.name, e, url=getattr(response, "url", None))
            logger.debug(
                "[GeminiProvider] Stream failure delegated to request runner: %s",
                provider_error.to_console_summary(),
            )
            raise provider_error from e
        finally:
            try:
                response.close()
            except Exception:
                logger.debug("[GeminiProvider] Failed to close HTTP stream", exc_info=True)

    def _extract_usage(self, response_data):
        if not isinstance(response_data, dict):
            return None

        usage_meta = response_data.get("usageMetadata") or response_data.get("usage_metadata")
        if not isinstance(usage_meta, dict):
            return None

        # promptTokenCount уже включает кэшированную часть, как и у OpenAI-совместимых:
        # cachedContentTokenCount — подмножество, а не добавка.
        payload = {
            "prompt_tokens": usage_meta.get("promptTokenCount") or usage_meta.get("prompt_token_count"),
            "completion_tokens": usage_meta.get("candidatesTokenCount") or usage_meta.get("candidates_token_count"),
            "total_tokens": usage_meta.get("totalTokenCount") or usage_meta.get("total_token_count"),
            "prompt_tokens_details": {
                "cached_tokens": (
                    usage_meta.get("cachedContentTokenCount")
                    or usage_meta.get("cached_content_token_count")
                ),
            },
            "completion_tokens_details": {
                "reasoning_tokens": (
                    usage_meta.get("thoughtsTokenCount")
                    or usage_meta.get("thoughts_token_count")
                ),
            },
        }
        return normalize_usage_payload(payload)
