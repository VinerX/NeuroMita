# src/handlers/llm_providers/gemini_provider.py
from __future__ import annotations

from .base import BaseProvider, LLMRequest
import requests
import json
import copy
from main_logger import logger
from handlers.llm_providers.param_mapper import filter_jsonable_params


class GeminiProvider(BaseProvider):
    name = "gemini"
    priority = 20
    supports_tools_native = True
    supports_streaming = True
    supports_streaming_with_tools = False
    tools_dialect_id: str = "gemini"

    def is_applicable(self, req: LLMRequest) -> bool:
        return bool(req.provider_name == self.name)

    def generate(self, req: LLMRequest) -> str:
        return self.generate_request_gemini(req)

    def _supports_system_instruction(self, model: str) -> bool:
        m = (model or "").lower()
        # Gemma-family часто не поддерживает developer instruction => нельзя system_instruction
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
        """
        Для моделей без system_instruction: переносим system в первое user-сообщение.
        """
        sys_text = self._system_parts_to_text(system_parts)
        if not sys_text:
            return contents

        prefix = f"[SYSTEM INFO]\n{sys_text}\n\n"

        if not contents:
            return [{
                "role": "user",
                "parts": [{"text": prefix}]
            }]

        # найти первое user сообщение
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

        # если user-сообщений нет — добавим отдельное в начало
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

        # Thinking support (Gemini 2.5+)
        if u.get("enable_thinking"):
            budget = u.get("gemini_thinking_budget")
            thinking_cfg: dict = {"includeThoughts": True}
            if budget is not None:
                thinking_cfg["thinkingBudget"] = int(budget)
            cfg["thinkingConfig"] = thinking_cfg
            logger.debug(f"[GeminiProvider] thinkingConfig enabled: {thinking_cfg}")

        return filter_jsonable_params(cfg)

    def generate_request_gemini(self, req: LLMRequest) -> str:
        if req.depth > 3:
            logger.error("Превышена глубина рекурсии для Gemini tool calls")
            return None

        formatted = self._format_messages_for_gemini_api(req.messages)

        data = {}

        contents = formatted.get("contents") or []
        system_parts = []
        if "system_instruction" in formatted:
            system_parts = (formatted.get("system_instruction") or {}).get("parts") or []

        # Gemma: system_instruction нельзя — переносим system в contents
        if system_parts and not self._supports_system_instruction(req.model):
            contents = self._inject_system_into_contents(system_parts, contents)
        else:
            if system_parts:
                data["system_instruction"] = {"parts": system_parts}

        data["contents"] = contents or []
        if not data["contents"]:
            data["contents"] = [{
                "role": "user",
                "parts": [{"text": "Generate an appropriate reaction."}]
            }]

        if data["contents"] and data["contents"][-1].get("role") != "user":
            last_msg = data["contents"][-1]
            last_msg["role"] = "user"
            for part in last_msg.get("parts", []):
                if "text" in part:
                    part["text"] = f"[SYSTEM INFO] {part['text']}"

        gen_cfg = self._map_unified_params_to_generation_config(req.extra, req.model)

        # Add structured output for Gemini when capability is enabled.
        # Default mode "gemini_schema": pass responseSchema for strict enforcement.
        # Escape hatch: set structured_output_mode="gemini_prompt" in preset to use
        # prompt-guided JSON only (old behavior, no schema constraint).
        caps = req.capabilities or {}
        if caps.get("structured_output", False):
            gen_cfg["responseMimeType"] = "application/json"
            mode = caps.get("structured_output_mode", "gemini_schema")
            if mode != "gemini_prompt":
                from schemas.structured_response import StructuredResponse as _SR
                schema = _SR.gemini_schema_dict()
                gen_cfg["responseJsonSchema"] = schema
                logger.debug("[GeminiProvider] Structured output: responseSchema passed (gemini_schema mode)")
            else:
                logger.debug("[GeminiProvider] Structured output: prompt-guided only (gemini_prompt mode)")

        if gen_cfg:
            data["generationConfig"] = gen_cfg

        if req.tools_on and req.tools_mode == "native" and req.tool_manager:
            dialect = req.tools_dialect or "gemini"
            tools_payload = req.tools_payload or req.tool_manager.get_tools_payload(dialect)
            if tools_payload:
                data["tools"] = tools_payload

        need_stream = req.stream and "tools" not in data

        headers = {"Content-Type": "application/json"}
        if isinstance(req.headers, dict):
            for k, v in req.headers.items():
                if k and v is not None:
                    headers[str(k)] = str(v)

        gen_cfg_log = data.get("generationConfig", {})
        logger.info(f"[GeminiProvider] need_stream={need_stream}, generationConfig keys: {list(gen_cfg_log.keys())}")

        import time as _time
        _t0 = _time.time()
        response = requests.post(
            req.api_url,
            headers=headers,
            json=data,
            stream=need_stream,
            timeout=120,
        )
        logger.info(f"[GeminiProvider] Response received in {_time.time()-_t0:.1f}s, status={response.status_code}")

        if response.status_code != 200:
            logger.error(f"Gemini API error: {response.status_code} - {response.text[:500]}")
            return None

        if need_stream:
            return self._handle_gemini_stream(response, req.stream_cb)

        try:
            response_data = response.json()
            parts = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])

            think_texts = []
            text_parts_list = []
            func_call = None

            for part in parts:
                if not isinstance(part, dict):
                    continue
                if part.get("functionCall"):
                    func_call = part.get("functionCall")
                elif part.get("thought"):
                    t = part.get("text", "")
                    if t:
                        think_texts.append(t)
                else:
                    t = part.get("text", "")
                    if t:
                        text_parts_list.append(t)

            if func_call:
                name = func_call.get("name")
                args = func_call.get("args", {})
                tm = req.tool_manager
                if tm:
                    tool_result = tm.run(name, args)
                    new_messages = copy.deepcopy(req.messages)
                    new_messages.append(tm.mk_tool_call_msg(self.tools_dialect_id, name, args))
                    new_messages.append(tm.mk_tool_resp_msg(self.tools_dialect_id, name, tool_result))
                    req.messages = new_messages
                    req.depth += 1
                    return self.generate_request_gemini(req)

            response_text = "".join(text_parts_list) or "…"
            if think_texts:
                think_block = "<think>" + "\n".join(think_texts) + "</think>"
                response_text = think_block + "\n" + response_text
            return response_text
        except Exception as e:
            logger.error(f"Ошибка парсинга Gemini response: {e}", exc_info=True)
            return None

    def _handle_gemini_stream(self, response, stream_callback: callable = None) -> str:
        full_response_parts = []
        json_buffer = ''
        decoder = json.JSONDecoder()
        try:
            for chunk in response.iter_content(chunk_size=None, decode_unicode=True):
                json_buffer += chunk
                while json_buffer.strip():
                    try:
                        result, index = decoder.raw_decode(json_buffer)
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
                                # Wrap thinking parts in <think> tags so the existing
                                # ThinkTagStreamFilter in chat_controller routes them correctly
                                if is_thought:
                                    stream_callback(f"<think>{text}</think>")
                                else:
                                    stream_callback(text)
                            if not is_thought:
                                full_response_parts.append(text)
                        json_buffer = json_buffer[index:].lstrip()
                    except json.JSONDecodeError:
                        break
            return "".join(full_response_parts)
        except Exception as e:
            logger.error(f"Ошибка обработки Gemini stream: {e}", exc_info=True)
            return "".join(full_response_parts)