import os
import json
import shutil
import datetime
from tkinter import messagebox
import logging

# Initialize logger
from Logger import logger

def list_prompt_sets(catalogue_path, character_name=None):
    """
    Returns a list of subdirectory names in catalogue_path,
    filtered by character_name if provided.
    """
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
        messagebox.showerror("Error", f"Error listing prompt sets: {e}")
        return []

def read_info_json(set_path):
    """
    Reads and returns the JSON data from info.json in set_path.
    """
    info_file_path = os.path.join(set_path, "info.json")
    try:
        with open(info_file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"info.json not found in {set_path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON in {info_file_path}: {e}")
        messagebox.showerror("Error", f"Error decoding JSON in info.json: {e}")
        return {}
    except Exception as e:
        logger.exception(f"Error reading info.json in {set_path}: {e}")
        messagebox.showerror("Error", f"Error reading info.json: {e}")
        return {}

def write_info_json(set_path, data):
    """
    Writes the JSON data to info.json in set_path.
    """
    info_file_path = os.path.join(set_path, "info.json")
    try:
        with open(info_file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.exception(f"Error writing info.json to {info_file_path}: {e}")
        messagebox.showerror("Error", f"Error writing info.json: {e}")
        return False

def copy_prompt_set(set_path, character_path):
    """
    Copies the contents of set_path to character_path.
    """
    try:
        shutil.copytree(set_path, character_path, dirs_exist_ok=True)
        return True
    except Exception as e:
        logger.exception(f"Error copying prompt set from {set_path} to {character_path}: {e}")
        messagebox.showerror("Error", f"Error copying prompt set: {e}")
        return False

def create_new_set(character_name, catalogue_path, prompts_path):
    """
    Creates a new set directory in catalogue_path with name character_name_YYYYMMDD_HHMMSS,
    copies the contents of the character's prompts_path to the new set, and creates a default info.json.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    new_set_name = f"{character_name}_{timestamp}"
    new_set_path = os.path.join(catalogue_path, new_set_name)
    try:
        shutil.copytree(prompts_path, new_set_path)
        # Create default info.json
        info_data = {
            "character": character_name,
            "author": "Unknown",
            "version": "1.0",
            "description": "A new prompt set.",
        }
        if write_info_json(new_set_path, info_data):
            return new_set_path
        else:
            # If writing info.json fails, remove the created directory
            shutil.rmtree(new_set_path)
            return None
    except Exception as e:
        logger.exception(f"Error creating new prompt set in {catalogue_path}: {e}")
        messagebox.showerror("Error", f"Error creating new prompt set: {e}")
        return None

def delete_prompt_set(set_path):
    """
    Deletes the directory at set_path after confirmation.
    """
    if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete the prompt set at {set_path}?"):
        try:
            shutil.rmtree(set_path)
            return True
        except Exception as e:
            logger.exception(f"Error deleting prompt set at {set_path}: {e}")
            messagebox.showerror("Error", f"Error deleting prompt set: {e}")
            return False
    else:
        return False

def get_prompt_set_name(character_prompts_path):
    """
    Reads info.json from character_prompts_path and returns the 'name' field,
    or the basename of the path if info.json is not found or doesn't contain the 'name' field.
    """
    info_file_path = os.path.join(character_prompts_path, "info.json")
    try:
        with open(info_file_path, "r", encoding="utf-8") as f:
            info = json.load(f)
        return info.get("name", os.path.basename(character_prompts_path))
    except FileNotFoundError:
        return os.path.basename(character_prompts_path)
    except json.JSONDecodeError:
        return os.path.basename(character_prompts_path)
    except Exception:
        return os.path.basename(character_prompts_path)