# File: chat_model.py
import concurrent.futures
import time
import requests
import tiktoken # Keep for token counting if used by calculate_cost_for_combined_messages
from openai import OpenAI
import re
import importlib
from typing import List, Dict, Any
import os # Added for os.environ

from Logger import logger
from characters import CrazyMita, KindMita, ShortHairMita, CappyMita, MilaMita, CreepyMita, SleepyMita, GameMaster, SpaceCartridge, DivanCartridge # Updated imports
from character import Character # Character base
from utils.PipInstaller import PipInstaller

from utils import SH, save_combined_messages, calculate_cost_for_combined_messages, replace_numbers_with_words # Keep utils
# from promptPart import PromptPart, PromptType # No longer needed


class ChatModel:
    def __init__(self, gui, api_key, api_key_res, api_url, api_model, api_make_request, pip_installer: PipInstaller):
        self.last_key = 0
        self.gui = gui
        self.pip_installer = pip_installer
        self.g4fClient = None
        self.g4f_available = False
        self._initialize_g4f() # Keep g4f initialization

        self.api_key = api_key
        self.api_key_res = api_key_res
        self.api_url = api_url
        self.api_model = api_model
        self.gpt4free_model = self.gui.settings.get("gpt4free_model")
        self.makeRequest = api_make_request # This seems to be a boolean flag

        try:
            self.client = OpenAI(api_key=self.api_key, base_url=self.api_url)
            logger.info("OpenAI client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            self.client = None

        try:
            self.tokenizer = tiktoken.encoding_for_model("gpt-4o-mini") # Or your preferred model
            self.hasTokenizer = True
        except Exception:
            logger.info("Tiktokenizer failed to initialize. Token counting might be affected.")
            self.hasTokenizer = False

        self.max_response_tokens = int(self.gui.settings.get("MODEL_MAX_RESPONSE_TOKENS", 3200))
        self.temperature = float(self.gui.settings.get("MODEL_TEMPERATURE", 0.5))
        self.presence_penalty = float(self.gui.settings.get("MODEL_PRESENCE_PENALTY", 0.0))
        
        # Cost calculation variables (if used)
        self.cost_input_per_1000 = 0.0432 
        self.cost_response_per_1000 = 0.1728

        self.memory_limit = int(self.gui.settings.get("MODEL_MESSAGE_LIMIT", 40)) # For historical messages

        self.current_character: Character = None
        self.current_character_to_change = str(self.gui.settings.get("CHARACTER"))
        self.characters: Dict[str, Character] = {}

        # Game-specific state - these should ideally be passed to character or managed elsewhere if possible
        # For now, keeping them here as per original. DSL might need them injected into character.variables.
        self.distance = 0.0
        self.roomPlayer = -1
        self.roomMita = -1
        self.nearObjects = ""
        self.actualInfo = ""
        
        self.infos_to_add_to_history: List[Dict] = [] # For temporary system messages to be added to history

        self.init_characters()
        self.HideAiData = True # Unused?
        self.max_request_attempts = int(self.gui.settings.get("MODEL_MESSAGE_ATTEMPTS_COUNT", 5))
        self.request_delay = float(self.gui.settings.get("MODEL_MESSAGE_ATTEMPTS_TIME", 0.20))

    def _initialize_g4f(self):
        logger.info("Проверка и инициализация g4f (после возможного обновления при запуске)...")
        try:
            from g4f.client import Client as g4fClient
            logger.info("g4f найден (при проверке), попытка инициализации клиента...")
            try:
                self.g4fClient = g4fClient()
                self.g4f_available = True
                logger.info("g4fClient успешно инициализирован.")
            except Exception as e:
                logger.error(f"Ошибка при инициализации g4fClient: {e}")
                self.g4fClient = None
                self.g4f_available = False
        except ImportError:
            logger.info("Модуль g4f не найден (при проверке). Попытка первоначальной установки...")

            target_version = self.gui.settings.get("G4F_VERSION", "0.4.7.7") # Using "0.x.y.z" format
            package_spec = f"g4f=={target_version}" if target_version != "latest" else "g4f"

            if self.pip_installer:
                success = self.pip_installer.install_package(
                    package_spec,
                    description=f"Первоначальная установка g4f версии {target_version}..."
                )
                if success:
                    logger.info("Первоначальная установка g4f (файлы) прошла успешно. Очистка кэша импорта...")
                    try:
                        importlib.invalidate_caches()
                        logger.info("Кэш импорта очищен.")
                    except Exception as e_invalidate:
                        logger.error(f"Ошибка при очистке кэша импорта: {e_invalidate}")

                    logger.info("Повторная попытка импорта и инициализации...")
                    try:
                        from g4f.client import Client as g4fClient # Re-import
                        logger.info("Повторный импорт g4f успешен. Попытка инициализации клиента...")
                        try:
                            self.g4fClient = g4fClient()
                            self.g4f_available = True
                            logger.info("g4fClient успешно инициализирован после установки.")
                        except Exception as e_init_after_install: # More specific exception name
                            logger.error(f"Ошибка при инициализации g4fClient после установки: {e_init_after_install}")
                            self.g4fClient = None
                            self.g4f_available = False
                    except ImportError:
                        logger.error("Не удалось импортировать g4f даже после успешной установки и очистки кэша.")
                        self.g4fClient = None
                        self.g4f_available = False
                    except Exception as e_import_after:
                        logger.error(f"Непредвиденная ошибка при повторном импорте/инициализации g4f: {e_import_after}")
                        self.g4fClient = None
                        self.g4f_available = False
                else:
                    logger.error("Первоначальная установка g4f не удалась (ошибка pip).")
                    self.g4fClient = None
                    self.g4f_available = False
            else:
                logger.error("Экземпляр PipInstaller не передан в ChatModel, установка g4f невозможна.")
                self.g4fClient = None
                self.g4f_available = False
        except Exception as e_initial:
            logger.error(f"Непредвиденная ошибка при первичной инициализации g4f: {e_initial}")
            self.g4fClient = None
            self.g4f_available = False


    def init_characters(self):
        self.crazy_mita_character = CrazyMita("Crazy", "Crazy Mita", "/speaker mita", short_name="CrazyMita", miku_tts_name="/set_person CrazyMita", silero_turn_off_video=True)
        self.kind_mita_character = KindMita("Kind", "Kind Mita", "/speaker kind", short_name="MitaKind", miku_tts_name="/set_person KindMita", silero_turn_off_video=True)
        self.cappy_mita_character = CappyMita("Cappy","Cappy Mita", "/speaker cap", short_name="CappieMita", miku_tts_name="/set_person CapMita", silero_turn_off_video=True)
        self.shorthair_mita_character = ShortHairMita("ShortHair","ShortHair Mita", "/speaker shorthair", short_name="ShorthairMita", miku_tts_name="/set_person ShortHairMita", silero_turn_off_video=True)
        self.mila_character = MilaMita("Mila","Mila", "/speaker mila", short_name="Mila", miku_tts_name="/set_person MilaMita", silero_turn_off_video=True)
        self.sleepy_character = SleepyMita("Sleepy","Sleepy Mita", "/speaker dream", short_name="SleepyMita", miku_tts_name="/set_person SleepyMita", silero_turn_off_video=True)
        self.creepy_character = CreepyMita("Creepy","Creepy Mita", "/speaker ghost", short_name="GhostMita", miku_tts_name="/set_person GhostMita", silero_turn_off_video=True)
        
        self.cart_space = SpaceCartridge("Cart_portal", "Cart_portal", "/speaker wheatley", short_name="Player", miku_tts_name="/set_person Player", silero_turn_off_video=True)
        self.cart_divan = DivanCartridge("Cart_divan", "Cart_divan", "/speaker engineer", short_name="Player", miku_tts_name="/set_person Player", silero_turn_off_video=True)
        self.GameMaster = GameMaster("GameMaster", "GameMaster", "/speaker dryad", short_name="PhoneMita", miku_tts_name="/set_person PhoneMita", silero_turn_off_video=True)

        self.characters = {
            self.crazy_mita_character.name: self.crazy_mita_character,
            self.kind_mita_character.name: self.kind_mita_character,
            self.cappy_mita_character.name: self.cappy_mita_character,
            self.shorthair_mita_character.name: self.shorthair_mita_character,
            self.mila_character.name: self.mila_character,
            self.sleepy_character.name: self.sleepy_character,
            self.creepy_character.name: self.creepy_character,
            self.cart_space.name: self.cart_space,
            self.cart_divan.name: self.cart_divan,
            self.GameMaster.name: self.GameMaster,
        }
        self.current_character = self.characters.get(self.current_character_to_change) or self.crazy_mita_character


    def get_all_mitas(self):
        logger.info(f"Available characters: {list(self.characters.keys())}")
        return list(self.characters.keys())

    def update_openai_client(self, reserve_key_token=None):
        logger.info("Attempting to update OpenAI client.")
        key_to_use = reserve_key_token if reserve_key_token else self.api_key

        if not key_to_use:
            logger.error("No API key available to update OpenAI client.")
            self.client = None
            return

        try:
            if self.api_url:
                logger.info(f"Using API key (masked): {SH(key_to_use)} and base URL: {self.api_url}")
                self.client = OpenAI(api_key=key_to_use, base_url=self.api_url)
            else:
                logger.info(f"Using API key (masked): {SH(key_to_use)} (no custom base URL)")
                self.client = OpenAI(api_key=key_to_use)
            logger.info("OpenAI client updated successfully.")
        except Exception as e:
            logger.error(f"Failed to update OpenAI client: {e}")
            self.client = None


    def generate_response(self, user_input: str, system_input: str = "") -> str:
        self.check_change_current_character()

        history_data = self.current_character.history_manager.load_history()
        llm_messages_history = history_data.get("messages", [])

        if self.infos_to_add_to_history:
            llm_messages_history.extend(self.infos_to_add_to_history)
            self.infos_to_add_to_history.clear()
            
        self.current_character.variables["GAME_DISTANCE"] = self.distance
        self.current_character.variables["GAME_ROOM_PLAYER"] = self.roomPlayer
        self.current_character.variables["GAME_ROOM_MITA"] = self.roomMita
        self.current_character.variables["GAME_NEAR_OBJECTS"] = self.nearObjects
        self.current_character.variables["GAME_ACTUAL_INFO"] = self.actualInfo
        
        combined_messages = self.current_character.get_full_system_setup_for_llm()

        if self.current_character != self.GameMaster:
            llm_messages_history_limited = llm_messages_history[-self.memory_limit:]
        else:
            llm_messages_history_limited = llm_messages_history[-8:]
        
        combined_messages.extend(llm_messages_history_limited)

        user_message_for_history = None
        if system_input:
            combined_messages.append({"role": "system", "content": system_input})
        if user_input:
            user_message_for_history = {"role": "user", "content": user_input}
            combined_messages.append(user_message_for_history)
        
        try:
            llm_response_content, success = self._generate_chat_response(combined_messages)

            if not success or not llm_response_content:
                logger.warning("LLM generation failed or returned empty.")
                return "..." 

            processed_response_text = self.current_character.process_response_nlp_commands(llm_response_content)
            
            # --- Start of Embedding/Command Replacer Integration ---
            final_response_text = processed_response_text # Initialize
            try:
                use_command_replacer = self.gui.settings.get("USE_COMMAND_REPLACER", False)
                # Check environment variable for default enabling
                enable_by_default = os.environ.get("ENABLE_COMMAND_REPLACER_BY_DEFAULT", "0") == "1"

                if use_command_replacer and enable_by_default:
                    if not hasattr(self, 'model_handler'): # Changed from 'embedder'
                        from utils.embedding_handler import EmbeddingModelHandler
                        self.model_handler = EmbeddingModelHandler()

                    if not hasattr(self, 'parser'):
                        from utils.command_parser import CommandParser
                        self.parser = CommandParser(model_handler=self.model_handler)
                    
                    min_similarity = float(self.gui.settings.get("MIN_SIMILARITY_THRESHOLD", 0.40))
                    category_threshold = float(self.gui.settings.get("CATEGORY_SWITCH_THRESHOLD", 0.18))
                    skip_comma = bool(self.gui.settings.get("SKIP_COMMA_PARAMETERS", True)) # Ensure bool conversion
                    
                    logger.info(f"Attempting command replacement on: {processed_response_text[:100]}...")
                    final_response_text, _ = self.parser.parse_and_replace(
                        processed_response_text,
                        min_similarity_threshold=min_similarity,
                        category_switch_threshold=category_threshold,
                        skip_comma_params=skip_comma
                    )
                    logger.info(f"After command replacement: {final_response_text[:100]}...")
                elif use_command_replacer and not enable_by_default:
                    logger.info("Command replacer is enabled by settings but not by default environment variable.")
                elif not use_command_replacer:
                    logger.info("Command replacer is disabled by settings.")

            except Exception as exi:
                logger.error(f"Error during command replacement using embeddings: {exi}", exc_info=True)
                # final_response_text remains processed_response_text if error occurs
            # --- End of Embedding/Command Replacer Integration ---

            assistant_message = {"role": "assistant", "content": final_response_text} # Use final_response_text
            
            if user_message_for_history: 
                llm_messages_history.append(user_message_for_history)
            llm_messages_history.append(assistant_message) 
            
            self.current_character.save_character_state_to_history(llm_messages_history)

            if self.current_character != self.GameMaster or bool(self.gui.settings.get("GM_VOICE")):
                self.gui.textToTalk = self.process_text_to_voice(final_response_text) # Use final_response_text
                self.gui.textSpeaker = self.current_character.silero_command
                self.gui.textSpeakerMiku = self.current_character.miku_tts_name
                self.gui.silero_turn_off_video = self.current_character.silero_turn_off_video
                logger.info(f"TTS Text: {self.gui.textToTalk}, Speaker: {self.gui.textSpeaker}")
            
            self.gui.update_debug_info() 
            return final_response_text # Return final_response_text

        except Exception as e:
            logger.error(f"Error during LLM response generation or processing: {e}", exc_info=True)
            return f"Ошибка: {e}"


    def check_change_current_character(self):
        if not self.current_character_to_change:
            return
        if self.current_character_to_change in self.characters:
            if not self.current_character or self.current_character.name != self.current_character_to_change:
                logger.info(f"Changing character to {self.current_character_to_change}")
                self.current_character = self.characters[self.current_character_to_change]
                self.current_character.reload_character_data()
            self.current_character_to_change = ""
        else:
            logger.warning(f"Attempted to change to unknown character: {self.current_character_to_change}")
            self.current_character_to_change = ""


    def _generate_chat_response(self, combined_messages):
        max_attempts = self.max_request_attempts
        retry_delay = self.request_delay
        request_timeout = 45 

        self._log_generation_start()
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Generation attempt {attempt}/{max_attempts}")
            response_text = None

            save_combined_messages(combined_messages, f"Attempt_{attempt}")

            try:
                if bool(self.gui.settings.get("NM_API_REQ", False)): 
                    formatted_for_request = combined_messages
                    if bool(self.gui.settings.get("GEMINI_CASE", False)):
                        formatted_for_request = self._format_messages_for_gemini(combined_messages)
                    
                    response_text = self._execute_with_timeout(
                        self._generate_request_response,
                        args=(formatted_for_request,),
                        timeout=request_timeout
                    )
                else: 
                    use_gpt4free_for_this_attempt = bool(self.gui.settings.get("gpt4free")) or \
                                                 (bool(self.gui.settings.get("GPT4FREE_LAST_ATTEMPT")) and attempt >= max_attempts)
                    
                    if use_gpt4free_for_this_attempt:
                        logger.info("Using gpt4free for this attempt.")
                    elif attempt > 1 and self.api_key_res: 
                        logger.info("Attempting with reserve API key.")
                        self.update_openai_client(reserve_key_token=self.GetOtherKey())
                    
                    response_text = self._generate_openapi_response(combined_messages, use_gpt4free=use_gpt4free_for_this_attempt)

                if response_text:
                    cleaned_response = self._clean_response(response_text)
                    logger.info(f"Successful response received (attempt {attempt}).")
                    if cleaned_response:
                        return cleaned_response, True
                    else:
                        logger.warning("Response became empty after cleaning.")
                else:
                    logger.warning(f"Attempt {attempt} yielded no response or an error handled within generation.")

            except concurrent.futures.TimeoutError:
                logger.error(f"Attempt {attempt} timed out after {request_timeout}s.")
            except Exception as e:
                logger.error(f"Error during generation attempt {attempt}: {str(e)}", exc_info=True)

            if attempt < max_attempts:
                logger.info(f"Waiting {retry_delay}s before next attempt...")
                time.sleep(retry_delay)
        
        logger.error("All generation attempts failed.")
        return None, False


    def _execute_with_timeout(self, func, args=(), kwargs={}, timeout=30):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                logger.error(f"Function {func.__name__} timed out after {timeout} seconds.")
                raise 
            except Exception as e:
                logger.error(f"Exception in function {func.__name__} executed with timeout: {e}")
                raise


    def _log_generation_start(self):
        logger.info("Preparing to generate LLM response.")
        logger.info(f"Max Response Tokens: {self.max_response_tokens}, Temperature: {self.temperature}")
        logger.info(f"Presence Penalty: {self.presence_penalty} (Used: {bool(self.gui.settings.get('USE_MODEL_PRESENCE_PENALTY'))})")
        logger.info(f"API URL: {self.api_url}, API Model: {self.api_model}")
        logger.info(f"g4f Enabled: {bool(self.gui.settings.get('gpt4free'))}, g4f Model: {self.gpt4free_model}")
        logger.info(f"Custom Request (NM_API_REQ): {bool(self.gui.settings.get('NM_API_REQ', False))}")
        if bool(self.gui.settings.get('NM_API_REQ', False)):
            logger.info(f"  Custom Request Model (NM_API_MODEL): {self.gui.settings.get('NM_API_MODEL')}")
            logger.info(f"  Gemini Case for Custom Req: {bool(self.gui.settings.get('GEMINI_CASE', False))}")


    def _format_messages_for_gemini(self, combined_messages):
        formatted_messages = []
        for i, msg in enumerate(combined_messages):
            if msg["role"] == "system":
                formatted_messages.append({"role": "user", "content": f"[System Instruction]: {msg['content']}"})
            elif msg["role"] == "assistant":
                 formatted_messages.append({"role": "model", "content": msg['content']})
            else: # user
                formatted_messages.append(msg)
        return formatted_messages


    def _generate_request_response(self, formatted_messages):
        try:
            if bool(self.gui.settings.get("GEMINI_CASE", False)):
                logger.info("Dispatching to Gemini request generation.")
                return self.generate_request_gemini(formatted_messages)
            else:
                logger.info("Dispatching to common request generation.")
                return self.generate_request_common(formatted_messages)
        except Exception as e:
            logger.error(f"Error in _generate_request_response dispatcher: {str(e)}", exc_info=True)
            return None


    def _generate_openapi_response(self, combined_messages, use_gpt4free=False):
        target_client = None
        model_to_use = ""

        if use_gpt4free:
            if not self.g4f_available or not self.g4fClient:
                logger.error("gpt4free selected, but client is not available.")
                return None
            target_client = self.g4fClient
            model_to_use = self.gui.settings.get("gpt4free_model", "gpt-3.5-turbo") 
            logger.info(f"Using g4f client with model: {model_to_use}")
        else:
            if not self.client:
                logger.info("OpenAI client not initialized. Attempting to re-initialize.")
                self.update_openai_client() 
                if not self.client:
                    logger.error("OpenAI client is not available after re-initialization attempt.")
                    return None
            target_client = self.client
            model_to_use = self.api_model
            logger.info(f"Using OpenAI compatible client with model: {model_to_use}")

        try:
            self.change_last_message_to_user_for_gemini(model_to_use, combined_messages)
            
            final_params = self.get_final_params(model_to_use, combined_messages)
            
            logger.info(f"Requesting completion from {model_to_use} with temp={final_params.get('temperature')}, max_tokens={final_params.get('max_tokens')}")
            completion = target_client.chat.completions.create(**final_params)
            
            if completion and completion.choices:
                response_content = completion.choices[0].message.content
                logger.info("Completion successful.")
                return response_content.strip() if response_content else None
            else:
                logger.warning("No completion choices received or completion object is empty.")
                if completion: self.try_print_error(completion)
                return None
        except Exception as e:
            logger.error(f"Error during OpenAI/g4f API call: {str(e)}", exc_info=True)
            if hasattr(e, 'response') and e.response: 
                 logger.error(f"API Error details: Status={e.response.status_code}, Body={e.response.text}")
            return None


    def change_last_message_to_user_for_gemini(self, api_model, combined_messages):
        if combined_messages and ("gemini" in api_model.lower() or "gemma" in api_model.lower()) and \
           combined_messages[-1]["role"] == "system":
            logger.info(f"Adjusting last message for {api_model}: system -> user with [SYSTEM INFO] prefix.")
            combined_messages[-1]["role"] = "user"
            combined_messages[-1]["content"] = f"[SYSTEM INFO] {combined_messages[-1]['content']}"


    def try_print_error(self, completion_or_error):
        logger.warning("Attempting to print error details from API response/error object.")
        if not completion_or_error:
            logger.warning("No error object or completion data to parse.")
            return

        if hasattr(completion_or_error, 'error') and completion_or_error.error:
            error_data = completion_or_error.error
            logger.warning(f"API Error: Code={getattr(error_data, 'code', 'N/A')}, Message='{getattr(error_data, 'message', 'N/A')}', Type='{getattr(error_data, 'type', 'N/A')}'")
            if hasattr(error_data, 'param') and error_data.param:
                logger.warning(f"  Param: {error_data.param}")
        elif isinstance(completion_or_error, dict) and 'error' in completion_or_error:
             error_data = completion_or_error['error']
             logger.warning(f"API Error (from dict): {error_data}")
        elif hasattr(completion_or_error, 'message'): 
             logger.warning(f"API Error: {completion_or_error.message}")
        else:
            logger.warning(f"Could not parse detailed error. Raw object: {str(completion_or_error)[:500]}")


    def _clean_response(self, response_text: str) -> str:
        if not isinstance(response_text, str):
            logger.warning(f"Clean response expected string, got {type(response_text)}. Returning as is.")
            return response_text
        
        cleaned = response_text
        if cleaned.startswith("```json\n") and cleaned.endswith("\n```"):
            cleaned = cleaned[len("```json\n"):-len("\n```")]
        elif cleaned.startswith("```\n") and cleaned.endswith("\n```"):
            cleaned = cleaned[len("```\n"):-len("\n```")]
        elif cleaned.startswith("```") and cleaned.endswith("```"): 
            cleaned = cleaned[3:-3]
            
        return cleaned.strip()


    # def generate_request_gemini(self, combined_messages):
    #     params_for_gemini = self.get_params(model="gemini-pro")
    #     self.clear_endline_sim(params_for_gemini) # Added from other versions

    #     gemini_contents = []
    #     for msg in combined_messages: 
    #         role = "model" if msg["role"] == "assistant" else msg["role"]
    #         if role not in ["user", "model"]: 
    #             logger.warning(f"Invalid role '{role}' for Gemini, converting to 'user'. Content: {msg['content'][:50]}")
    #             role = "user" 
    #         gemini_contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    #     data = {
    #         "contents": gemini_contents,
    #         "generationConfig": params_for_gemini
    #     }

    #     headers = {"Content-Type": "application/json"} 

    #     api_url_with_key = self.api_url 
    #     if ":generateContent" not in api_url_with_key and not api_url_with_key.endswith("/generateContent"):
    #          api_url_with_key = api_url_with_key.replace("/v1beta/models/", "/v1beta/models/") + ":generateContent" # Ensure correct path
    #          if "?key=" not in api_url_with_key and self.api_key: 
    #              api_url_with_key += f"?key={self.api_key}"

    #     logger.info(f"Sending request to Gemini API: {api_url_with_key}")
        
    #     try:
    #         response = requests.post(api_url_with_key, headers=headers, json=data, timeout=40)
    #         response.raise_for_status() 

    #         response_data = response.json()
    #         if response_data.get("candidates"):
    #             generated_text = response_data["candidates"][0].get("content", {}).get("parts", [{}])[0].get("text", "")
    #             logger.info("Gemini response successful.")
    #             return generated_text
    #         else:
    #             logger.warning(f"Gemini response missing candidates. Full response: {response_data}")
    #             if "promptFeedback" in response_data:
    #                 logger.warning(f"Gemini Prompt Feedback: {response_data['promptFeedback']}")
    #             return None
    #     except requests.exceptions.HTTPError as http_err:
    #         logger.error(f"Gemini API HTTP error: {http_err} - Response: {http_err.response.text}")
    #         return None
    #     except Exception as e:
    #         logger.error(f"Error during Gemini API request: {str(e)}", exc_info=True)
    #         return None


    # def generate_request_common(self, combined_messages):
    #     model_name = self.gui.settings.get("NM_API_MODEL", self.api_model)
    #     params_for_common = self.get_params(model=model_name)
    #     self.clear_endline_sim(params_for_common) # Added from other versions

    #     data = {
    #         "model": model_name,
    #         "messages": combined_messages, 
    #         **params_for_common 
    #     }

    #     headers = {
    #         "Content-Type": "application/json",
    #     }
    #     if self.api_key: 
    #         headers["Authorization"] = f"Bearer {self.api_key}"

    #     logger.info(f"Sending request to common API: {self.api_url} with model: {model_name}")
        
    #     try:
    #         response = requests.post(self.api_url, headers=headers, json=data, timeout=40)
    #         response.raise_for_status()
            
    #         response_data = response.json()
    #         if response_data.get("choices"):
    #             generated_text = response_data["choices"][0].get("message", {}).get("content", "")
    #             logger.info("Common API response successful.")
    #             return generated_text
    #         else:
    #             logger.warning(f"Common API response missing choices. Full response: {response_data}")
    #             return None
    #     except requests.exceptions.HTTPError as http_err:
    #         logger.error(f"Common API HTTP error: {http_err} - Response: {http_err.response.text}")
    #         return None
    #     except Exception as e:
    #         logger.error(f"Error during common API request: {str(e)}", exc_info=True)
    #         return None


    def _get_provider_key(self, model_name: str) -> str:
        if not model_name: return 'openai' 
        model_name_lower = model_name.lower()
        if 'gpt-4' in model_name_lower or 'gpt-3.5' in model_name_lower: return 'openai'
        if 'gemini' in model_name_lower or 'gemma' in model_name_lower: return 'gemini'
        if 'claude' in model_name_lower: return 'anthropic'
        if 'deepseek' in model_name_lower: return 'deepseek'
        logger.info(f"Unknown provider for model '{model_name}', defaulting to 'openai' parameter naming conventions.")
        return 'openai'


    # def get_params(self, model: str = None) -> Dict[str, Any]:
    #     current_model_name = model if model is not None else self.api_model
    #     provider_key = self._get_provider_key(current_model_name)
        
    #     params: Dict[str, Any] = {}

    #     if self.temperature is not None:
    #         params['temperature'] = self.temperature

    #     if self.max_response_tokens is not None:
    #         if provider_key in ['openai', 'deepseek', 'anthropic']: 
    #             params['max_tokens'] = self.max_response_tokens
    #         elif provider_key == 'gemini':
    #             params['maxOutputTokens'] = self.max_response_tokens

    #     if self.presence_penalty is not None and bool(self.gui.settings.get("USE_MODEL_PRESENCE_PENALTY", False)):
    #         if provider_key in ['openai', 'deepseek']:
    #             params['presence_penalty'] = self.presence_penalty
    #         elif provider_key == 'gemini': 
    #             logger.info(f"Presence penalty not directly supported by Gemini config for model {current_model_name}. Skipping.")
        
    #     params = self.remove_unsupported_params(current_model_name, params)
    #     return params

    # def get_final_params(self, model_name: str, messages: List[Dict]) -> Dict[str, Any]:
    #     final_params = {
    #         "model": model_name,
    #         "messages": messages,
    #         **self.get_params(model=model_name)
    #     }
    #     self.clear_endline_sim(final_params) # Added from other versions
    #     return final_params

    # def clear_endline_sim(self,params):
    #     for key, value in params.items():
    #         if isinstance(value, str):
    #             params[key] = value.replace("'\x00", "") 


    # def remove_unsupported_params(self,model,params):
    #     """Тут удаляем все лишние параметры"""
    #     if model in ("gemini-2.5-pro-exp-03-25","gemini-2.5-flash-preview-04-17"):
    #         params.pop("presencePenalty", None) # This was for Gemini, but get_params already skips it.
    #         # However, if presence_penalty (OpenAI style) was added by mistake, this would remove it.
    #         # More robustly, check for actual Gemini param names if they were added by mistake.
    #         # For now, keeping this as it was in the provided code.
    #     return params


    def process_text_to_voice(self, text_to_speak: str) -> str:
        if not isinstance(text_to_speak, str):
            logger.warning(f"process_text_to_voice expected string, got {type(text_to_speak)}. Converting to string.")
            text_to_speak = str(text_to_speak)

        clean_text = re.sub(r"<[^>]+>.*?</[^>]+>", "", text_to_speak, flags=re.DOTALL)
        clean_text = re.sub(r"<[^>]+>", "", clean_text)
        
        try:
            clean_text = replace_numbers_with_words(clean_text)
        except NameError: 
            logger.debug("replace_numbers_with_words utility not found or used.")
            pass 
            
        if not clean_text.strip():
            clean_text = "..." 
            logger.info("TTS text was empty after cleaning, using default '...'")
            
        return clean_text.strip()


    def reload_promts(self): 
        logger.info("Reloading current character data.")
        if self.current_character:
            self.current_character.reload_character_data()
            logger.info(f"Character {self.current_character.name} data reloaded.")
        else:
            logger.warning("No current character selected to reload.")

    def add_temporary_system_info(self, content: str):
        system_info_message = {"role": "system", "content": content}
        self.infos_to_add_to_history.append(system_info_message)
        logger.info(f"Queued temporary system info: {content[:100]}...")

    #region TokensCounting
    def calculate_cost(self, user_input_text: str): 
        if not self.hasTokenizer:
            logger.warning("Tokenizer not available, cannot calculate cost accurately.")
            return 0, 0.0
        
        temp_messages_for_costing = []
        if self.current_character:
            history_data = self.current_character.history_manager.load_history()
            temp_messages_for_costing.extend(history_data.get("messages", []))
        
        temp_messages_for_costing.append({"role": "user", "content": user_input_text})
        
        token_count = self.count_tokens(temp_messages_for_costing)
        cost = (token_count / 1000) * self.cost_input_per_1000 
        
        logger.info(f"Estimated token count for input '{user_input_text[:50]}...': {token_count}, Estimated cost: {cost:.5f}")
        return token_count, cost

    def count_tokens(self, messages_list: List[Dict]) -> int:
        if not self.hasTokenizer:
            return 0 

        total_tokens = 0
        for msg in messages_list:
            if isinstance(msg, dict) and "content" in msg and isinstance(msg["content"], str):
                try:
                    total_tokens += len(self.tokenizer.encode(msg["content"]))
                except Exception as e:
                    logger.warning(f"Error encoding content for token counting: {e}. Content snippet: {msg['content'][:50]}")
        return total_tokens
    #endregion

    def GetOtherKey(self) -> str | None: 
        all_keys = []
        if self.api_key: 
            all_keys.append(self.api_key)
        
        reserve_keys_str = self.gui.settings.get("NM_API_KEY_RES", "")
        if reserve_keys_str:
            all_keys.extend([key.strip() for key in reserve_keys_str.split() if key.strip()])
        
        seen = set()
        unique_keys = [x for x in all_keys if not (x in seen or seen.add(x))]

        if not unique_keys:
            logger.warning("No API keys configured (main or reserve).")
            return None
        
        if len(unique_keys) == 1:
            self.last_key = 0 
            return unique_keys[0]

        self.last_key = (self.last_key + 1) % len(unique_keys)
        selected_key = unique_keys[self.last_key]
        
        logger.info(f"Selected API key index: {self.last_key} (masked: {SH(selected_key)}) from {len(unique_keys)} unique keys.")
        return selected_key
    
    # region невошедшие (из старых версий, но могут быть полезны или заменены)
    def get_room_name(self, room_id): # This seems generally useful, kept.
        room_names = {
            0: "Кухня",
            1: "Зал",
            2: "Комната",
            3: "Туалет",
            4: "Подвал"
        }
        return room_names.get(room_id, "?")
    
    # This method was in the "невошедшие" section of V1/V3 but has a different signature than add_temporary_system_info.
    # The current `add_temporary_system_info` which uses `self.infos_to_add_to_history` is the primary mechanism in the new system.
    def add_temporary_system_message(self, messages: List[Dict], content: str):
        if not isinstance(messages, list):
            logger.error("add_temporary_system_message ожидает список сообщений.")
            return
        system_message = {
            "role": "system",
            "content": content
        }
        messages.append(system_message)
        logger.debug(f"Временно добавлено системное сообщение в переданный список: {content[:100]}...")

    # endregion

    # region Old but working
    def generate_request_gemini(self, combined_messages):
        params = self.get_params()
        self.clear_endline_sim(params)
        data = {
            "contents": [
                {"role": "model" if msg["role"] == "assistant" else msg["role"], "parts": [{"text": msg["content"]}]}
                for msg in combined_messages
            ],
            "generationConfig": params
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        logger.info("Отправляю запрос к Gemini")
        save_combined_messages(data, "Gem2")
        response = requests.post(self.api_url, headers=headers, json=data)

        if response.status_code == 200:
            response_data = response.json()
            generated_text = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get(
                "text", "")
            logger.info("Answer: \n" + generated_text)
            return generated_text
        else:
            logger.error(f"Ошибка: {response.status_code}, {response.text}")
            return None
    
    def generate_request_common(self, combined_messages):
        data = {
            "model": self.gui.settings.get("NM_API_MODEL"),
            "messages": [
                {"role": msg["role"], "content": msg["content"]} for msg in combined_messages
            ]
        }

        # Объединяем params в data
        params = self.get_params()
        self.clear_endline_sim(params)
        data.update(params)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        logger.info("Отправляю запрос к RequestCommon")
        save_combined_messages(data, "RequestCommon")
        response = requests.post(self.api_url, headers=headers, json=data)

        if response.status_code == 200:
            response_data = response.json()
            # Формат ответа DeepSeek отличается от Gemini
            generated_text = response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
            logger.info("Common request: \n" + generated_text)
            return generated_text
        else:
            logger.error(f"Ошибка: {response.status_code}, {response.text}")
            return None
        
    def get_params(self, model=None):
        current_model = model if model is not None else self.api_model
        provider_key = self._get_provider_key(current_model)

        params = {}

        # Температура часто называется одинаково
        if self.temperature is not None:
            params['temperature'] = self.temperature

        # Макс. токены - названия могут различаться
        if self.max_response_tokens is not None:
            if provider_key == 'openai' or provider_key == 'deepseek' or provider_key == 'anthropic':
                params['max_tokens'] = self.max_response_tokens
            elif provider_key == 'gemini':
                params['maxOutputTokens'] = self.max_response_tokens
            # Добавьте другие провайдеры

        # Штраф за присутствие - названия могут различаться, и параметр может отсутствовать у некоторых провайдеров
        if bool(self.gui.settings.get("USE_MODEL_PRESENCE_PENALTY")):
            if provider_key == 'openai' or provider_key == 'deepseek':
                params['presence_penalty'] = self.presence_penalty
            elif provider_key == 'gemini':
                params['presencePenalty'] = self.presence_penalty
            # Anthropic, например, не имеет прямого аналога этого параметра в том же виде.
            # Поэтому мы просто не добавляем его для Anthropic.

        # Добавьте другие параметры аналогично
        # if self.some_other_param is not None:
        #     if provider_key == 'openai': params['openai_name'] = self.some_other_param
        #     elif provider_key == 'gemini': params['gemini_name'] = self.some_other_param
        #     # и т.д.

        params = self.remove_unsupported_params(current_model,params)

        return params
    
    def get_final_params(self, model, messages):
        """Модель, сообщения и параметры"""
        final_params = {
            "model": model,
            "messages": messages,
        }
        final_params.update(self.get_params(model))

        self.clear_endline_sim(final_params)

        return final_params
    
    def clear_endline_sim(self,params):
        for key, value in params.items():
            if isinstance(value, str):
                params[key] = value.replace("'\x00", "").replace("\x00", "")

    def remove_unsupported_params(self,model,params):
        """Тут удаляем все лишние параметры"""
        if model in ("gemini-2.5-pro-exp-03-25","gemini-2.5-flash-preview-04-17"):
            params.pop("presencePenalty", None)
        return params

    # endregion