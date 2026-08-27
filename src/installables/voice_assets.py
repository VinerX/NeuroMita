"""AI Hub components for per-character voice assets (the ``Models/`` payload).

Each Mita voice is a downloadable bundle hosted on a low-profile GitHub
prerelease (see ``utils.voice_assets_installer``). They surface in the AI Hub
under the «Голоса Мит» category: install one Mita, or grab them all at once via
the aggregate ``voices:all`` card.

Voices are *assets*, not engines — a TTS engine (EdgeTTS+RVC / F5 / FishSpeech)
won't actually speak in a character's voice until the matching bundle is here.
"""

from __future__ import annotations

from typing import Any

from core.backends import BackendKind
from core.install_types import InstallAction, InstallPlan
from core.installables import (
    ComponentCategory,
    ComponentMetadata,
    ComponentStatus,
    ComponentStatusCode,
    make_component_id,
)
from core.installables.helpers import noop_plan
from utils import getTranslationVariant as _
from utils.voice_assets_installer import (
    bundle_cache_path,
    bundle_url,
    extract_bundle,
    fetch_remote_manifest,
    is_installed,
    is_update_available,
    record_installed_version,
    remote_entry,
    remove_assets,
)


def _manifest_from_ctx(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    """Единый манифест версий для status()/плана. force=True приходит при явном
    «Проверить обновления» (контроллер кладёт refresh в ctx) — минуем кэш."""
    force = bool((ctx or {}).get("refresh"))
    return fetch_remote_manifest(force=force)


# Manifest of shippable voices. ``short_name`` must match the file stem used by
# get_character_voice_paths and the ``<ShortName>.zip`` asset on the release.
# ``size`` is informational only. Prune/extend to match what's uploaded.
MITA_VOICES: tuple[dict[str, str], ...] = (
    {"short_name": "CrazyMita", "title": "Crazy Mita", "size": "~250 MB"},
    {"short_name": "MitaKind", "title": "Kind Mita", "size": "~230 MB"},
    {"short_name": "CappieMita", "title": "Cappie Mita", "size": "~250 MB"},
    {"short_name": "Mila", "title": "Mila", "size": "~230 MB"},
    {"short_name": "ShorthairMita", "title": "Shorthair Mita", "size": "~170 MB"},
    {"short_name": "SleepyMita", "title": "Sleepy Mita", "size": "~170 MB"},
    {"short_name": "GhostMita", "title": "Ghost Mita", "size": "~190 MB"},
)


def _log_from_ctx(ctx: dict[str, Any] | None):
    cb = (ctx or {}).get("callbacks")
    if cb is not None and hasattr(cb, "log"):
        return lambda msg: cb.log(msg)
    return lambda _msg: None


def _download_action(short_name: str, progress: int, progress_to: int) -> InstallAction:
    return InstallAction(
        type="download_http",
        description=_("Загрузка голоса: {name}...", "Downloading voice: {name}...").format(name=short_name),
        progress=progress,
        progress_to=progress_to,
        files=[{"url": bundle_url(short_name), "dest": str(bundle_cache_path(short_name))}],
    )


def _extract_action(short_name: str, progress: int, version: dict[str, Any] | None = None) -> InstallAction:
    def _extract(**kwargs) -> bool:
        log = _log_from_ctx(kwargs)
        zip_path = bundle_cache_path(short_name)
        ok = extract_bundle(zip_path, short_name, log)
        try:
            zip_path.unlink(missing_ok=True)
        except OSError:
            pass
        if ok:
            # Штампуем локальный маркер версии — по нему потом видно, что на диске
            # уже актуальный релиз (иначе он навсегда считался бы «обновляемым»).
            record_installed_version(short_name, version)
        return ok

    return InstallAction(
        type="call",
        description=_("Распаковка: {name}...", "Extracting: {name}...").format(name=short_name),
        progress=progress,
        fn=_extract,
    )


def _clean_action(short_name: str, progress: int = 4) -> InstallAction:
    """Drop a cached archive and any existing files so a clean reinstall really
    re-downloads (download_http otherwise skips an already-present archive)."""
    def _clean(**kwargs) -> bool:
        log = _log_from_ctx(kwargs)
        try:
            bundle_cache_path(short_name).unlink(missing_ok=True)
        except OSError:
            pass
        remove_assets(short_name, log)
        return True

    return InstallAction(
        type="call",
        description=_("Очистка перед переустановкой: {name}...", "Cleaning before reinstall: {name}...").format(name=short_name),
        progress=progress,
        fn=_clean,
    )


def _drop_cache_action(short_name: str, progress: int = 4) -> InstallAction:
    """Только удалить кэшированный архив (для обновления): файлы на диске трогать
    не надо — extract перезапишет их атомарно, а вот download_http иначе пропустит
    скачивание при совпадении имени уже лежащего .zip."""
    def _drop(**kwargs) -> bool:
        try:
            bundle_cache_path(short_name).unlink(missing_ok=True)
        except OSError:
            pass
        return True

    return InstallAction(
        type="call",
        description=_("Подготовка обновления: {name}...", "Preparing update: {name}...").format(name=short_name),
        progress=progress,
        fn=_drop,
    )


class VoiceAssetComponent:
    """A single character's voice bundle."""

    category = ComponentCategory.VOICES
    legacy_kind = "voices"

    def __init__(self, spec: dict[str, str]) -> None:
        self.spec = spec
        self.short_name = str(spec["short_name"])
        self.item_id = self.short_name
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=self.spec.get("title") or self.short_name,
            description=_(
                "Голосовая модель персонажа для локальной озвучки (RVC/F5). "
                "Нужна, чтобы движок озвучки говорил голосом этой Миты.",
                "Character voice model for local voiceover (RVC/F5). Required for "
                "the TTS engine to speak in this Mita's voice.",
            ),
            backend=BackendKind.NONE,  # plain asset — compatible with any backend
            legacy_kind=self.legacy_kind,
            tags=("voice", "rvc", "f5", self.short_name.lower()),
            size=self.spec.get("size", ""),
        )

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        installed = is_installed(self.short_name)
        manifest = _manifest_from_ctx(ctx) if installed else None
        update = installed and is_update_available(self.short_name, manifest)
        if installed:
            message = (
                _("Доступно обновление голоса.", "Voice update available.")
                if update
                else _("Голос установлен.", "Voice installed.")
            )
        else:
            message = _("Голос не установлен.", "Voice not installed.")
        return ComponentStatus(
            id=self.id,
            code=ComponentStatusCode.INSTALLED if installed else ComponentStatusCode.NOT_INSTALLED,
            installed=installed,
            ready=installed,
            message=message,
            backend=BackendKind.NONE,
            details={"update_available": bool(update)},
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        clean = bool((ctx or {}).get("clean"))
        manifest = _manifest_from_ctx(ctx)
        version = remote_entry(self.short_name, manifest)
        update = is_update_available(self.short_name, manifest)
        if is_installed(self.short_name) and not clean and not update:
            return InstallPlan(
                actions=[],
                already_installed=True,
                already_installed_status=_("Уже установлено", "Already installed"),
            )

        actions: list[InstallAction] = []
        if clean:
            actions.append(_clean_action(self.short_name))
        elif update:
            # Обновление ставим поверх — extract перезапишет файлы; чистим лишь кэш zip.
            actions.append(_drop_cache_action(self.short_name))
        actions.append(_download_action(self.short_name, progress=10, progress_to=85))
        actions.append(_extract_action(self.short_name, progress=90, version=version))
        return InstallPlan(actions=actions, ok_status=_("Готово", "Done"))

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        if not is_installed(self.short_name):
            return noop_plan(_("Голос не установлен.", "Voice not installed."))

        def _remove(**kwargs) -> bool:
            remove_assets(self.short_name, _log_from_ctx(kwargs))
            return True

        return InstallPlan(
            actions=[
                InstallAction(
                    type="call",
                    description=_("Удаление голоса: {name}...", "Removing voice: {name}...").format(name=self.short_name),
                    progress=50,
                    fn=_remove,
                )
            ],
            ok_status=_("Удалено", "Uninstalled"),
        )

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


class AllVoicesComponent:
    """Aggregate card: download (or remove) every voice in the manifest."""

    category = ComponentCategory.VOICES
    legacy_kind = "voices"

    def __init__(self, voices: tuple[dict[str, str], ...]) -> None:
        self._voices = voices
        self.item_id = "all"
        self.id = make_component_id(self.category, self.item_id)

    def metadata(self) -> ComponentMetadata:
        return ComponentMetadata(
            id=self.id,
            item_id=self.item_id,
            category=self.category,
            title=_("Все голоса Мит", "All Mita voices"),
            description=_(
                "Скачать голосовые модели всех персонажей разом. Уже установленные "
                "пропускаются.",
                "Download every character's voice model at once. Already installed "
                "voices are skipped.",
            ),
            backend=BackendKind.NONE,
            legacy_kind=self.legacy_kind,
            tags=("voice", "bundle", "all"),
            size=_("несколько ГБ", "several GB"),
        )

    def _names(self) -> list[str]:
        return [str(v["short_name"]) for v in self._voices]

    def status(self, ctx: dict[str, Any] | None = None) -> ComponentStatus:
        names = self._names()
        installed_n = sum(1 for n in names if is_installed(n))
        total = len(names)
        all_in = installed_n >= total and total > 0
        # Манифест тянем только если есть что обновлять (иначе лишний сетевой запрос).
        manifest = _manifest_from_ctx(ctx) if installed_n else None
        updates = sum(1 for n in names if is_update_available(n, manifest))
        if updates:
            message = _("Доступно обновлений: {u} (установлено {a} из {b}).",
                        "{u} update(s) available ({a} of {b} installed).").format(u=updates, a=installed_n, b=total)
        else:
            message = _("Установлено {a} из {b} голосов.", "{a} of {b} voices installed.").format(a=installed_n, b=total)
        return ComponentStatus(
            id=self.id,
            code=ComponentStatusCode.INSTALLED if all_in else ComponentStatusCode.NOT_INSTALLED,
            installed=all_in,
            ready=all_in,
            message=message,
            backend=BackendKind.NONE,
            details={"installed": installed_n, "total": total, "updates": updates,
                     "update_available": bool(updates)},
        )

    def build_install_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        clean = bool((ctx or {}).get("clean"))
        manifest = _manifest_from_ctx(ctx)
        # Ставим недостающие + обновляем устаревшие (при clean — все).
        pending = [
            n for n in self._names()
            if clean or not is_installed(n) or is_update_available(n, manifest)
        ]
        if not pending:
            return InstallPlan(
                actions=[],
                already_installed=True,
                already_installed_status=_("Все голоса уже установлены", "All voices already installed"),
            )

        actions: list[InstallAction] = []
        n = len(pending)
        for i, name in enumerate(pending):
            # Spread progress evenly across the pending voices.
            lo = int(i * 100 / n)
            mid = int((i + 0.8) * 100 / n)
            hi = int((i + 1) * 100 / n)
            version = remote_entry(name, manifest)
            if clean:
                actions.append(_clean_action(name, progress=max(1, lo)))
            elif is_installed(name) and is_update_available(name, manifest):
                actions.append(_drop_cache_action(name, progress=max(1, lo)))
            actions.append(_download_action(name, progress=max(1, lo), progress_to=max(2, mid)))
            actions.append(_extract_action(name, progress=max(3, hi), version=version))
        return InstallPlan(actions=actions, ok_status=_("Готово", "Done"))

    def build_uninstall_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan:
        names = [n for n in self._names() if is_installed(n)]
        if not names:
            return noop_plan(_("Голоса не установлены.", "No voices installed."))

        def _remove(**kwargs) -> bool:
            log = _log_from_ctx(kwargs)
            ok = True
            for name in names:
                if not remove_assets(name, log):
                    ok = False
            return ok

        return InstallPlan(
            actions=[
                InstallAction(
                    type="call",
                    description=_("Удаление всех голосов...", "Removing all voices..."),
                    progress=50,
                    fn=_remove,
                )
            ],
            ok_status=_("Удалено", "Uninstalled"),
        )

    def build_initialize_plan(self, ctx: dict[str, Any] | None = None) -> InstallPlan | None:
        return None


def create_voice_asset_installable_components() -> list[Any]:
    components: list[Any] = [AllVoicesComponent(MITA_VOICES)]
    components.extend(VoiceAssetComponent(spec) for spec in MITA_VOICES)
    return components
