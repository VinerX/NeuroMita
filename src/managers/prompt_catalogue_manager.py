import os
import json
import shutil
import datetime
from PyQt6.QtWidgets import QMessageBox

from main_logger import logger


_SPECIAL_FOLDERS = {"System", "Cartridges", "__pycache__"}


def list_prompt_sets(root_path, character_name=None):
    """
    Новый формат:
      Prompts/<char_id>/<set_name>/...

    - Если character_name задан:
        вернёт список set_name внутри Prompts/<char_id>
    - Иначе:
        вернёт список строк вида "<char_id>/<set_name>" по всем персонажам в root_path
    """
    try:
        if character_name:
            char_dir = os.path.join(root_path, character_name)
            if not os.path.isdir(char_dir):
                return []
            names = [
                d
                for d in os.listdir(char_dir)
                if os.path.isdir(os.path.join(char_dir, d))
            ]
            names = [d for d in names if d and not d.startswith(".") and d not in {"System", "__pycache__"}]
            return sorted(names)

        chars = [
            d
            for d in os.listdir(root_path)
            if os.path.isdir(os.path.join(root_path, d))
        ]
        chars = [c for c in chars if c and not c.startswith(".") and c not in _SPECIAL_FOLDERS]

        out = []
        for c in sorted(chars):
            cdir = os.path.join(root_path, c)
            sets = [
                s
                for s in os.listdir(cdir)
                if os.path.isdir(os.path.join(cdir, s))
            ]
            sets = [s for s in sets if s and not s.startswith(".") and s not in {"System", "__pycache__"}]
            for s in sorted(sets):
                out.append(f"{c}/{s}")
        return out

    except Exception as e:
        logger.exception(f"Error listing prompt sets in {root_path}: {e}")
        return []


def read_info_json(set_path):
    info_file_path = os.path.join(set_path, "info.json")
    try:
        with open(info_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        try:
            with open(info_file_path, "r", encoding="cp1251") as f:
                return json.load(f)
        except Exception:
            return {}
    except FileNotFoundError:
        logger.warning(f"info.json not found in {set_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON in {info_file_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error decoding JSON in info.json: {e}")
        return {}
    except Exception as e:
        logger.exception(f"Error reading info.json in {set_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error reading info.json: {e}")
        return {}


def write_info_json(set_path, data):
    info_file_path = os.path.join(set_path, "info.json")
    try:
        with open(info_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.exception(f"Error writing info.json to {info_file_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error writing info.json: {e}")
        return False


def copy_prompt_set(set_path: str, target_path: str, clean_target: bool = True) -> bool:
    try:
        if clean_target and os.path.exists(target_path):
            shutil.rmtree(target_path)
        shutil.copytree(set_path, target_path, dirs_exist_ok=True)
        return True
    except Exception as e:
        logger.exception(f"Error copying prompt set from {set_path} to {target_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error copying prompt set: {e}")
        return False


def create_new_set(character_name, root_path, source_path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    new_set_name = f"{timestamp}"
    new_set_path = os.path.join(root_path, character_name, new_set_name)
    try:
        os.makedirs(os.path.dirname(new_set_path), exist_ok=True)
        shutil.copytree(source_path, new_set_path)
        info_data = {
            "character": character_name,
            "author": "Unknown",
            "version": "1.0",
            "description": "A new prompt set.",
        }
        if write_info_json(new_set_path, info_data):
            return new_set_path
        shutil.rmtree(new_set_path)
        return None
    except Exception as e:
        logger.exception(f"Error creating new prompt set in {root_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error creating new prompt set: {e}")
        return None


def delete_prompt_set(set_path):
    reply = QMessageBox.question(
        None,
        "Confirm Delete",
        f"Are you sure you want to delete the prompt set at {set_path}?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    if reply == QMessageBox.StandardButton.Yes:
        try:
            shutil.rmtree(set_path)
            return True
        except Exception as e:
            logger.exception(f"Error deleting prompt set at {set_path}: {e}")
            QMessageBox.critical(None, "Error", f"Error deleting prompt set: {e}")
            return False
    return False


def get_prompt_catalogue_folder_name(character_prompts_path):
    info_file_path = os.path.join(character_prompts_path, "info.json")
    try:
        with open(info_file_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        return info.get("folder", os.path.basename(character_prompts_path))
    except UnicodeDecodeError:
        try:
            with open(info_file_path, "r", encoding="cp1251") as f:
                info = json.load(f)
            return info.get("folder", os.path.basename(character_prompts_path))
        except Exception:
            return os.path.basename(character_prompts_path)
    except Exception:
        return os.path.basename(character_prompts_path)