from __future__ import annotations
from core.error_utils import format_exception

import base64
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

from main_logger import logger

_DEFAULT_ROOT_DIRNAME = "GameTransfer"
_DEFAULT_IMAGES_DIRNAME = "Images"
_DEFAULT_MANIFESTS_DIRNAME = "Manifests"


def get_shared_transfer_root() -> Path:
    explicit = str(os.environ.get("NEUROMITA_SHARED_TRANSFER_DIR", "") or "").strip()
    if explicit:
        root = Path(explicit)
    else:
        base_dir = str(os.environ.get("NEUROMITA_BASE_DIR", "") or "").strip() or os.getcwd()
        root = Path(base_dir) / _DEFAULT_ROOT_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def ensure_shared_transfer_dirs() -> dict[str, Path]:
    root = get_shared_transfer_root()
    images_dir = root / _DEFAULT_IMAGES_DIRNAME
    manifests_dir = root / _DEFAULT_MANIFESTS_DIRNAME
    images_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    return {
        "root": root,
        "images": images_dir,
        "manifests": manifests_dir,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _normalize_file_ref(ref: Any) -> str:
    text = str(ref or "").strip()
    if not text:
        return ""
    if text.startswith("file://"):
        parsed = urlparse(text)
        if parsed.scheme == "file":
            if parsed.netloc and parsed.path:
                return unquote(f"//{parsed.netloc}{parsed.path}")
            return unquote(parsed.path)
    return text


def _sanitize_client_id(client_id: str | None) -> str:
    raw = str(client_id or "").strip()
    if not raw:
        return ""
    safe = []
    for ch in raw:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe).strip("._")


def resolve_shared_file_ref(
    ref: Any,
    *,
    client_id: str | None = None,
    base_dir: Path | None = None,
) -> Path | None:
    raw = _normalize_file_ref(ref)
    if not raw:
        return None

    dirs = ensure_shared_transfer_dirs()
    root = dirs["root"]
    candidate = Path(raw)

    allowed_roots: list[Path] = [root, dirs["images"], dirs["manifests"]]
    safe_client = _sanitize_client_id(client_id)
    if safe_client:
        client_root = root / "clients" / safe_client
        client_root.mkdir(parents=True, exist_ok=True)
        allowed_roots.append(client_root.resolve())

    resolved: Path | None = None
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        search_roots: list[Path] = []
        if base_dir is not None:
            search_roots.append(base_dir.resolve())
        if safe_client:
            search_roots.append((root / "clients" / safe_client).resolve())
        search_roots.extend([dirs["images"], dirs["manifests"], root])

        for search_root in search_roots:
            probe = (search_root / candidate).resolve()
            if probe.exists():
                resolved = probe
                break

        if resolved is None and search_roots:
            resolved = (search_roots[0] / candidate).resolve()

    if resolved is None:
        return None

    if not any(_is_within(resolved, allowed_root) for allowed_root in allowed_roots):
        logger.warning(
            f"[shared_image_transfer] Ref outside allowed roots ignored: {resolved}"
        )
        return None

    return resolved


def _iter_context_path_refs(context: dict[str, Any]) -> Iterable[Any]:
    for key in ("image_paths", "shared_image_paths", "image_files"):
        items = context.get(key) or []
        if isinstance(items, (str, bytes, os.PathLike)):
            yield items
            continue
        if isinstance(items, list):
            for item in items:
                yield item


def _load_manifest_payload(
    manifest_payload: Any,
    *,
    client_id: str | None = None,
) -> tuple[dict[str, Any] | None, Path | None]:
    if not manifest_payload:
        return None, None

    if isinstance(manifest_payload, dict):
        return manifest_payload, None

    manifest_path = resolve_shared_file_ref(manifest_payload, client_id=client_id)
    if manifest_path is None:
        logger.warning(
            f"[shared_image_transfer] Manifest ref could not be resolved: {manifest_payload!r}"
        )
        return None, None

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            return json.load(fh), manifest_path
    except Exception as exc:
        logger.warning(
            f"[shared_image_transfer] Failed to load manifest {manifest_path}: {format_exception(exc)}"
        )
        return None, manifest_path


def _iter_manifest_path_refs(
    manifest: dict[str, Any] | None,
    *,
    manifest_path: Path | None = None,
) -> Iterable[Any]:
    if not isinstance(manifest, dict):
        return

    for key in ("image_paths", "shared_image_paths", "files"):
        items = manifest.get(key) or []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    path_ref = item.get("path") or item.get("file") or item.get("image_path")
                    if path_ref:
                        yield path_ref
                else:
                    yield item

    images = manifest.get("images") or []
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                path_ref = item.get("path") or item.get("file") or item.get("image_path")
                if path_ref:
                    yield path_ref
            else:
                yield item


def _decode_base64_image(item: Any) -> bytes | None:
    if isinstance(item, bytes):
        return item

    text = str(item or "").strip()
    if not text:
        return None

    payload = text.split(",", 1)[-1] if text.startswith("data:image") else text
    try:
        return base64.b64decode(payload)
    except Exception as exc:
        logger.warning(f"[shared_image_transfer] Failed to decode base64 image: {format_exception(exc)}")
        return None


def _cleanup_paths(paths: Iterable[Path]) -> None:
    root = get_shared_transfer_root()
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:
            logger.warning(f"[shared_image_transfer] Failed to delete {path}: {format_exception(exc)}")

    for path in paths:
        try:
            parent = path.parent
            while parent != root and _is_within(parent, root):
                parent.rmdir()
                parent = parent.parent
        except Exception:
            pass


def collect_context_images(
    context: dict[str, Any] | None,
    *,
    client_id: str | None = None,
) -> list[bytes]:
    context = context or {}

    images: list[bytes] = []
    cleanup_candidates: list[Path] = []

    for item in context.get("image_base64_list", []) or []:
        decoded = _decode_base64_image(item)
        if decoded is not None:
            images.append(decoded)

    manifest_payload = (
        context.get("image_manifest")
        or context.get("image_manifest_path")
        or context.get("shared_image_manifest")
    )
    manifest, manifest_path = _load_manifest_payload(manifest_payload, client_id=client_id)
    if manifest_path is not None:
        cleanup_candidates.append(manifest_path)

    delete_after_read = context.get("delete_after_read")
    if delete_after_read is None and isinstance(manifest, dict):
        delete_after_read = manifest.get("delete_after_read")
    if delete_after_read is None:
        delete_after_read = True

    all_refs = list(_iter_context_path_refs(context))
    all_refs.extend(
        _iter_manifest_path_refs(
            manifest,
            manifest_path=manifest_path,
        )
    )

    manifest_base_dir = manifest_path.parent if manifest_path is not None else None
    for ref in all_refs:
        resolved = resolve_shared_file_ref(ref, client_id=client_id, base_dir=manifest_base_dir)
        if resolved is None:
            logger.warning(f"[shared_image_transfer] Image ref ignored: {ref!r}")
            continue
        if not resolved.exists() or not resolved.is_file():
            logger.warning(f"[shared_image_transfer] Image file missing: {resolved}")
            continue
        try:
            images.append(resolved.read_bytes())
            cleanup_candidates.append(resolved)
        except Exception as exc:
            logger.warning(f"[shared_image_transfer] Cannot read image from {resolved}: {format_exception(exc)}")

    if cleanup_candidates and bool(delete_after_read):
        _cleanup_paths(cleanup_candidates)

    return images
