from __future__ import annotations

from ui.pages.main_page_registry import MAIN_PAGE_ORDER
from ui.pages.settings.section_access import migrate_legacy_section_settings
from ui.pages.settings.section_registry import get_settings_section_specs


class _Settings:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = dict(values)

    def get(self, key: str, default=None):
        return self.values.get(str(key), default)

    def set(self, key: str, value) -> None:
        self.values[str(key)] = value


def test_data_collection_is_the_settings_tab_after_updates() -> None:
    sections = get_settings_section_specs()
    section_keys = [spec.key for spec in sections]
    data_collection = next(spec for spec in sections if spec.key == "data_collection")

    assert section_keys[section_keys.index("updates") + 1] == "data_collection"
    assert data_collection.nav_label == ("Сбор данных", "Data Collection")
    assert "developer" not in section_keys
    assert "developer" not in MAIN_PAGE_ORDER


def test_data_collection_visibility_migrates_from_developer_section() -> None:
    settings = _Settings({"SECTION_DEVELOPER_ENABLED": True})

    migrate_legacy_section_settings(settings)

    assert settings.get("SECTION_DATA_COLLECTION_ENABLED") is True
def test_existing_data_collection_visibility_is_not_overwritten() -> None:
    settings = _Settings(
        {
            "SECTION_DEVELOPER_ENABLED": False,
            "SECTION_DATA_COLLECTION_ENABLED": True,
        }
    )

    migrate_legacy_section_settings(settings)

    assert settings.get("SECTION_DATA_COLLECTION_ENABLED") is True
