# Implementation Plan: Prompt Catalogue System

This document outlines the implementation plan for the prompt catalogue system, as requested by the user.

## 1. Overview

The goal is to create a system that allows users to easily manage and switch between different prompt sets for their characters. This involves creating a new GUI section, implementing file system operations for copying and managing prompt sets, and providing a way to edit the metadata associated with each set.

## 2. Components

The system will consist of the following components:

*   **`utils/prompt_catalogue_manager.py`:** This file will contain the core logic for managing prompt sets, including functions for:
    *   Listing available prompt sets in `PromptsCatalogue`.
    *   Reading and writing the `info.json` file for each set.
    *   Copying prompt sets between `PromptsCatalogue` and the character's `Prompts` folder.
    *   Creating new prompt sets.
    *   Deleting prompt sets.
*   **`ui/settings/prompt_catalogue_settings.py`:** This file will contain the GUI elements for managing prompt sets, including:
    *   A combobox for selecting a prompt set.
    *   Buttons for creating, browsing to, and deleting sets.
    *   A GUI for editing the `info.json` metadata.
*   **`gui.py`:** This file will be modified to include the new settings section from `ui/settings/prompt_catalogue_settings.py`.
*   **`chat_model.py`:** This file will be updated to ensure that the `reload_character_data` function correctly reloads prompts after a new set is selected.

## 3. Implementation Steps

1.  **Create `utils/prompt_catalogue_manager.py`:**
    *   Implement functions for:
        *   `list_prompt_sets(catalogue_path)`: Returns a list of subdirectory names in `catalogue_path`.
        *   `read_info_json(set_path)`: Reads and returns the JSON data from `info.json` in `set_path`.
        *   `write_info_json(set_path, data)`: Writes the JSON data to `info.json` in `set_path`.
        *   `copy_prompt_set(set_path, character_path)`: Copies the contents of `set_path` to `character_path`.
        *   `create_new_set(character_name, catalogue_path, prompts_path)`: Creates a new set directory in `catalogue_path` with name `character_name_YYYYMMDD_HHMMSS`, copies the contents of the character's `prompts_path` to the new set, and creates a default `info.json`.
        *   `delete_prompt_set(set_path)`: Deletes the directory at `set_path` after confirmation.

2.  **Create `ui/settings/prompt_catalogue_settings.py`:**
    *   Implement the function `setup_prompt_catalogue_controls(self, parent)`:
        *   Create a `CollapsibleSection` for "Prompt Catalogue".
        *   Add a `Combobox` for selecting a prompt set, populated with data from `list_prompt_sets`.
        *   Add a "Create New Set" button that calls `create_new_set` and updates the combobox.
        *   Add a "Browse to Set Folder" button that calls `delete_prompt_set` and updates the combobox.
        *   Add a "Delete Set" button that calls `delete_prompt_set` (with confirmation) and updates the combobox.
        *   Add a GUI for editing the `info.json` data (Labels and Entry widgets for character, author, version, description, and a way to add/edit additional parameters).

3.  **Modify `gui.py`:**
    *   Import `setup_prompt_catalogue_controls` from `ui/settings/prompt_catalogue_settings.py`.
    *   Call `setup_prompt_catalogue_controls` in `setup_right_frame`.
    *   Implement the logic to:
        *   Call `copy_prompt_set` when a new set is selected in the combobox.
        *   Call `self.model.current_character.reload_character_data()` after copying.
        *   Load and display the `info.json` data in the GUI.

4.  **Update `chat_model.py`:**
    *   Verify that `self.model.current_character.reload_character_data()` correctly reloads prompts.

## 4. JSON Description File Format (`info.json`)

```json
{
  "character": "Character Name",
  "author": "Author Name",
  "version": "1.0",
  "description": "A brief description of the prompt set.",
  "additional_params": {
    "param1": "value1",
    "param2": "value2"
  }
}
```

## 5. Naming Conventions

*   New prompt set directories will be named: `character_name_YYYYMMDD_HHMMSS` (e.g., `Crazy_20250613_201530`).
*   The description file will be named `info.json`.

## 6. Error Handling

*   Implement proper error handling for file system operations (e.g., checking if directories exist, handling file access errors).
*   Use `messagebox` to display error messages to the user.
*   Log all errors using the `Logger` module.

## 7. User Interface Considerations

*   Use clear and concise labels for all GUI elements.
*   Provide tooltips for settings where necessary.
*   Use a consistent visual style throughout the GUI.
*   Implement confirmation dialogs for potentially destructive actions (e.g., deleting a prompt set).

## 8. Next Steps

1.  Create `utils/prompt_catalogue_manager.py` and implement the core file system functions.