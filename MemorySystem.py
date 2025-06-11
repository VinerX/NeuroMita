import json
import logging
import os
import datetime


class MemorySystem:
    def __init__(self, character_name):
        self.history_dir = f"Histories\\{character_name}"
        os.makedirs(self.history_dir, exist_ok=True)

        self.filename = os.path.join(self.history_dir, f"{character_name}_memories.json")
        self.memories = []
        self.total_characters = 0  # Новый атрибут для подсчета символов
        self.last_memory_number = 1

        self.load_memories()

    def load_memories(self):

        if os.path.exists(self.filename):
            with open(self.filename, 'r', encoding='utf-8') as file:
                self.memories = json.load(file)
                self.last_memory_number = len(self.memories) + 1
                self._calculate_total_characters()
        else:
            logging.warning(f"No memories file {self.filename} found!")
            self.memories = []
            self.save_memories() # Создаем пустой файл
            logging.info(f"Created new memories file: {self.filename}")

    def _calculate_total_characters(self):
        """Пересчитывает общее количество символов"""
        self.total_characters = sum(len(memory["content"]) for memory in self.memories)

    def save_memories(self):
        with open(self.filename, 'w', encoding='utf-8') as file:
            json.dump(self.memories, file, ensure_ascii=False, indent=4)

    def add_memory(self, content, date=datetime.datetime.now().strftime("%d.%m.%Y_%H.%M"), priority="Normal"):
        if not self.memories:
            new_id = 1
        else:
            new_id = max(memory['N'] for memory in self.memories) + 1

        memory = {
            "N": new_id,
            "date": date,
            "priority": priority,
            "content": content
        }
        self.memories.append(memory)
        self.total_characters += len(content)  # Обновляем счетчик
        self.last_memory_number += 1
        self.save_memories()

    def update_memory(self, number, content, priority=None):
        for memory in self.memories:
            if memory["N"] == number:
                # Обновляем счетчик символов
                self.total_characters -= len(memory["content"])
                self.total_characters += len(content)

                memory["date"] = datetime.datetime.now().strftime("%d.%m.%Y_%H.%M")
                memory["content"] = content
                if priority:
                    memory["priority"] = priority
                self.save_memories()
                return True
        return False

    def delete_memory(self, number):
        for i, memory in enumerate(self.memories):
            if memory["N"] == number:
                self.total_characters -= len(memory["content"])  # Обновляем счетчик
                del self.memories[i]
                self.save_memories()
                return True
        return False

    def clear_memories(self):
        self.memories = []
        self.total_characters = 0  # Сбрасываем счетчик
        self.save_memories()
        self.last_memory_number = 1

    def get_memories_formatted(self):
        formatted_memories = []
        for memory in self.memories:
            formatted_memories.append(
                f"N:{memory['N']}, Date {memory['date']}, Priority: {memory['priority']}: {memory['content']}"
            )

        memory_stats = f"\nMemory status: {len(self.memories)} facts, {self.total_characters} characters"

        # Правила для управления памятью
        management_tips = []
        if self.total_characters > 10000:
            management_tips.append("CRITICAL: Memory limit exceeded! Delete old or useless memories immediately!")
        elif self.total_characters > 5000:
            management_tips.append("WARNING: Memory size is large. Consider optimization or summarization")

        if len(self.memories) > 75:
            management_tips.append("Too many memories! Delete unimportant ones using <-memory>N</memory> syntax")
        elif len(self.memories) > 40:
            management_tips.append("Many memories stored. Review lower priority entries")

        # Примеры команд
        examples = [
            "Example of memory commands:",
            "<-memory>2</memory> - delete memory 2",
            "<+memory>high|new content</memory> - add memory with priority high",
            "<#memory>4|low|content</memory> - change memory 4 to content with priority low"
        ]

        full_message = (
                "LongMemory< " +
                "\n".join(formatted_memories) +
                " >EndLongMemory\n" +
                memory_stats + "\n" +
                "\n".join(management_tips) + "\n" +
                "\n".join(examples)
        )

        return full_message
