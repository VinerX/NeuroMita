# src/controllers/chat_controller.py
import os
import asyncio
import tempfile
from main_logger import logger
from core.events import get_event_bus, Events, Event
from managers.task_manager import TaskStatus
import base64

# Контроллер для работы с отправкой сообщений.
class ChatController:
    def __init__(self, settings):
        self.settings = settings
        self.event_bus = get_event_bus()
        self.llm_processing = False
        
        self.staged_images = []
        self._subscribe_to_events()
        
    def _subscribe_to_events(self):
        self.event_bus.subscribe(Events.Chat.SEND_MESSAGE, self._on_send_message, weak=False)
        self.event_bus.subscribe(Events.Model.GET_LLM_PROCESSING_STATUS, self._on_get_llm_processing_status, weak=False)
        self.event_bus.subscribe("send_periodic_image_request", self._on_send_periodic_image_request, weak=False)
        self.event_bus.subscribe(Events.Chat.CLEAR_CHAT, self._on_clear_chat, weak=False)
        
        self.event_bus.subscribe(Events.Chat.STAGE_IMAGE, self._on_stage_image, weak=False)
        self.event_bus.subscribe(Events.Chat.CLEAR_STAGED_IMAGES, self._on_clear_staged_images, weak=False)
        
    async def async_send_message(
        self,
        user_input: str,
        system_input: str = "",
        image_data: list[bytes] | None = None,
        task_uid: str | None = None,  # Изменено с message_id на task_uid
        event_type: str | None = None
    ):
        try:
            print("[DEBUG] Начинаем async_send_message, показываем статус")
            self.llm_processing = True

            is_react = (event_type == 'react')
            
            # Обновляем статус задачи на PENDING если есть uid
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    'uid': task_uid,
                    'status': TaskStatus.PENDING
                })

            is_streaming = bool(self.settings.get("ENABLE_STREAMING", False))

            def stream_callback_handler(chunk: str):
                self.event_bus.emit(Events.GUI.APPEND_STREAM_CHUNK_UI, {'chunk': chunk})

            if is_streaming and not is_react:
                self.event_bus.emit(Events.GUI.PREPARE_STREAM_UI)

            if image_data:      # ДО вызова GENERATE_RESPONSE
                prepared = []
                for img in image_data:
                    if isinstance(img, bytes):
                        prepared.append(img)
                    elif isinstance(img, str):
                        # строка вида "abc..." или "data:image/...;base64,abc..."
                        try:
                            b64 = img.split(",", 1)[-1]
                            prepared.append(base64.b64decode(b64))
                        except Exception:
                            continue
                image_data = prepared if prepared else None

            response_result = self.event_bus.emit_and_wait(Events.Model.GENERATE_RESPONSE, {
                'user_input': user_input,
                'system_input': system_input,
                'image_data': image_data,
                'stream_callback': stream_callback_handler if is_streaming and not is_react else None,
                'message_id': task_uid,  # task_uid как message_id
                'event_type': event_type
            }, timeout=600.0)
            
            response = response_result[0] if response_result else None

            if not response:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        'uid': task_uid,
                        'status': TaskStatus.FAILED_ON_GENERATION,
                        'error': "Failed to generate response"
                    })
                self.llm_processing = False
                if not is_react:
                    self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {'error': "Превышено время ожидания ответа"})
                return None

            # Проверяем нужна ли озвучка
            if response and self.settings.get("USE_VOICEOVER") and not is_react:
                character_result = self.event_bus.emit_and_wait(Events.Model.GET_CURRENT_CHARACTER, timeout=3.0)
                current_character = character_result[0] if character_result else None
                
                logger.info(current_character)
                if current_character:
                    is_game_master = current_character.get('name') == 'GameMaster'
                    if not is_game_master or self.settings.get("GM_VOICE"):
                        # Обновляем статус задачи на VOICING
                        if task_uid:
                            self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                                'uid': task_uid,
                                'status': TaskStatus.VOICING
                            })
                        
                        speaker = current_character.get("silero_command")
                        if self.settings.get("AUDIO_BOT") == "@CrazyMitaAIbot":
                            speaker = current_character.get("miku_tts_name")
                        
                        self.event_bus.emit(Events.Audio.VOICEOVER_REQUESTED, {
                            'text': response,
                            'speaker': speaker,
                            'task_uid': task_uid
                        })
                        logger.info(f"Озвучка запрошена с task_uid: {task_uid}")
            else:
                if task_uid:
                    self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                        'uid': task_uid,
                        'status': TaskStatus.SUCCESS,
                        'result': {'response': response}
                    })


            if is_streaming and not is_react:
                self.event_bus.emit(Events.GUI.FINISH_STREAM_UI)
            elif not is_streaming and not is_react:
                self.event_bus.emit(Events.GUI.UPDATE_CHAT_UI, {
                    'role': 'assistant',
                    'response': response if response is not None else "...",
                    'is_initial': False,
                    'emotion': ''
                })

            self.event_bus.emit(Events.GUI.UPDATE_STATUS)
            self.event_bus.emit(Events.GUI.UPDATE_DEBUG_INFO)
            self.event_bus.emit(Events.GUI.UPDATE_TOKEN_COUNT)

            # Отправляем ответ в игру через старый механизм если нет task_uid
            if not task_uid:
                server_result = self.event_bus.emit_and_wait(Events.Server.GET_CHAT_SERVER, timeout=1.0)
                server = server_result[0] if server_result else None
                
                if server and hasattr(server, 'client_socket') and server.client_socket:
                    final_response_text = response if response else "..."
                    try:
                        server.send_message_to_server(final_response_text)
                        logger.info("Ответ отправлен в игру.")
                    except Exception as e:
                        logger.error(f"Не удалось отправить ответ в игру: {e}")
            
            self.llm_processing = False
            return response
                    
        except asyncio.TimeoutError:
            logger.warning("Тайм-аут: генерация ответа заняла слишком много времени.")
            self.llm_processing = False
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    'uid': task_uid,
                    'status': TaskStatus.FAILED_ON_GENERATION,
                    'error': "Timeout"
                })
            if not is_react:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {'error': "Превышено время ожидания ответа"})
            return "Произошла ошибка при обработке вашего сообщения."
        except Exception as e:
            logger.error(f"Ошибка в async_send_message: {e}", exc_info=True)
            self.llm_processing = False
            if task_uid:
                self.event_bus.emit(Events.Task.UPDATE_TASK_STATUS, {
                    'uid': task_uid,
                    'status': TaskStatus.FAILED_ON_GENERATION,
                    'error': str(e)
                })
            if not is_react:
                self.event_bus.emit(Events.Model.ON_FAILED_RESPONSE, {'error': f"Ошибка: {str(e)[:50]}..."})
            return "Произошла ошибка при обработке вашего сообщения."
    
    def _on_send_message(self, event: Event):
        data = event.data
        user_input = data.get('user_input', '')
        system_input = data.get('system_input', '')
        image_data = data.get('image_data', [])
        task_uid = data.get('task_uid')  # Изменено с message_id
        event_type = data.get('event_type')

        
        if image_data:
            self.event_bus.emit(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME)
        
        # Получаем главный asyncio-loop
        loop_res = self.event_bus.emit_and_wait(Events.Core.GET_EVENT_LOOP, timeout=1.0)
        loop = loop_res[0] if loop_res else None
        
        if loop and loop.is_running():
            # Запускаем корутину в этом loop'е и синхронно ждём результата
            import asyncio
            fut = asyncio.run_coroutine_threadsafe(
                self.async_send_message(user_input, system_input, image_data, task_uid, event_type),
                loop
            )
            try:
                response = fut.result(timeout=600)
                return response  # ответ попадёт вызвавшему emit_and_wait
            except Exception as e:
                logger.error(f"async_send_message failed: {e}", exc_info=True)
                return None
        else:
            # fallback: нет цикла ⇒ запускаем напрямую
            import asyncio
            response = asyncio.run(
                self.async_send_message(user_input, system_input, image_data, task_uid, event_type)
            )
            return response
    
    def _on_get_llm_processing_status(self, event: Event):
        return self.llm_processing
    
    def _on_send_periodic_image_request(self, event: Event):
        data = event.data
        
        if data.get('image_data'):
            self.event_bus.emit(Events.Capture.UPDATE_LAST_IMAGE_REQUEST_TIME)
        
        coro = self.async_send_message(
            user_input=data.get('user_input', ''),
            system_input=data.get('system_input', ''), 
            image_data=data.get('image_data', []),
            task_uid=data.get('task_uid'),
            event_type=data.get('event_type')
        )
        
        self.event_bus.emit(Events.Core.RUN_IN_LOOP, {
            'coroutine': coro,
            'callback': None
        })

    
    def _on_clear_chat(self, event: Event):
        pass

    
    def stage_image_bytes(self, img_bytes: bytes) -> int:
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="nm_clip_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(img_bytes)

        self.staged_images.append(tmp_path)
        logger.info(f"Clipboard image staged: {tmp_path}")
        return len(self.staged_images)

    def clear_staged_images(self):
        self.staged_images.clear()
    
    
    def _on_stage_image(self, event: Event):
        image_data = event.data.get('image_data')
        if image_data:
            if isinstance(image_data, bytes):
                self.stage_image_bytes(image_data)
            elif isinstance(image_data, str):
                self.staged_images.append(image_data)
    
    def _on_clear_staged_images(self, event: Event):
        self.clear_staged_images()