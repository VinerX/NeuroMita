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
        return bool(req.make_request and req.gemini_case)

    def generate(self, req: LLMRequest) -> str:
        return self.generate_request_gemini(req)

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

        result = {}
        if system_parts:
            result["system_instruction"] = {"parts": system_parts}
        result["contents"] = contents
        return result

    def _format_content_to_parts(self, content):
        parts = []
        if isinstance(content, str):
            parts.append({"text": content})
        elif isinstance(content, list):
            for item in content:
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

        return filter_jsonable_params(cfg)

    def generate_request_gemini(self, req: LLMRequest) -> str:
        if req.depth > 3:
            logger.error("Превышена глубина рекурсии для Gemini tool calls")
            return None

        formatted = self._format_messages_for_gemini_api(req.messages)

        data = {}
        if "system_instruction" in formatted:
            data["system_instruction"] = formatted["system_instruction"]

        data["contents"] = formatted["contents"] or []
        if not data["contents"]:
            data["contents"] = [{
                "role": "user",
                "parts": [{"text": "[SYSTEM INFO] Follow the system_instruction and generate an appropriate reaction."}]
            }]

        if data["contents"] and data["contents"][-1].get("role") != "user":
            last_msg = data["contents"][-1]
            last_msg["role"] = "user"
            for part in last_msg.get("parts", []):
                if "text" in part:
                    part["text"] = f"[SYSTEM INFO] {part['text']}"

        gen_cfg = self._map_unified_params_to_generation_config(req.extra, req.model)
        if gen_cfg:
            data["generationConfig"] = gen_cfg

        if req.tools_on and req.tools_mode == "native" and req.tool_manager:
            dialect = req.tools_dialect or "gemini"
            tools_payload = req.tools_payload or req.tool_manager.get_tools_payload(dialect)
            if tools_payload:
                data["tools"] = tools_payload

        need_stream = req.stream and "tools" not in data

        response = requests.post(
            req.api_url,
            headers={"Content-Type": "application/json"},
            json=data,
            stream=need_stream
        )

        if response.status_code != 200:
            logger.error(f"Gemini API error: {response.status_code} - {response.text}")
            return None

        if need_stream:
            return self._handle_gemini_stream(response, req.stream_cb)

        try:
            response_data = response.json()
            first_part = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0]

            func_call = first_part.get("functionCall")
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

            return first_part.get("text", "") or "…"
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
                        generated_text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if generated_text:
                            if stream_callback:
                                stream_callback(generated_text)
                            full_response_parts.append(generated_text)
                        json_buffer = json_buffer[index:].lstrip()
                    except json.JSONDecodeError:
                        break
            return "".join(full_response_parts)
        except Exception as e:
            logger.error(f"Ошибка обработки Gemini stream: {e}", exc_info=True)
            return "".join(full_response_parts)