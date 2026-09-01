from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping


CONTOUR_SETTING = "UPDATE_CONTOUR"
TEST_CONTOUR = "test"
RELEASE_CONTOUR = "release"
DISTRIBUTION_FILE_NAME = "distribution.json"
DISTRIBUTION_SCHEMA = 1

# Последний общий stable до разделения контуров. Версии Atm4x после этой
# границы считаются тестовыми ТОЛЬКО при наличии внешнего updater-state,
# подтверждающего, что установка действительно обновлялась из Atm4x.
LEGACY_LAST_SHARED_STABLE_VERSION = "2026.07.22"


@dataclass(frozen=True, slots=True)
class UpdateTarget:
    contour: str
    repo: str
    channel: str


@dataclass(frozen=True, slots=True)
class ContourMigration:
    contour: str
    reason: str
    changed: bool


_TARGETS = {
    TEST_CONTOUR: UpdateTarget(TEST_CONTOUR, "Atm4x/NeuroMita", "stable"),
    RELEASE_CONTOUR: UpdateTarget(RELEASE_CONTOUR, "VinerX/NeuroMita", "stable"),
}


def normalize_contour(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold()
    return normalized if normalized in _TARGETS else None


def target_for_contour(value: Any) -> UpdateTarget:
    # Без маркера безопасный дефолт — пользовательский stable-контур.
    return _TARGETS[normalize_contour(value) or RELEASE_CONTOUR]


def parse_version(value: Any) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", str(value or "")))


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            value = json.load(source)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def distribution_metadata_path(config_path: str | None) -> Path | None:
    """Return Settings/distribution.json for the active settings file.

    ``config_path`` points to the user's Settings/settings.json.  The
    distribution marker deliberately lives next to it, but it is *not* a user
    preference: it only tells a fresh installation which contour produced the
    package.  Once UPDATE_CONTOUR has been persisted in settings.json, that
    user value always wins over this file.
    """
    if not config_path:
        return None
    return Path(config_path).expanduser().resolve().parent / DISTRIBUTION_FILE_NAME


def read_distribution_metadata(config_path: str | None) -> dict[str, Any]:
    path = distribution_metadata_path(config_path)
    if path is None:
        return {}
    return _read_json(path)


def _infer_from_distribution(config_path: str | None) -> tuple[str | None, str]:
    metadata = read_distribution_metadata(config_path)
    if not metadata:
        return None, ""

    # Unknown future schemas must not silently change update routing.  Schema
    # may be omitted only for a short-lived hand-authored migration marker.
    schema = metadata.get("schema", DISTRIBUTION_SCHEMA)
    try:
        schema = int(schema)
    except (TypeError, ValueError):
        return None, ""
    if schema != DISTRIBUTION_SCHEMA:
        return None, ""

    contour = normalize_contour(metadata.get("contour"))
    if contour:
        return contour, "distribution-marker"
    return None, ""


def _legacy_journal_candidates(config_path: str | None) -> tuple[Path, ...]:
    """Known pre-contour updater journals.

    The state is external to the pyz and therefore can be used as a one-time
    migration hint without making the promoted Python artifact identify itself
    as test/release from its embedded version.
    """
    if not config_path:
        return ()

    settings_file = Path(config_path).expanduser().resolve()
    settings_dir = settings_file.parent
    install_dir = settings_dir.parent
    return (
        install_dir.parent / f".{install_dir.name}.update-state" / "python" / "operation.json",
        install_dir / "_update_state" / "python" / "operation.json",
    )


def _infer_from_legacy_journal(config_path: str | None) -> tuple[str | None, str]:
    cutoff = parse_version(LEGACY_LAST_SHARED_STABLE_VERSION)
    for candidate in _legacy_journal_candidates(config_path):
        state = _read_json(candidate)
        if not state:
            continue

        url = str(state.get("archive_url") or "").casefold()
        version = parse_version(state.get("version"))

        if "vinerx/neuromita" in url:
            return RELEASE_CONTOUR, "legacy-vinerx-journal"
        if "atm4x/neuromita" in url and version and version > cutoff:
            return TEST_CONTOUR, "legacy-atm4x-version"

    return None, ""


def infer_initial_contour(
    settings: Mapping[str, Any],
    *,
    config_path: str | None = None,
) -> tuple[str, str]:
    """Resolve contour for an installation that has no persisted contour yet.

    Priority is intentional:
      1. explicit user state (normally handled by migrate_update_contour);
      2. Settings/distribution.json from the package;
      3. pre-contour updater/settings hints;
      4. safe stable default.
    """
    explicit = normalize_contour(settings.get(CONTOUR_SETTING))
    if explicit:
        return explicit, "explicit"

    distribution_contour, reason = _infer_from_distribution(config_path)
    if distribution_contour:
        return distribution_contour, reason

    journal_contour, reason = _infer_from_legacy_journal(config_path)
    if journal_contour:
        return journal_contour, reason

    legacy_repo = str(settings.get("UPDATE_REPO") or "").strip().casefold()
    legacy_channel = str(settings.get("UPDATE_CHANNEL") or "").strip().casefold()
    tester_code = str(settings.get("TESTER_CODE") or "").strip()

    if "vinerx/neuromita" in legacy_repo:
        return RELEASE_CONTOUR, "legacy-vinerx-repo"
    if legacy_channel in {"beta", "test", "prerelease"}:
        return TEST_CONTOUR, "legacy-beta-channel"
    if tester_code:
        return TEST_CONTOUR, "legacy-tester-code"

    return RELEASE_CONTOUR, "default-release"


def migrate_update_contour(
    settings: MutableMapping[str, Any],
    *,
    config_path: str | None = None,
) -> ContourMigration:
    """Persist the contour once; after this, package/legacy hints are ignored."""
    explicit = normalize_contour(settings.get(CONTOUR_SETTING))
    if explicit:
        # Canonicalize case/whitespace if needed, but never re-infer.  This is
        # what keeps an existing tester on test even if a release marker later
        # appears in the installation directory.
        changed = settings.get(CONTOUR_SETTING) != explicit
        if changed:
            settings[CONTOUR_SETTING] = explicit
        return ContourMigration(explicit, "explicit", changed)

    contour, reason = infer_initial_contour(settings, config_path=config_path)
    settings[CONTOUR_SETTING] = contour
    return ContourMigration(contour, reason, True)
