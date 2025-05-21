from typing import Dict, List

from FSM.FiniteStateMachine import FiniteStateMachine
from Logger import logger
from MemorySystem import MemorySystem
from promptPart import PromptPart, PromptType
from HistoryManager import HistoryManager
from utils import clamp
import datetime
import re


class Character:
    def __init__(self, name: str, silero_command: str, short_name: str, miku_tts_name: str = "Player", silero_turn_off_video=False, ):

        self.fsm = None
        self.name = name
        self.silero_command = silero_command
        self.silero_turn_off_video = silero_turn_off_video
        self.miku_tts_name = miku_tts_name
        self.short_name = short_name

        self.fixed_prompts: List[PromptPart] = []
        self.float_prompts: List[PromptPart] = []
        self.temp_prompts: List[PromptPart] = []
        self.events: List[PromptPart] = []
        self.variables = {}
        self.attitude = 60
        self.boredom = 10
        self.stress = 5

        self.history_manager = HistoryManager(self.name)
        self.load_history()

        self.memory_system = MemorySystem(self.name)
        #        self.state = EventState()

        """
        Спорные временные переменные
        """
        self.LongMemoryRememberCount = 0
        self.MitaLongMemory = ""

        self.init()

    def init_variables(self):
        """Базовые"""
        self.attitude = 60
        self.boredom = 10
        self.stress = 5

    def add_prompt_part(self, part: PromptPart):
        if part.is_fixed:
            self.fixed_prompts.append(part)
        elif part.is_floating:
            part.active = False
            self.float_prompts.append(part)
        elif part.is_temporary:
            self.temp_prompts.append(part)
        else:
            logger.info("Добавляется неизвестный промпарт")

    def find_prompt(self, list_to_find, name):
        return next((p for p in list_to_find if p.name == name), None)

    def find_float(self, name):
        logger.info("Попытка найти ивент")
        return self.find_prompt(self.float_prompts, name)

    def replace_prompt(self, name_current: str, name_next: str):
        """
        Заменяет активный промпт.

        :param name_current: Имя текущего активного промпта.
        :param name_next: Имя следующего промпта, который нужно активировать.
        """
        logger.info("Замена промпарта")

        # Находим текущий активный промпт
        current_prompt = self.find_prompt(self.fixed_prompts, name_current)
        if current_prompt:
            current_prompt.active = False
        else:
            logger.info(f"Промпт '{name_current}' не существует")

        # Находим следующий промпт
        next_prompt = self.find_prompt(self.fixed_prompts, name_next)
        if next_prompt:
            next_prompt.active = True
        else:
            logger.info(f"Промпт '{name_next}' не существует")

    def prepare_fixed_messages(self) -> List[Dict]:
        """Создает фиксированные начальные установки
        :return: сообщения до
        """

        messages = []

        for part in self.fixed_prompts:
            text = str(part).strip()
            if part.active and text != "":
                m = {"role": "system", "content": text}
                messages.append(m)

        memory_message = {"role": "system", "content": self.memory_system.get_memories_formatted()}
        messages.append(memory_message)

        if self.fsm:
            try:
                state_message = {"role": "system", "content": self.fsm.get_prompts_text(PromptType.FIXED_START)}
                messages.append(state_message)
            except Exception as ex:
                logger.info("FSM", ex)

        return messages

    def prepare_float_messages(self, messages):
        """
        Добавляет плавающие промпты (очищает их из ивентов)

        :param messages сообщения фиксированные заготовленные
        :return: сообщения
        """
        logger.info(f"Добавление плавающих")
        for part in self.float_prompts:

            text = str(part).strip()
            if part.active and text != "":
                m = {"role": "system", "content": str(text)}
                messages.append(m)
                part.active = False
                logger.info(f"Добавляю плавающий промпт {text}")
        if self.fsm:
            try:
                state_message = {"role": "system", "content": self.fsm.get_prompts_text(PromptType.FLOATING_SYSTEM)}
                messages.append(state_message)
            except Exception as ex:
                logger.info("FSM", ex)

        return messages

    def add_context(self, messages):
        """
        Перед сообщением пользователя будет контекст, он не запишется в историю.
        :param messages:
        :return: Messages с добавленным контекстом
        """

        self.LongMemoryRememberCount += 1

        """Обработка пользовательского ввода и добавление сообщений"""
        # Получаем текущую дату и время, убираем микросекунды
        date_now = datetime.datetime.now().replace(microsecond=0)

        # Форматируем дату: год, месяц словами, день месяца, день недели в скобках
        formatted_date = date_now.strftime("%Y %B %d (%A) %H:%M")

        repeated_system_message = f"Time: {formatted_date}."

        if self.LongMemoryRememberCount % 3 == 0:
            repeated_system_message += " Remember facts for 3 messages using block <+memory>"
        if self.LongMemoryRememberCount % 5 == 0:
            repeated_system_message += " Update memories for 5 messages using block <#memory>"
        if self.LongMemoryRememberCount % 10 == 0:
            repeated_system_message += " Delete repeating memories if required using block <-memory>"

        if self.fsm:
            try:
                repeated_system_message += self.fsm.get_prompts_text(PromptType.CONTEXT_TEMPORARY)
                repeated_system_message += self.fsm.get_variables_text()
            except Exception as ex:
                logger.info("FSM", ex)

        messages.append({"role": "system", "content": repeated_system_message})

        return messages

    def init(self):
        raise NotImplementedError("Метод init должен быть реализован в подклассе")

    def process_logic(self, messages: dict = None):
        """То, как должно что-то менять до получения ответа"""
        logger.info("Персонаж без изменяемой логики промптов")

    def process_response(self, response: str):
        response = self.extract_and_process_memory_data(response)
        try:
            response = self._process_behavior_changes(response)
        except Exception as e:
            logger.warning(e)
        """То, как должно что-то меняться в результате ответа"""

        if self.fsm:
            try:
                self.fsm.process_response(response)
            except Exception as ex:
                logger.info("FSM", ex)

        return response

    def _process_behavior_changes(self, response):
        """
        Обрабатывает изменения переменных на основе строки формата <p>x,x,x<p>.
        """
        start_tag = "<p>"
        end_tag = "</p>"

        if start_tag in response and end_tag in response:
            # Извлекаем изменения переменных
            start_index = response.index(start_tag) + len(start_tag)
            end_index = response.index(end_tag, start_index)
            changes_str = response[start_index:end_index]

            # Разделяем строку на отдельные значения
            changes = [float(x.strip()) for x in changes_str.split(",")]

            if len(changes) == 3:
                # Применяем изменения к переменным
                self.adjust_attitude(changes[0])
                self.adjust_boredom(changes[1])
                self.adjust_stress(changes[2])

        return response

    def extract_and_process_memory_data(self, response):
        """
        Извлекает данные из ответа с тегами памяти и выполняет операции.
        Форматы тегов:
        - Добавление: <+memory>priority|content</memory>
        - Обновление: <#memory>number|priority|content</memory>
        - Удаление: <-memory>number</memory>
        """
        # Регулярное выражение для захвата тегов памяти
        memory_pattern = r"<([+#-])memory>(.*?)</memory>"
        matches = re.findall(memory_pattern, response, re.DOTALL)

        if matches:
            logger.info("Обнаружены команды изменения памяти!")
            for operation, content in matches:
                content = content.strip()
                try:
                    # Обработка добавления
                    if operation == "+":
                        parts = [p.strip() for p in content.split('|', 1)]
                        if len(parts) == 2:
                            priority, mem_content = parts
                            self.memory_system.add_memory(
                                priority=priority,
                                content=mem_content
                            )
                            logger.info(f"Добавлено воспоминание #{mem_content}")
                        elif len(parts) == 1:
                            mem_content = parts[0]
                            self.memory_system.add_memory(
                                priority="normal",
                                content=mem_content
                            )
                            logger.info(f"Добавлено воспоминание #{mem_content} (Старый формат)")
                        else:
                            raise ValueError("Неверный формат данных для добавления")




                    # Обработка обновления
                    elif operation == "#":
                        parts = [p.strip() for p in content.split('|', 2)]
                        if len(parts) != 3:
                            raise ValueError("Неверный формат данных для обновления")

                        number, priority, mem_content = parts
                        self.memory_system.update_memory(
                            number=int(number),
                            priority=priority,
                            content=mem_content
                        )
                        logger.info(f"Обновлено воспоминание #{number}")

                    # Обработка удаления
                    elif operation == "-":
                        content = content.strip()
                        # Обработка записи через запятую (5,6,7)
                        if "," in content:
                            numbers = [num.strip() for num in content.split(",")]
                            for number in numbers:
                                if number.isdigit():
                                    self.memory_system.delete_memory(number=int(number))
                                    logger.info(f"Удалено воспоминание #{number}")
                        # Обработка записи через дефис (5-9)
                        elif "-" in content:
                            start_end = content.split("-")
                            if len(start_end) == 2 and start_end[0].isdigit() and start_end[1].isdigit():
                                start = int(start_end[0])
                                end = int(start_end[1])
                                for number in range(start, end + 1):
                                    self.memory_system.delete_memory(number=number)
                                    logger.info(f"Удалено воспоминание #{number}")
                        # Обычное удаление одного числа
                        else:
                            if content.isdigit():
                                self.memory_system.delete_memory(number=int(content))
                                logger.info(f"Удалено воспоминание #{content}")

                    self.MitaLongMemory = {"role": "system", "content": self.memory_system.get_memories_formatted()}
                except Exception as e:
                    logger.info(f"Ошибка обработки памяти: {str(e)}")

        return response

    def reload_prompts(self):
        """Перезагружает все промпты персонажа"""
        logger.info(f"Перезагрузка промптов для {self.name}")
        self.fixed_prompts = []
        self.temp_prompts = []
        self.float_prompts = []
        self.init()
        logger.info(f"Промпты для {self.name} успешно перезагружены")

    #region History
    def load_history(self):
        data = self.history_manager.load_history()

        variables = data.get("variables")
        self.attitude = variables.get("attitude", self.attitude)
        self.boredom = variables.get("boredom", self.boredom)
        self.stress = variables.get("stress", self.stress)
        """Кастомная обработка загрузки истории"""
        return data

    def safe_history(self, messages: dict, temp_context: dict):
        """Кастомная обработка сохранения истории"""
        history_data = {
            'fixed_parts': self.prepare_fixed_messages(),
            'messages': messages,
            'temp_context': temp_context,
            'variables': self.variables
        }
        self.variables = {
            "attitude": self.attitude,
            "boredom": self.boredom,
            "stress": self.stress,
        }
        self.history_manager.save_history(history_data)

    def clear_history(self):
        self.init_variables()
        self.memory_system.clear_memories()
        self.history_manager.clear_history()
        self.load_history()

    def add_message_to_history(self, message):
        self.safe_history(self.load_history().get("messages").append(message), {})

    #endregion

    def current_variables(self):
        return {
            "role": "system",
            "content": (f"Твои характеристики:"
                        f"Отношение: {self.attitude}/100."
                        f"Скука: {self.boredom}/100."
                        f"Стресс: {self.stress}/100.")
        }

    def current_variables_string(self) -> str:
        characteristics = {
            "Отношение": self.attitude,
            "Стресс": self.stress,
            "Скука": self.boredom
        }
        return f"Характеристики {self.name}:\n" + "\n".join(
            f"- {key}: {value}" for key, value in characteristics.items()
        )

    def adjust_attitude(self, amount):
        amount = clamp(amount, -5, 5)
        """Корректируем отношение."""
        self.attitude = clamp(self.attitude + amount, 0, 100)
        logger.info(f"Отношение изменилось на {amount}, новое значение: {self.attitude}")

    def adjust_boredom(self, amount):
        amount = clamp(amount, -5, 5)
        """Корректируем уровень скуки."""
        self.boredom = clamp(self.boredom + amount, 0, 100)
        logger.info(f"Скука изменилась на {amount}, новое значение: {self.boredom}")

    def adjust_stress(self, amount):
        amount = clamp(amount, -5, 5)
        """Корректируем уровень стресса."""
        self.stress = clamp(self.stress + amount, 0, 100)
        logger.info(f"Стресс изменился на {amount}, новое значение: {self.stress}")

    def get_path(self, path):
        return f"Prompts/{self.name}/{path}"

    def append_common_prompts(self, promts):
        """Добавляет к списку необходимых промптов общие"""

        promts.append(PromptPart(PromptType.FIXED_START, "Prompts/Common/Security.txt"))
        promts.append(PromptPart(PromptType.FIXED_START, "Prompts/Common/None.txt", stride=-1))
        promts.append(PromptPart(PromptType.FIXED_START, "Prompts/Common/Dialogue.txt"))


#region Cartridges
class Cartridge(Character):
    ...


class SpaceCartridge(Cartridge):

    def init(self):
        self.cart_space_prompts()

    def cart_space_prompts(self):
        Prompts = []

        response_structure = "Prompts/Cartridges/space cartridge.txt"
        Prompts.append(PromptPart(PromptType.FIXED_START, response_structure))

        self.append_common_prompts(Prompts)

        for prompt in Prompts:
            self.add_prompt_part(prompt)


from SettingsManager import SettingsManager as settings


class DivanCartridge(Cartridge):

    def init(self):
        self.init_prompts()

    def init_prompts(self):
        Prompts = []

        response_structure = "Prompts/Cartridges/divan_cart.txt"
        Prompts.append(PromptPart(PromptType.FIXED_START, response_structure))

        self.append_common_prompts(Prompts)

        for prompt in Prompts:
            self.add_prompt_part(prompt)


#endregion


class GameMaster(Character):
    """
    Специальный служебный персонаж, отвечающий за ход диалога
    """

    #class GameMaster(Character):
       # def __init__(self, *args, **kwargs):
       #     super().__init__(*args, **kwargs)  # Важно: вызываем родительский __init__

    def init(self):
        self.init_prompts()

    def init_prompts(self):
        Prompts = []

        Prompts.append(PromptPart(PromptType.FIXED_START, self.get_path("Game_master.txt")))
        #Prompts.append(PromptPart(PromptType.FIXED_START, text=))
        Prompts.append(PromptPart(PromptType.CONTEXT_TEMPORARY, self.get_path("current_command.txt")))

        for prompt in Prompts:
            self.add_prompt_part(prompt)

    def prepare_fixed_messages(self) -> List[Dict]:
        messages = super().prepare_fixed_messages()
        current_instruction = settings.get("GM_SMALL_PROMPT", "")
        if current_instruction != "":
            small_prompt = {"role": "system", "content": f"[INSTRUCTION]: {current_instruction}"}
            messages.append(small_prompt)

        return messages


    def process_response(self, response: str):
        response = self.extract_and_process_memory_data(response)
        response = self._process_behavior_changes(response)

        return response

    def _process_behavior_changes(self, response):
        return response

    def add_context(self, messages):
        super().add_context(messages)

        logger.info("Особый контекст ГМ")
        for prompt in self.temp_prompts:
            messages.append({"role": "system", "content": str(prompt)})

        return messages

    def current_variables(self):
        return {
            "role": "system",
            "content": ""
        }

        # return {
        #     "role": "system",
        #     "content": (f"Твои характеристики:"
        #                 f"Отношение: {self.attitude}/100."
        #                 f"Скука: {self.boredom}/100."
        #                 f"Стресс: {self.stress}/100.")
        # }

    def current_variables_string(self) -> str:
        characteristics = {
            "Отношение": self.attitude,
            "Стресс": self.stress,
            "Скука": self.boredom,
        }
        return ""

        # return f"характеристики {self.name}:\n" + "\n".join(
        #     f"- {key}: {value} " for key, value in characteristics.items()
        # )
