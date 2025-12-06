from __future__ import annotations
from typing import Dict, Any, List, Optional
import os
import base64
import datetime

from core.events import get_event_bus, Events, Event
from main_logger import logger
from utils.prompt_builder import build_system_prompts


class PromptController:
    def __init__(self):
        self.event_bus = get_event_bus()
        self._subscribe_to_events()

    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Prompt.BUILD_PROMPT, self._on_build_prompt, weak=False)

    def _get_character(self, char_id: str):
        try:
            res = self.event_bus.emit_and_wait(
                Events.Model.GET_CHARACTER,
                {'name': char_id},
                timeout=1.0
            )
            return res[0] if res else None
        except Exception as e:
            logger.error(f"[PromptController] Не удалось получить персонажа '{char_id}': {e}", exc_info=True)
            return None

    def _load_app_vars(self) -> Dict[str, Any]:
        app_vars: Dict[str, Any] = {}
        try:
            results = self.event_bus.emit_and_wait(Events.Settings.GET_APP_VARS, timeout=1.0)
            for r in results or []:
                if isinstance(r, dict):
                    app_vars.update(r)
        except Exception as e:
            logger.warning(f"[PromptController] Не удалось получить app_vars: {e}")
        return app_vars

    def _setup_character_for_prompt(self, character, event_type: str):
        now_str = datetime.datetime.now().strftime("%Y %B %d (%A) %H:%M")
        character.set_variable("SYSTEM_DATETIME", now_str)
        app_vars = self._load_app_vars()
        character.update_app_vars(app_vars)

        if getattr(character, "char_id", "") == "GameMaster":
            try:
                res = self.event_bus.emit_and_wait(
                    Events.Settings.GET_SETTING,
                    {'key': 'GM_SMALL_PROMPT', 'default': ''},
                    timeout=1.0
                )
                gm_instr = res[0] if res else ""
                character.set_variable("GM_INSTRUCTION", gm_instr or "")
            except Exception as e:
                logger.warning(
                    f"[PromptController] Не удалось получить GM_SMALL_PROMPT для GameMaster: {e}"
                )
                character.set_variable("GM_INSTRUCTION", "")

    def _build_system_messages(
        self,
        character,
        event_type: str,
        separate_prompts: bool
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        self._setup_character_for_prompt(character, event_type)

        if event_type == 'react':
            template_name = "react_template.txt"
            candidate = os.path.join(character.base_data_path, template_name)
            if not os.path.exists(candidate):
                template_name = character.main_template_path_relative
        else:
            template_name = character.main_template_path_relative

        try:
            blocks, dsl_system_infos = character.dsl_interpreter.process_main_template(template_name)
        except Exception as e:
            logger.error(
                f"[PromptController] Ошибка DSL при обработке шаблона '{template_name}' "
                f"для персонажа {getattr(character, 'char_id', '')}: {e}",
                exc_info=True
            )
            return [], []

        system_messages: List[Dict[str, Any]] = []
        system_messages.extend(build_system_prompts(blocks, separate=separate_prompts))

        memory_message_content = ""
        try:
            if hasattr(character, "memory_system") and character.memory_system:
                memory_message_content = character.memory_system.get_memories_formatted()
        except Exception as e:
            logger.warning(
                f"[PromptController] Ошибка получения памяти для персонажа "
                f"{getattr(character, 'char_id', '')}: {e}"
            )
            memory_message_content = ""

        if memory_message_content and memory_message_content.strip():
            system_messages.append({"role": "system", "content": memory_message_content})

        return system_messages, dsl_system_infos

    def _on_build_prompt(self, event: Event) -> Dict[str, Any]:
        data = event.data or {}
        char_id: str = data.get('character_id')
        if not char_id:
            logger.error("[PromptController] BUILD_PROMPT без character_id")
            return {'messages': [], 'history_messages': []}

        character = self._get_character(char_id)
        if not character:
            logger.error(f"[PromptController] Персонаж '{char_id}' не найден")
            return {'messages': [], 'history_messages': []}

        event_type: str = data.get('event_type', 'chat')
        user_input: str = data.get('user_input', '') or ''
        system_input: str = data.get('system_input', '') or ''
        image_data = data.get('image_data') or []

        memory_limit: int = int(data.get('memory_limit', 40))
        is_game_master: bool = bool(data.get('is_game_master', False))
        save_missed_history: bool = bool(data.get('save_missed_history', True))
        image_cfg: Dict[str, Any] = data.get('image_quality', {}) or {}
        separate_prompts: bool = bool(data.get('separate_prompts', True))
        extra_system_infos: List[Any] = data.get('extra_system_infos') or []
        game_state: Dict[str, Any] = data.get('game_state') or {}

        try:
            character.set_variable("GAME_DISTANCE", float(game_state.get('distance', 0.0)))
            character.set_variable("GAME_ROOM_PLAYER", game_state.get('roomPlayer', -1))
            character.set_variable("GAME_ROOM_MITA", game_state.get('roomMita', -1))
            character.set_variable("GAME_NEAR_OBJECTS", game_state.get('nearObjects', ''))
            character.set_variable("GAME_ACTUAL_INFO", game_state.get('actualInfo', ''))
        except Exception as e:
            logger.warning(f"[PromptController] Не удалось обновить игровые переменные для {char_id}: {e}")

        game_state_prompt_content: Optional[str] = None
        try:
            if character.get_variable("playingGame", False) and hasattr(character, 'game_manager'):
                game_state_prompt_content = character.game_manager.get_active_game_state_prompt()
                if game_state_prompt_content:
                    logger.info(f"[PromptController][{char_id}] Сформирован промпт состояния игры.")
        except Exception as e:
            logger.warning(f"[PromptController][{char_id}] Ошибка при формировании промпта игры: {e}", exc_info=True)

        messages: List[Dict[str, Any]] = []

        system_messages, dsl_system_infos = self._build_system_messages(
            character,
            event_type,
            separate_prompts
        )
        messages.extend(system_messages)

        if game_state_prompt_content:
            messages.append({"role": "system", "content": game_state_prompt_content})

        hist_res = self.event_bus.emit_and_wait(
            Events.History.PREPARE_FOR_PROMPT,
            {
                'character_id': char_id,
                'event_type': event_type,
                'memory_limit': memory_limit,
                'is_game_master': is_game_master,
                'save_missed_history': save_missed_history,
                'image_quality': image_cfg,
            },
            timeout=5.0
        )
        history_limited: List[Dict[str, Any]] = []
        if hist_res and isinstance(hist_res[0], dict):
            history_limited = hist_res[0].get('history', []) or []

        for info in extra_system_infos:
            if isinstance(info, dict):
                history_limited.append(info)
            elif isinstance(info, str):
                history_limited.append({"role": "system", "content": info})

        for s in dsl_system_infos:
            if isinstance(s, str):
                history_limited.append({"role": "system", "content": s})
            elif isinstance(s, dict):
                history_limited.append(s)

        messages.extend(history_limited)

        current_time = datetime.datetime.now()
        current_state_message = {
            "role": "system",
            "content": (
                f"[Current State]\n"
                f"Date: {current_time.strftime('%Y-%m-%d')}\n"
                f"Time: {current_time.strftime('%H:%M:%S')}\n"
                f"Day of week: {current_time.strftime('%A')}"
            )
        }
        messages.append(current_state_message)

        if system_input:
            messages.append({"role": "system", "content": system_input})

        user_message_for_history: Optional[Dict[str, Any]] = None
        user_content_chunks: List[Dict[str, Any]] = []

        if user_input:
            user_content_chunks.append({"type": "text", "text": user_input})

        for img in image_data:
            if isinstance(img, bytes):
                img_b64 = base64.b64encode(img).decode('utf-8')
            else:
                img_b64 = str(img)
            user_content_chunks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })

        if user_content_chunks:
            user_message_for_history = {"role": "user", "content": user_content_chunks}
            messages.append(user_message_for_history)

        if user_message_for_history:
            user_message_for_history["time"] = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
            history_limited.append(user_message_for_history)

        return {
            "messages": messages,
            "history_messages": history_limited
        }