import numpy as np
import time
import os
import json
import re
from typing import List, Dict, Tuple, Optional, Any

from utils.embedding_handler import EmbeddingModelHandler

EMBEDDINGS_FILE = "mita_commands_embeddings_full.json"
CATEGORY_SWITCH_THRESHOLD_DIFF = 0.18
MIN_SIMILARITY_THRESHOLD = 0.40
TOP_N_CANDIDATES = 5
IGNORED_TAGS = {'p'}
TAG_TO_CATEGORY_MAP = {
    'c': 'commands', 'a': 'animations', 'e': 'emotions', 'f': 'face_params',
    'm': 'movement_modes', 'v': 'visual_effects', 'clothes': 'clothes',
    'music': 'music', 'interaction': 'interactions'
}
CATEGORY_TO_TAG_MAP = {v: k for k, v in TAG_TO_CATEGORY_MAP.items()}

class CommandParser:
    def __init__(self, model_handler: EmbeddingModelHandler, embeddings_path: str = EMBEDDINGS_FILE):
        self.model_handler = model_handler
        self.embeddings_data = self._load_embeddings(embeddings_path)
        self.all_canonical_items = self._prepare_all_items()
        print(f"\nCommandParser инициализирован. Загружено {len(self.all_canonical_items)} канонических команд.")

    def _load_embeddings(self, embeddings_path: str) -> Dict[str, List[Dict[str, Any]]]:
        print(f"Загрузка эмбеддингов из файла: {embeddings_path}")
        if not os.path.exists(embeddings_path):
             raise FileNotFoundError(f"Файл с эмбеддингами не найден: {embeddings_path}")
        try:
            with open(embeddings_path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)

            processed_data = {}
            model_dim = self.model_handler.hidden_size
            for category, items in loaded_data.items():
                processed_items = []
                if not items:
                    processed_data[category] = processed_items
                    continue
                for item in items:
                    if 'embedding' in item and isinstance(item['embedding'], list):
                         if len(item['embedding']) == model_dim:
                             item['embedding'] = np.array(item['embedding'], dtype=np.float32)
                             processed_items.append(item)
                         else:
                             print(f"  Предупреждение: Неверная размерность эмбеддинга ({len(item['embedding'])}, ожидалось {model_dim}) для '{item.get('name', 'N/A')}' в категории '{category}'. Пропущено.")
                    else:
                         print(f"  Предупреждение: Отсутствует или неверный формат эмбеддинга для '{item.get('name', 'N/A')}' в категории '{category}'. Пропущено.")
                processed_data[category] = processed_items
            print(f"Эмбеддинги успешно загружены и обработаны.")
            return processed_data
        except Exception as e:
            print(f"Ошибка при загрузке или обработке файла эмбеддингов: {e}")
            raise e

    def _prepare_all_items(self) -> List[Dict[str, Any]]:
        all_items = []
        for category, items in self.embeddings_data.items():
            for item in items:
                item_copy = item.copy()
                item_copy['category'] = category
                all_items.append(item_copy)
        return all_items

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        if vec1.shape != vec2.shape or vec1.ndim != 1:
             return -1.0
        return np.dot(vec1, vec2)

    def _find_best_match(self, input_embedding: np.ndarray, original_category: Optional[str], 
                         min_threshold: float = MIN_SIMILARITY_THRESHOLD, 
                         category_threshold: float = CATEGORY_SWITCH_THRESHOLD_DIFF) -> Tuple[Optional[Dict[str, Any]], Optional[str], float, List[Tuple[float, str, str]]]:
        if input_embedding is None:
            return None, None, -1.0, []

        best_overall_score = -1.0
        best_overall_item = None
        best_overall_category = None
        best_in_category_score = -1.0
        best_in_category_item = None
        all_scores = []

        for item in self.all_canonical_items:
            if 'embedding' not in item or not isinstance(item['embedding'], np.ndarray):
                continue
            if item['embedding'].shape != input_embedding.shape:
                 continue
            similarity = self._cosine_similarity(input_embedding, item['embedding'])
            if np.isnan(similarity): continue
            all_scores.append((similarity, item['name'], item['category']))

            if similarity > best_overall_score:
                best_overall_score = similarity
                best_overall_item = item
                best_overall_category = item['category']

            if original_category and item['category'] == original_category:
                if similarity > best_in_category_score:
                    best_in_category_score = similarity
                    best_in_category_item = item

        all_scores.sort(key=lambda x: x[0], reverse=True)
        top_candidates = all_scores[:TOP_N_CANDIDATES]

        chosen_item = None
        chosen_category = None
        chosen_score = -1.0

        if best_overall_item is None:
             print("  Предупреждение: Не найдено ни одного валидного совпадения.")
             return None, None, -1.0, top_candidates

        if best_overall_score < min_threshold:
             print(f"  Информация: Лучшее общее сходство ({best_overall_score:.4f}) ниже порога ({min_threshold}). Замена не будет выполнена.")
             return None, None, best_overall_score, top_candidates

        if original_category is None or best_in_category_item is None or best_in_category_score < min_threshold:
            chosen_item = best_overall_item
            chosen_category = best_overall_category
            chosen_score = best_overall_score
            print(f"  Информация: Исходная категория не определена или лучший результат в ней ниже порога. Выбран лучший общий: '{chosen_item['name']}' ({chosen_category}, {chosen_score:.4f})")
        else:
            score_diff = best_overall_score - best_in_category_score
            if best_overall_category != original_category and score_diff >= category_threshold:
                chosen_item = best_overall_item
                chosen_category = best_overall_category
                chosen_score = best_overall_score
                print(f"  Информация: Лучший общий результат из ДРУГОЙ категории ('{chosen_item['name']}' [{chosen_category}], {chosen_score:.4f}) "
                      f"значительно лучше лучшего в исходной ('{best_in_category_item['name']}' [{original_category}], {best_in_category_score:.4f}), разница {score_diff:.4f}. Категория изменена.")
            else:
                chosen_item = best_in_category_item
                chosen_category = original_category
                chosen_score = best_in_category_score
                print(f"  Информация: Выбран лучший результат из исходной категории '{original_category}': '{chosen_item['name']}' ({chosen_score:.4f})")

        if chosen_score < min_threshold:
             print(f"  Информация: Выбранный результат '{chosen_item['name']}' ({chosen_score:.4f}) ниже порога ({min_threshold}). Замена не будет выполнена.")
             return None, None, chosen_score, top_candidates

        return chosen_item, chosen_category, chosen_score, top_candidates

    def _parse_tags(self, text: str) -> List[Dict[str, Any]]:
        known_tags = list(TAG_TO_CATEGORY_MAP.keys())
        for cat in self.embeddings_data.keys():
            if cat not in TAG_TO_CATEGORY_MAP.values() and cat not in known_tags:
                known_tags.append(cat)

        pattern = r"<({tag_names})>(.*?)</\1>".format(tag_names="|".join(re.escape(tag) for tag in known_tags))

        found_tags = []
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            tag_name = match.group(1).lower()
            if tag_name in IGNORED_TAGS:
                continue

            content = match.group(2)
            start, end = match.span()
            original_category = TAG_TO_CATEGORY_MAP.get(tag_name)
            if original_category is None and tag_name in self.embeddings_data:
                 original_category = tag_name

            found_tags.append({
                "tag_name": tag_name,
                "content": content,
                "start": start,
                "end": end,
                "original_category": original_category,
                "full_match": match.group(0)
            })
        return found_tags

    def parse_and_replace(self, text: str, 
                          min_similarity_threshold: float = MIN_SIMILARITY_THRESHOLD,
                          category_switch_threshold: float = CATEGORY_SWITCH_THRESHOLD_DIFF,
                          skip_comma_params: bool = True,
                          top_candidates_count: int = TOP_N_CANDIDATES) -> Tuple[str, List[Dict[str, Any]]]:
        replacements_report = []
        modified_text = text

        tags_to_process = self._parse_tags(text)

        for tag_info in sorted(tags_to_process, key=lambda x: x['start'], reverse=True):
            tag_name = tag_info['tag_name']
            content = tag_info['content']
            original_category = tag_info['original_category']
            start = tag_info['start']
            end = tag_info['end']
            full_match = tag_info['full_match']

            print(f"\nОбработка тега: <{tag_name}>, Содержимое: '{content}'")

            if skip_comma_params and ',' in content:
                print(f"  Информация: Содержимое тега содержит запятую. Пропускаем замену для '{full_match}'.")
                replacements_report.append({
                    "original_tag": tag_name,
                    "original_content": content,
                    "skipped_reason": "Contains comma (likely parameters)",
                    "chosen_item": None, "chosen_tag": None, "score": None, "top_candidates": [], "needs_param": None
                })
                continue

            if not original_category:
                 print(f"  Предупреждение: Неизвестная категория для тега <{tag_name}>. Пропускаем.")
                 replacements_report.append({
                    "original_tag": tag_name, "original_content": content,
                    "skipped_reason": f"Unknown category for tag <{tag_name}>",
                    "chosen_item": None, "chosen_tag": None, "score": None, "top_candidates": [], "needs_param": None
                 })
                 continue
            if not content.strip():
                 print(f"  Информация: Пустое содержимое тега <{tag_name}>. Пропускаем.")
                 replacements_report.append({
                    "original_tag": tag_name, "original_content": content,
                    "skipped_reason": f"Empty content for tag <{tag_name}>",
                    "chosen_item": None, "chosen_tag": None, "score": None, "top_candidates": [], "needs_param": None
                 })
                 continue

            input_embedding = self.model_handler.get_embedding(content)
            if input_embedding is None:
                print(f"  Ошибка: Не удалось получить эмбеддинг для '{content}'. Пропускаем тег.")
                replacements_report.append({
                    "original_tag": tag_name, "original_content": content,
                    "skipped_reason": f"Failed to get embedding for '{content}'",
                    "chosen_item": None, "chosen_tag": None, "score": None, "top_candidates": [], "needs_param": None
                 })
                continue

            best_item, best_category, best_score, top_candidates = self._find_best_match(
                input_embedding, original_category, min_similarity_threshold, category_switch_threshold)

            report_entry = {
                "original_tag": tag_name,
                "original_content": content,
                "chosen_item": None,
                "chosen_tag": None,
                "score": float(best_score) if best_score is not None else None,
                "top_candidates": [(f"{float(s):.4f}", n, c) for s, n, c in top_candidates[:top_candidates_count]],
                "needs_param": None,
                "skipped_reason": None
            }

            if best_item and best_category:
                item_needs_param = best_item.get("needs_param", False)
                report_entry["needs_param"] = item_needs_param

                if not item_needs_param:
                    canonical_name = best_item['name']
                    new_tag_name = CATEGORY_TO_TAG_MAP.get(best_category, best_category)
                    replacement_str = f"<{new_tag_name}>{canonical_name}</{new_tag_name}>"
                    print(f"  ЗАМЕНА: '{full_match}' -> '{replacement_str}' (Сходство: {best_score:.4f})")

                    modified_text = modified_text[:start] + replacement_str + modified_text[end:]

                    report_entry["chosen_item"] = canonical_name
                    report_entry["chosen_tag"] = new_tag_name
                else:
                    print(f"  ЗАМЕНА НЕ ВЫПОЛНЕНА для '{full_match}'. Лучший кандидат '{best_item['name']}' требует параметры (needs_param=True). Сходство: {best_score:.4f}")
                    report_entry["skipped_reason"] = f"Best match '{best_item['name']}' requires parameters (needs_param=True)"
                    report_entry["chosen_item"] = best_item['name']
                    report_entry["chosen_tag"] = CATEGORY_TO_TAG_MAP.get(best_category, best_category)
            else:
                 print(f"  ЗАМЕНА НЕ ВЫПОЛНЕНА для '{full_match}'. Лучшее сходство: {best_score:.4f} (ниже порога или не найдено).")
                 report_entry["skipped_reason"] = f"Best similarity {best_score:.4f} below threshold or no match found"

            replacements_report.append(report_entry)

        return modified_text, list(reversed(replacements_report))

if __name__ == "__main__":
    try:
        model_handler = EmbeddingModelHandler()
        parser = CommandParser(model_handler=model_handler)
    except Exception as e:
        print(f"Не удалось инициализировать CommandParser: {e}")
        exit()

    input_text = "Crazy: <p>-4,0,5</p> Ты хочешь, чтобы я говорила по-русски? <e>discontent</e> Ладно, так и быть. <c>Сесть на угловой диван справа</c> Теперь я здесь, но не думай, что это меня развлекает."
    input_text_2 = "Я хочу <c>подойди ко мне</c> и потом <a>Помахай рукой</a>. И еще <music>Веселая Музыка</music>."
    input_text_3 = "Какой ужас! <e>fear</e> <v>Кровь,3.5</v>"
    input_text_4 = "<c>walk to Hall Sofa</c>"
    input_text_5 = "<c>Телепортироваться к, Hall Sofa</c>"
    input_text_6 = "<a>Какой-то бред сивой кобылы</a>"

    tests = [input_text, input_text_2, input_text_3, input_text_4, input_text_5, input_text_6]

    for i, text_to_test in enumerate(tests):
        print(f"\n--- Тест {i+1} ---")
        print(f"Исходный текст: {text_to_test}")
        modified_text, report = parser.parse_and_replace(
            text_to_test,
            min_similarity_threshold=0.45,  # Пример изменения порога сходства
            category_switch_threshold=0.2,  # Пример изменения порога для переключения категории
            skip_comma_params=True          # Пример опции для обработки тегов с запятыми
        )
        print("\nИтоговый текст:")
        print(modified_text)
        print("\nОтчет о заменах:")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("-" * 20)