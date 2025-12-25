# src/handlers/llm_providers/gemini_provider.py
from .base import BaseProvider, LLMRequest
import requests
import json
import copy
from main_logger import logger

from handlers.llm_providers.param_mapper import (
    build_unified_generation_params,
    map_unified_params_to_gemini_generation_config,
    filter_jsonable_params,
)

class GeminiProvider(BaseProvider):
    name = "gemini"
    priority = 20

    def is_applicable(self, req: LLMRequest) -> bool:
        if not req.make_request:
            return False
        if not req.gemini_case:
            return False
        return True

    def generate(self, req: LLMRequest) -> str:
        return self.generate_request_gemini(req)

    def _format_messages_for_gemini_api(self, messages):
        """
        Форматирует сообщения для Gemini API согласно официальной спецификации.
        Разделяет system сообщения в system_instruction, остальные в contents.
        """
        system_parts = []
        contents = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                parts = self._format_content_to_parts(content)
                system_parts.extend(parts)
            else:
                gemini_role = "model" if role == "assistant" else "user"
                parts = self._format_content_to_parts(content)

                contents.append({
                    "role": gemini_role,
                    "parts": parts
                })

        result = {}
        if system_parts:
            result["system_instruction"] = {"parts": system_parts}
        result["contents"] = contents
        return result

    def _format_content_to_parts(self, content):
        """
        Преобразует content в формат parts для Gemini API.
        Поддерживает текст, изображения и tool calls.
        """
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
                        parts.append({
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": base64_data
                            }
                        })
        elif isinstance(content, dict):
            if "functionCall" in content or "functionResponse" in content:
                parts.append(content)

        return parts

    def generate_request_gemini(self, req: LLMRequest) -> str:
        if req.depth > 3:
            logger.error("Превышена глубина рекурсии для Gemini tool calls")
            return None

        # req.extra теперь содержит unified (canonical) параметры.
        unified_params = filter_jsonable_params(req.extra or {})
        gen_cfg = map_unified_params_to_gemini_generation_config(unified_params, model=req.model)

        formatted = self._format_messages_for_gemini_api(req.messages)

        data = {}
        if "system_instruction" in formatted:
            data["system_instruction"] = formatted["system_instruction"]

        data["contents"] = formatted["contents"]

        if not data["contents"]:
            logger.info("Gemini: no non-system messages, inserting synthetic user prompt for contents.")
            data["contents"] = [{
                "role": "user",
                "parts": [{
                    "text": "[SYSTEM INFO] Follow the system_instruction and generate an appropriate reaction."
                }]
            }]

        if data["contents"] and data["contents"][-1].get("role") != "user":
            logger.info("Корректировка: последнее сообщение должно быть от user для Gemini")
            last_msg = data["contents"][-1]
            last_msg["role"] = "user"
            for part in last_msg.get("parts", []):
                if "text" in part:
                    part["text"] = f"[SYSTEM INFO] {part['text']}"

        if gen_cfg:
            data["generationConfig"] = gen_cfg

        if req.tools_on and req.tools_payload:
            data["tools"] = req.tools_payload

        try:
            json_data = json.dumps(data, ensure_ascii=False, indent=2)
            with open("wtf.json", "w", encoding="utf-8") as f:
                f.write(json_data)
            logger.debug("Gemini request payload сохранен в wtf.json")
        except Exception as e:
            logger.warning(f"Не удалось сохранить wtf.json: {e}")

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
                    logger.info(f"Gemini вызвал tool: {name} с args: {args}")
                    tool_result = tm.run(name, args)
                    from tools.manager import mk_tool_call_msg, mk_tool_resp_msg
                    new_messages = copy.deepcopy(req.messages)
                    new_messages.append(mk_tool_call_msg(name, args))
                    new_messages.append(mk_tool_resp_msg(name, tool_result))
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

            full_text = "".join(full_response_parts)
            logger.info("Gemini stream завершен. Накоплен полный текст.")
            return full_text
        except Exception as e:
            logger.error(f"Ошибка обработки Gemini stream: {e}", exc_info=True)
            return "".join(full_response_parts)