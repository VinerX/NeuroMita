from __future__ import annotations

from typing import Any

from controllers.gui.intent_view_model import IntentViewModel
from ui.settings.finetune_data_presentation import (
    ClearFineTuneData,
    EnforceFineTuneLimit,
    FineTuneDataMessage,
    FineTuneDataState,
    RefreshFineTuneData,
    SetFineTuneDirectory,
)
from utils import getTranslationVariant as _


class FineTuneDataViewModel(IntentViewModel[FineTuneDataState]):
    def __init__(self, *, finetune, parent=None) -> None:
        super().__init__(FineTuneDataState(), parent)
        self._finetune = finetune

    def export_available(self) -> bool:
        return bool(self._finetune.available())

    def export_stats(self) -> dict[str, Any]:
        return dict(self._finetune.get_stats() or {}) if self.export_available() else {}

    def export_samples(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.export_available():
            return []
        return list(self._finetune.load_samples(dict(filters)) or [])

    def export_to_file(
        self,
        samples: list[dict[str, Any]],
        path: str,
        *,
        sharegpt: bool,
    ) -> int:
        if sharegpt:
            return int(self._finetune.export_sharegpt(list(samples), str(path)))
        return int(self._finetune.export_raw_jsonl(list(samples), str(path)))

    def dispatch(self, intent: Any) -> None:
        if isinstance(intent, RefreshFineTuneData):
            self.refresh()
            return
        if isinstance(intent, ClearFineTuneData):
            self.clear_all()
            return
        if isinstance(intent, EnforceFineTuneLimit):
            self.run_exclusive(
                "finetune-enforce-limit",
                self._finetune.enforce_limit,
                lambda _result: self.refresh(),
                lambda error: self.update_state(error=str(error)),
            )
            return
        if isinstance(intent, SetFineTuneDirectory):
            directory = str(intent.directory or "").strip()
            if directory:
                self._finetune.set_data_directory(directory)
                self.refresh()

    def refresh(self) -> None:
        if not self.state.loading:
            self.update_state(loading=True, error=None)

        def worker() -> dict[str, Any]:
            if not self._finetune.available():
                return {"available": False, "stats": {}}
            return {
                "available": True,
                "stats": dict(self._finetune.get_stats() or {}),
            }

        self.run_coalesced(
            "finetune-data-refresh",
            worker,
            self._apply_stats,
            lambda error: self.update_state(loading=False, error=str(error)),
        )

    def clear_all(self) -> None:
        self.update_state(loading=True, error=None)

        def applied(count: int) -> None:
            self.emit_effect(
                FineTuneDataMessage(
                    _("Готово", "Done"),
                    _("Удалено файлов: ", "Files deleted: ") + str(count),
                )
            )
            self.refresh()

        self.run_exclusive(
            "finetune-data-clear",
            lambda: int(self._finetune.clear_all()) if self._finetune.available() else 0,
            applied,
            lambda error: self._clear_failed(error),
        )

    def _apply_stats(self, payload: dict[str, Any]) -> None:
        if not payload.get("available"):
            lines = (_("Сборщик не инициализирован", "Collector not initialized"),)
            total = 0
        else:
            stats = dict(payload.get("stats") or {})
            total = int(stats.get("total", 0) or 0)
            rated = int(stats.get("rated", 0) or 0)
            positive = int(stats.get("positive", 0) or 0)
            negative = int(stats.get("negative", 0) or 0)
            built = [
                _("Всего записей: ", "Total records: ") + str(total),
                _("С рейтингом: ", "Rated: ")
                + f"{rated}  (👍 {positive} / 👎 {negative})",
            ]
            by_character = stats.get("by_character") or {}
            if isinstance(by_character, dict) and by_character:
                built.append(_("По персонажам:", "By character:"))
                for character_id, count in sorted(by_character.items()):
                    built.append(f"   {character_id}: {count}")
            lines = tuple(built)
        self.update_state(
            statistics_lines=tuple(lines),
            total_records=total,
            loading=False,
            error=None,
            revision=self.state.revision + 1,
        )

    def _clear_failed(self, error: Exception) -> None:
        self.update_state(loading=False, error=str(error))
        self.emit_effect(
            FineTuneDataMessage(
                _("Ошибка", "Error"),
                str(error),
                error=True,
            )
        )