from __future__ import annotations

import json

import requests

from main_logger import logger
from handlers.llm_providers.errors import build_provider_error, coerce_provider_error
from handlers.llm_providers.param_mapper import filter_jsonable_params
from schemas.structured_response import StructuredResponse

from .base import (
    BaseProvider,
    LLMRequest,
    LLMResponse,
    check_request_cancelled,
    normalize_usage_payload,
    register_cancellable_resource,
    resolve_requests_timeout,
)


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

    def _format_messages_for_gemini_api(self, messages):
        system_parts = []
        contents = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                system_parts.extend(self._format_content_to_parts(content))
            else:
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
                if item.get("type") == "text":
                    parts.append({"text": item.get("text", "")})
                elif item.get("type") == "image_url":
                    image_url = item.get("image_url", {}).get("url", "")
                    if "," in image_url:
                        base64_data = image_url.split(",", 1)[1]
                        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64_data}})
        elif isinstance(content, dict):
            if "functionCall" in content or "functionResponse" in content:
                parts.append(content)
        return parts

    def _map_unified_params_to_generation_config(self, unified: dict, model: str) -> dict:
        u = unified or {}
        cfg = {}

        if "temperature" in u:
            cfg["temperature"] = u["temperature"]
        if "max_tokens" in u:
            cfg["maxOutputTokens"] = u["max_tokens"]
        if "presence_penalty" in u:
            cfg["presencePenalty"] = u["presence_penalty"]
        if "frequency_penalty" in u:
            cfg["frequencyPenalty"] = u["frequency_penalty"]
        if "top_p" in u:
            cfg["topP"] = u["top_p"]
        if "top_k" in u:
            cfg["topK"] = u["top_k"]

        if model in ("gemini-2.5-pro-exp-03-25", "gemini-2.5-flash-preview-04-17"):
            cfg.pop("presencePenalty", None)

        if u.get("enable_thinking"):
            budget = u.get("gemini_thinking_budget")
            thinking_cfg: dict = {"includeThoughts": True}
            if budget is not None:
                thinking_cfg["thinkingBudget"] = int(budget)
            cfg["thinkingConfig"] = thinking_cfg
            logger.debug(f"[GeminiProvider] thinkingConfig enabled: {thinking_cfg}")
        elif "enable_thinking" in u:
            cfg["thinkingConfig"] = {"thinkingBudget": 0}
            logger.debug("[GeminiProvider] thinkingConfig explicitly disabled (thinkingBudget=0)")

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

        gen_cfg = self._map_unified_params_to_generation_config(req.extra, req.model)

        caps = req.capabilities or {}
        if caps.get("structured_output", False):
            gen_cfg["responseMimeType"] = "application/json"
            mode = caps.get("structured_output_mode", "gemini_schema")
            if mode != "gemini_prompt":
                model_cls = req.structured_model or StructuredResponse
                has_custom = bool(caps.get("has_custom_params")) or bool(caps.get("custom_params"))
                excl = set() if has_custom else {"custom_fields"}
                if not caps.get("schema_reasoning", True):
                    excl.add("reasoning")
                segment_excl = set(caps.get("structured_segment_exclude_fields") or ())
                schema = model_cls.gemini_schema_dict(
                    exclude_fields=excl or None,
                    exclude_segment_fields=segment_excl or None,
                )
                gen_cfg["responseJsonSchema"] = schema
                logger.debug("[GeminiProvider] Structured output: responseJsonSchema passed (gemini_schema mode)")
            else:
                logger.debug("[GeminiProvider] Structured output: prompt-guided only (gemini_prompt mode)")

        if gen_cfg:
            data["generationConfig"] = gen_cfg

        need_stream = req.stream

        headers = {"Content-Type": "application/json"}
        if isinstance(req.headers, dict):
            for k, v in req.headers.items():
                if k and v is not None:
                    headers[str(k)] = str(v)

        gen_cfg_log = data.get("generationConfig", {})
        logger.info(f"[GeminiProvider] need_stream={need_stream}, generationConfig keys: {list(gen_cfg_log.keys())}")

        import time as _time

        _t0 = _time.time()
        try:
            check_request_cancelled(req)
            response = requests.post(
                req.api_url,
                headers=headers,
                json=data,
                stream=need_stream,
                timeout=resolve_requests_timeout(req),
            )
            register_cancellable_resource(req, response)
            check_request_cancelled(req)
        except Exception as e:
            provider_error = coerce_provider_error(self.name, e, url=req.api_url)
            logger.error(f"[GeminiProvider] {provider_error.to_console_summary()}", exc_info=True)
            raise provider_error from e
        logger.info(f"[GeminiProvider] Response received in {_time.time()-_t0:.1f}s, status={response.status_code}")

        if response.status_code != 200:
            try:
                payload = response.json()
            except Exception:
                payload = response.text[:500]
            provider_error = build_provider_error(
                self.name,
                status_code=response.status_code,
                payload=payload,
                url=req.api_url,
            )
            logger.error(f"[GeminiProvider] {provider_error.to_console_summary()}")
            logger.debug(f"[GeminiProvider] raw error payload: {payload}")
            response.close()
            raise provider_error

        if need_stream:
            return self._handle_gemini_stream(response, req, req.stream_cb)

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
            if think_texts:
                think_block = "<think>" + "\n".join(think_texts) + "</think>"
                response_text = think_block + "\n" + response_text

            result = LLMResponse(
                text=response_text,
                usage=self._extract_usage(response_data),
                model=(response_data.get("modelVersion") if isinstance(response_data, dict) else None) or req.model,
                provider_name=self.name,
                raw=response_data if isinstance(response_data, dict) else {},
            )
            response.close()
            return result
        except Exception as e:
            logger.error(f"Ошибка парсинга Gemini response: {e}", exc_info=True)
            provider_error = build_provider_error(
                self.name,
                provider_message=f"Gemini response parse error: {e}",
                payload=getattr(response, "text", None),
                url=req.api_url,
            )
            logger.error(f"[GeminiProvider] {provider_error.to_console_summary()}", exc_info=True)
            try:
                response.close()
            except Exception:
                pass
            raise provider_error from e

    def _handle_gemini_stream(
        self,
        response,
        req: LLMRequest,
        stream_callback: callable = None,
    ) -> LLMResponse:
        full_response_parts = []
        json_buffer = ""
        decoder = json.JSONDecoder()
        usage = None
        response_model = None

        try:
            for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                check_request_cancelled(req)
                json_buffer += chunk
                while json_buffer.strip():
                    try:
                        result, index = decoder.raw_decode(json_buffer)
                        if response_model is None and isinstance(result, dict):
                            response_model = result.get("modelVersion")
                        usage = usage or self._extract_usage(result)

                        parts = (
                            result.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [])
                        )
                        for part in (parts if isinstance(parts, list) else []):
                            if not isinstance(part, dict):
                                continue
                            text = part.get("text", "")
                            if not text:
                                continue
                            is_thought = bool(part.get("thought"))
                            if stream_callback:
                                if is_thought:
                                    stream_callback(f"<think>{text}</think>")
                                else:
                                    stream_callback(text)
                            if not is_thought:
                                full_response_parts.append(text)

                        json_buffer = json_buffer[index:].lstrip()
                    except json.JSONDecodeError:
                        break

            # Стрим успешно дочитан до конца — отдаём накопленный текст.
            return LLMResponse(
                text="".join(full_response_parts),
                usage=usage,
                model=response_model,
                provider_name=self.name,
            )
        except Exception as e:
            # Обрыв/ошибка посреди стрима — не маскируем под успех, кидаем ошибку,
            # чтобы runner ушёл в retry/фоллбэк, а не вернул обрезанный ответ.
            provider_error = coerce_provider_error(self.name, e, url=getattr(response, "url", None))
            logger.error(f"[GeminiProvider] stream error: {provider_error.to_console_summary()}", exc_info=True)
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

        payload = {
            "prompt_tokens": usage_meta.get("promptTokenCount") or usage_meta.get("prompt_token_count"),
            "completion_tokens": usage_meta.get("candidatesTokenCount") or usage_meta.get("candidates_token_count"),
            "total_tokens": usage_meta.get("totalTokenCount") or usage_meta.get("total_token_count"),
        }
        return normalize_usage_payload(payload)
