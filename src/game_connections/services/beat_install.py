from __future__ import annotations

from core.events import Events, get_event_bus
from core.install_types import InstallAction, InstallPlan
from game_connections.services.beat_backend_spec import (
    BACKEND_AUTO,
    BACKEND_BEAT_THIS,
    BACKEND_DSP,
    BACKEND_LIBROSA,
    backend_display_name,
    backend_install_packages,
    build_beat_ctx,
    get_backend_status_snapshot,
    normalize_backend_choice,
)
from game_connections.services.beat_worker_client import call_beats_worker_sync, restart_beats_worker
from handlers.voice_models.install_plan_helpers import pip_uninstall_action, torch_install_action
from utils import getTranslationVariant as _

def build_beat_install_plan(target_backend: str = BACKEND_BEAT_THIS, *, ctx: dict | None = None) -> InstallPlan:
    normalized = normalize_backend_choice(target_backend)
    beat_ctx = build_beat_ctx(ctx)
    status = get_backend_status_snapshot(normalized, ctx=beat_ctx)

    if normalized == BACKEND_DSP:
        return InstallPlan(
            actions=[],
            already_installed=True,
            already_installed_status=_("DSP fallback не требует установки", "DSP fallback does not require installation"),
        )

    backend_key = BACKEND_LIBROSA if normalized == BACKEND_LIBROSA else BACKEND_BEAT_THIS
    backend_state = status["backends"][backend_key]
    if backend_state.get("available"):
        return InstallPlan(
            actions=[],
            already_installed=True,
            already_installed_status=_("Уже установлено", "Already installed"),
        )

    actions: list[InstallAction] = []
    if backend_key == BACKEND_BEAT_THIS:
        actions.append(torch_install_action(beat_ctx, progress=10))

    packages = backend_install_packages(backend_key)
    actions.append(
        InstallAction(
            type="call",
            description=_(
                "Установка зависимостей beat sync...",
                "Installing beat sync dependencies...",
            ),
            progress=35 if backend_key == BACKEND_BEAT_THIS else 20,
            fn=lambda **kwargs: _install_backend_packages(packages, **kwargs),
        )
    )
    actions.append(
        InstallAction(
            type="call",
            description=_("Перезапуск beat backend...", "Restarting beat backend..."),
            progress=85,
            fn=_restart_beats_service,
        )
    )
    actions.append(
        InstallAction(
            type="call",
            description=_("Проверка зависимостей beat backend...", "Validating beat backend dependencies..."),
            progress=99,
            fn=lambda **_kwargs: _backend_installed(backend_key),
        )
    )
    return InstallPlan(actions=actions, ok_status=_("Готово", "Done"))



def build_beat_uninstall_plan(target_backend: str = BACKEND_BEAT_THIS, *, ctx: dict | None = None) -> InstallPlan:
    normalized = normalize_backend_choice(target_backend)
    if normalized != BACKEND_BEAT_THIS:
        return InstallPlan(
            actions=[],
            already_installed=True,
            already_installed_status=_("Для этого backend удаление не требуется", "Nothing to uninstall for this backend"),
        )

    actions = [
        pip_uninstall_action(
            ["beat-this", "rotary-embedding-torch", "einops", "tqdm"],
            description=_("Удаление beat-this...", "Uninstalling beat-this..."),
            progress=20,
        ),
        InstallAction(
            type="call",
            description=_("Перезапуск beat backend...", "Restarting beat backend..."),
            progress=85,
            fn=_restart_beats_service,
        ),
        InstallAction(
            type="call",
            description=_("Проверка удаления beat-this...", "Validating beat-this removal..."),
            progress=99,
            fn=lambda **_kwargs: not bool(
                get_backend_status_snapshot(BACKEND_BEAT_THIS, ctx=build_beat_ctx(ctx))["backends"][BACKEND_BEAT_THIS]["available"]
            ),
        ),
    ]
    return InstallPlan(actions=actions, ok_status=_("Удалено", "Uninstalled"))


def build_beat_initialize_plan(preferred_backend: str = BACKEND_AUTO) -> InstallPlan:
    normalized = normalize_backend_choice(preferred_backend)
    title_backend = backend_display_name(normalized)

    if normalized == BACKEND_DSP:
        return InstallPlan(
            actions=[],
            already_installed=True,
            already_installed_status=_("DSP fallback готов без инициализации", "DSP fallback is ready without initialization"),
        )

    actions = [
        InstallAction(
            type="call",
            description=_("Перезапуск beat backend...", "Restarting beat backend..."),
            progress=20,
            fn=_restart_beats_service,
        ),
        InstallAction(
            type="call",
            description=_(
                "Инициализация backend: {}...",
                "Initializing backend: {}...",
            ).format(title_backend),
            progress=70,
            fn=lambda **_kwargs: _initialize_beats_service(normalized),
        ),
        InstallAction(
            type="call",
            description=_("Проверка инициализации...", "Validating initialization..."),
            progress=99,
            fn=lambda **_kwargs: _backend_ready(normalized),
        ),
    ]
    return InstallPlan(actions=actions, ok_status=_("Готово", "Done"))


def make_install_runner(target_backend: str):
    normalized = normalize_backend_choice(target_backend)

    def _runner(*args, **kwargs):
        run_ctx = kwargs.get("ctx") if isinstance(kwargs, dict) else None
        return build_beat_install_plan(normalized, ctx=run_ctx if isinstance(run_ctx, dict) else None)

    return _runner


def make_uninstall_runner(target_backend: str):
    normalized = normalize_backend_choice(target_backend)

    def _runner(*args, **kwargs):
        run_ctx = kwargs.get("ctx") if isinstance(kwargs, dict) else None
        return build_beat_uninstall_plan(normalized, ctx=run_ctx if isinstance(run_ctx, dict) else None)

    return _runner


def make_initialize_runner(preferred_backend: str):
    normalized = normalize_backend_choice(preferred_backend)

    def _runner(*_args, **_kwargs):
        return build_beat_initialize_plan(normalized)

    return _runner


def start_beat_install(
    target_backend: str = BACKEND_BEAT_THIS,
    *,
    with_ui: bool = True,
    timeout_sec: float = 3600.0,
) -> None:
    normalized = normalize_backend_choice(target_backend)
    title = _("Установка Beat Sync backend", "Installing Beat Sync backend")
    if normalized == BACKEND_LIBROSA:
        title = _("Установка backend Librosa", "Installing Librosa backend")

    _emit_install_task(
        {
            "kind": "beats",
            "item_id": normalized,
            "task_id": f"beats:install:{normalized}",
            "title": title,
            "initial_status": _("Подготовка...", "Preparing..."),
            "timeout_sec": float(timeout_sec or 3600.0),
            "meta": {"kind": "beats", "item_id": normalized, "op": "install"},
            "runner": make_install_runner(normalized),
        },
        with_ui=with_ui,
    )


def start_beat_uninstall(
    target_backend: str = BACKEND_BEAT_THIS,
    *,
    with_ui: bool = True,
    timeout_sec: float = 3600.0,
) -> None:
    normalized = normalize_backend_choice(target_backend)
    _emit_install_task(
        {
            "kind": "beats",
            "item_id": normalized,
            "task_id": f"beats:uninstall:{normalized}",
            "title": _("Удаление beat-this backend", "Uninstalling beat-this backend"),
            "initial_status": _("Подготовка...", "Preparing..."),
            "timeout_sec": float(timeout_sec or 3600.0),
            "meta": {"kind": "beats", "item_id": normalized, "op": "uninstall"},
            "runner": make_uninstall_runner(normalized),
        },
        with_ui=with_ui,
    )


def start_beat_initialize(
    preferred_backend: str = BACKEND_AUTO,
    *,
    with_ui: bool = True,
    timeout_sec: float = 3600.0,
) -> None:
    normalized = normalize_backend_choice(preferred_backend)
    _emit_install_task(
        {
            "kind": "beats",
            "item_id": normalized,
            "task_id": f"beats:init:{normalized}",
            "title": _("Инициализация Beat Sync backend", "Initializing Beat Sync backend"),
            "initial_status": _("Подготовка...", "Preparing..."),
            "timeout_sec": float(timeout_sec or 3600.0),
            "meta": {"kind": "beats", "item_id": normalized, "op": "initialize"},
            "runner": make_initialize_runner(normalized),
        },
        with_ui=with_ui,
    )


def _emit_install_task(payload: dict, *, with_ui: bool) -> None:
    get_event_bus().emit(
        Events.Install.RUN_WITH_UI if with_ui else Events.Install.RUN_HEADLESS,
        payload,
    )


def _restart_beats_service(*_args, **kwargs) -> bool:
    ctx = kwargs.get("ctx") if isinstance(kwargs, dict) else None
    event_bus = ctx.get("event_bus") if isinstance(ctx, dict) else None
    return restart_beats_worker(timeout=15.0, event_bus=event_bus)


def _initialize_beats_service(preferred_backend: str) -> bool:
    return bool(
        call_beats_worker_sync(
            "initialize_backend",
            {
                "backend_preference": normalize_backend_choice(preferred_backend),
                "strict": True,
            },
            timeout=180.0,
        )
    )


def _install_backend_packages(packages: list[str], *, pip_installer=None, callbacks=None, **_kwargs) -> bool:
    if pip_installer is None:
        return False
    if not packages:
        return True
    try:
        if callbacks:
            callbacks.log("Installing packages: {}".format(", ".join(packages)))
        return bool(
            pip_installer.install_package(
                list(packages),
                description=_("Установка зависимостей beat sync...", "Installing beat sync dependencies..."),
                extra_args=["--upgrade"],
            )
        )
    except Exception as exc:
        try:
            if callbacks:
                callbacks.log(str(exc))
        except Exception:
            pass
        return False

def _backend_installed(preferred_backend: str) -> bool:
    payload = call_beats_worker_sync(
        "get_backend_status",
        {"backend_preference": normalize_backend_choice(preferred_backend)},
        timeout=5.0,
    )
    preferred = normalize_backend_choice(preferred_backend)
    target = payload.get("resolved_backend") if preferred == BACKEND_AUTO else preferred
    if target == BACKEND_DSP:
        return True
    backends = payload.get("backends") if isinstance(payload.get("backends"), dict) else {}
    backend_state = backends.get(target) if isinstance(backends, dict) else None
    if not isinstance(backend_state, dict):
        return False
    return bool(backend_state.get("installed") or backend_state.get("available"))

def _backend_ready(preferred_backend: str) -> bool:
    payload = call_beats_worker_sync(
        "get_backend_status",
        {"backend_preference": normalize_backend_choice(preferred_backend)},
        timeout=5.0,
    )
    preferred = normalize_backend_choice(preferred_backend)
    target = payload.get("resolved_backend") if preferred == BACKEND_AUTO else preferred
    if target == BACKEND_DSP:
        return True
    backends = payload.get("backends") if isinstance(payload.get("backends"), dict) else {}
    backend_state = backends.get(target) if isinstance(backends, dict) else None
    if not isinstance(backend_state, dict):
        return False
    return bool(backend_state.get("ready"))
