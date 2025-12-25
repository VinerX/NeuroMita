# src/handlers/llm_providers/common_provider.py
from __future__ import annotations

from .base import BaseProvider, LLMRequest
import requests
import json
from main_logger import logger
from utils import save_combined_messages


class CommonProvider(BaseProvider):
    name = "common"
    priority = 30
    supports_tools_native = True

    def is_applicable(self, req: LLMRequest) -> bool:
        if req.g4f_flag:
            return False
        if not req.make_request:
            return False
        return True

    def generate(self, req: LLMRequest) -> str:
        return self.generate_request_common(req)

    def _map_unified_params(self, unified: dict, model_to_use: str) -> dict:
        u = unified or {}
        m = (model_to_use or "").lower()
        out = {}

        for k in ("temperature", "max_tokens", "presence_penalty", "frequency_penalty", "top_p"):
            if k in u:
                out[k] = u[k]

        if "top_k" in u and "deepseek" in m:
            out["top_k"] = u["top_k"]

        if "logprobs" in u:
            lp = u["logprobs"]
            out["logprobs"] = lp if isinstance(lp, bool) else bool(lp)

        return out

    def generate_request_common(self, req: LLMRequest) -> str:
        if req.depth > 3:
            return None

        data = {
            "model": req.model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in req.messages]
        }

        data.update(self._map_unified_params(req.extra, req.model))

        if req.tools_on and req.tools_mode == "native" and req.tools_payload:
            data["tools"] = req.tools_payload

        save_combined_messages(data["messages"], "SavedMessages/last_request_common_log")

        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {req.api_key}"}
        response = requests.post(req.api_url, headers=headers, json=data, stream=req.stream)

        if response.status_code != 200:
            try:
                err = response.json()
            except Exception:
                err = response.text
            logger.error(f"Ошибка генерации при Common запросе: {err}")
            return None

        if req.stream:
            return self._handle_common_stream(response, req.stream_cb)

        try:
            resp_json = response.json()
            message = resp_json.get("choices", [{}])[0].get("message", {}) or {}
            tool_calls = message.get("tool_calls") or []

            if tool_calls and req.tool_manager:
                from tools.manager import mk_tool_call_msg, mk_tool_resp_msg
                for call in tool_calls:
                    name = call["function"]["name"]
                    args = json.loads(call["function"]["arguments"])
                    tool_result = req.tool_manager.run(name, args)
                    req.messages.append(mk_tool_call_msg(name, args))
                    req.messages.append(mk_tool_resp_msg(name, tool_result))
                req.depth += 1
                return self.generate_request_common(req)

            return (message.get("content") or "").strip()
        except Exception as ex:
            logger.error(f"Произошла ошибка: {ex}", exc_info=True)
            return ""

    def _handle_common_stream(self, response, stream_callback: callable = None) -> str:
        full_response_parts = []
        try:
            for line in response.iter_lines(decode_unicode=True):
                if line and line.startswith('data: '):
                    line_data = line[6:]
                    if line_data.strip() == '[DONE]':
                        break
                    try:
                        response_json = json.loads(line_data)
                        delta = response_json.get("choices", [{}])[0].get("delta", {})
                        decoded_chunk = delta.get("content", "")
                        if decoded_chunk:
                            if stream_callback:
                                stream_callback(decoded_chunk)
                            full_response_parts.append(decoded_chunk)
                    except json.JSONDecodeError:
                        logger.warning(f"Could not decode JSON from SSE streaming line: {line_data}")
                    except (IndexError, KeyError) as e:
                        logger.warning(f"Could not parse SSE streaming chunk structure: {line_data}, error: {e}")

            return "".join(full_response_parts)
        except Exception as e:
            logger.error(f"Error processing common (SSE) stream: {e}", exc_info=True)
            return "".join(full_response_parts)