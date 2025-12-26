import os
import json
import shutil
import datetime
from PyQt6.QtWidgets import QMessageBox
import logging

from main_logger import logger

def list_prompt_sets(catalogue_path, character_name=None):
    try:
        all_sets = [d for d in os.listdir(catalogue_path) if os.path.isdir(os.path.join(catalogue_path, d))]
        if character_name:
            character_sets = [d for d in all_sets if d.__contains__(character_name)]
            if character_sets:
                return character_sets
            else:
                return []
        else:
            return all_sets
    except Exception as e:
        logger.exception(f"Error listing prompt sets in {catalogue_path}: {e}")
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

def copy_prompt_set(set_path: str, character_path: str, clean_target: bool = True) -> bool:
    try:
        set_config = os.path.join(set_path, "config.json")
        target_config = os.path.join(character_path, "config.json")
        preserve_config = clean_target and (not os.path.exists(set_config)) and os.path.exists(target_config)

        tmp_config = None
        if preserve_config:
            try:
                import tempfile
                fd, tmp_config = tempfile.mkstemp(prefix="nm_cfg_backup_", suffix=".json")
                os.close(fd)
                shutil.copy2(target_config, tmp_config)
                logger.info(f"Preserving existing config.json for '{character_path}' (no config.json in set).")
            except Exception as e:
                logger.warning(f"Failed to back up existing config.json at {target_config}: {e}")
                tmp_config = None

        if clean_target and os.path.exists(character_path):
            shutil.rmtree(character_path)

        shutil.copytree(set_path, character_path, dirs_exist_ok=True)

        if preserve_config and tmp_config and not os.path.exists(os.path.join(character_path, "config.json")):
            try:
                shutil.copy2(tmp_config, os.path.join(character_path, "config.json"))
                logger.info(f"Restored preserved config.json into '{character_path}'.")
            except Exception as e:
                logger.warning(f"Failed to restore preserved config.json to {character_path}: {e}")

        return True
    except Exception as e:
        logger.exception(f"Error copying prompt set from {set_path} to {character_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error copying prompt set: {e}")
        return False
    finally:
        try:
            if 'tmp_config' in locals() and tmp_config and os.path.exists(tmp_config):
                os.remove(tmp_config)
        except Exception:
            pass

def create_new_set(character_name, catalogue_path, prompts_path):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    new_set_name = f"{character_name}_{timestamp}"
    new_set_path = os.path.join(catalogue_path, new_set_name)
    try:
        shutil.copytree(prompts_path, new_set_path)
        info_data = {
            "character": character_name,
            "folder": new_set_name,
            "author": "Unknown",
            "version": "1.0",
            "description": "A new prompt set.",
        }
        if write_info_json(new_set_path, info_data):
            return new_set_path
        else:
            shutil.rmtree(new_set_path)
            return None
    except Exception as e:
        logger.exception(f"Error creating new prompt set in {catalogue_path}: {e}")
        QMessageBox.critical(None, "Error", f"Error creating new prompt set: {e}")
        return None

def delete_prompt_set(set_path):
    reply = QMessageBox.question(None, "Confirm Delete", f"Are you sure you want to delete the prompt set at {set_path}?",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply == QMessageBox.StandardButton.Yes:
        try:
            shutil.rmtree(set_path)
            return True
        except Exception as e:
            logger.exception(f"Error deleting prompt set at {set_path}: {e}")
            QMessageBox.critical(None, "Error", f"Error deleting prompt set: {e}")
            return False
    else:
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
    except FileNotFoundError:
        return os.path.basename(character_prompts_path)
    except json.JSONDecodeError:
        return os.path.basename(character_prompts_path)
    except Exception:
        return os.path.basename(character_prompts_path)