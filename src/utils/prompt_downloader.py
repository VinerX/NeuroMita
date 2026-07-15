from __future__ import annotations

import os
import shutil
import stat
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests

from core.app_paths import base_dir
from main_logger import logger


class PromptDownloader:
    _CONNECT_TIMEOUT_SECONDS = 10.0
    _READ_TIMEOUT_SECONDS = 120.0
    _MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
    _MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
    _MAX_ARCHIVE_FILES = 10_000
    _CHUNK_SIZE = 256 * 1024

    def __init__(self) -> None:
        self.repo_url = "https://github.com/VinerX/NeuroMita"
        self.branch = "main"

        configured = str(os.environ.get("NEUROMITA_PROMPTS_DIR", "") or "").strip()
        self.base_path = (
            Path(configured).expanduser().resolve()
            if configured
            else (base_dir() / "Prompts").resolve()
        )
        self.backup_path = self.base_path.with_name(f"{self.base_path.name}_backup")

    def download_and_replace_prompts(
        self,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Download the configured prompt set and replace it transactionally."""
        staging_path = self.base_path.with_name(
            f".{self.base_path.name}.download-{uuid.uuid4().hex}"
        )

        try:
            zip_url = self._build_zip_url()
            logger.info("Downloading repository zip from: %s", zip_url)

            archive = self._download_archive(zip_url, cancel_event=cancel_event)
            try:
                self._extract_prompts(
                    archive,
                    staging_path,
                    cancel_event=cancel_event,
                )
            finally:
                archive.close()

            self._replace_transactionally(staging_path)
            logger.info("Successfully downloaded and replaced prompts")
            return True
        except Exception as exc:
            logger.error("Error in download_and_replace_prompts: %s", exc, exc_info=True)
            self._remove_path(staging_path)
            return False

    def _build_zip_url(self) -> str:
        parsed_url = urlparse(self.repo_url)
        path_parts = [part for part in parsed_url.path.split("/") if part]
        if parsed_url.scheme not in {"http", "https"} or len(path_parts) < 2:
            raise ValueError(f"Unsupported repository URL: {self.repo_url!r}")
        owner, repo = path_parts[:2]
        repo = repo.removesuffix(".git")
        return f"https://api.github.com/repos/{owner}/{repo}/zipball/{self.branch}"

    def _download_archive(
        self,
        zip_url: str,
        *,
        cancel_event: threading.Event | None,
    ) -> tempfile.SpooledTemporaryFile:
        archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
        downloaded = 0
        try:
            with requests.get(
                zip_url,
                stream=True,
                timeout=(self._CONNECT_TIMEOUT_SECONDS, self._READ_TIMEOUT_SECONDS),
                headers={"User-Agent": "NeuroMita-PromptUpdater/1"},
            ) as response:
                response.raise_for_status()

                raw_length = str(response.headers.get("Content-Length", "") or "").strip()
                if raw_length:
                    try:
                        content_length = int(raw_length)
                    except ValueError:
                        content_length = 0
                    if content_length > self._MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"Prompt archive is too large: {content_length} bytes"
                        )

                for chunk in response.iter_content(chunk_size=self._CHUNK_SIZE):
                    self._raise_if_cancelled(cancel_event)
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > self._MAX_DOWNLOAD_BYTES:
                        raise ValueError(
                            f"Prompt archive exceeded {self._MAX_DOWNLOAD_BYTES} bytes"
                        )
                    archive.write(chunk)

            if downloaded <= 0:
                raise ValueError("Downloaded prompt archive is empty")
            archive.seek(0)
            return archive
        except Exception:
            archive.close()
            raise

    def _extract_prompts(
        self,
        archive,
        staging_path: Path,
        *,
        cancel_event: threading.Event | None,
    ) -> None:
        self._remove_path(staging_path)
        staging_path.mkdir(parents=True, exist_ok=False)

        extracted_files = 0
        extracted_bytes = 0
        with zipfile.ZipFile(archive) as zip_ref:
            infos = zip_ref.infolist()
            prompt_prefix = self._find_prompt_prefix(infos)

            for info in infos:
                self._raise_if_cancelled(cancel_event)
                parts = PurePosixPath(info.filename).parts
                if len(parts) <= len(prompt_prefix) or tuple(parts[: len(prompt_prefix)]) != prompt_prefix:
                    continue

                relative_parts = parts[len(prompt_prefix) :]
                if not relative_parts or any(part in {"", ".", ".."} for part in relative_parts):
                    continue
                if self._is_symlink(info):
                    raise ValueError(f"Symlink is not allowed in prompt archive: {info.filename}")

                target_path = staging_path.joinpath(*relative_parts)
                resolved_target = target_path.resolve()
                if staging_path.resolve() not in resolved_target.parents:
                    raise ValueError(f"Unsafe archive path: {info.filename}")

                if info.is_dir():
                    resolved_target.mkdir(parents=True, exist_ok=True)
                    continue

                extracted_files += 1
                if extracted_files > self._MAX_ARCHIVE_FILES:
                    raise ValueError("Prompt archive contains too many files")

                declared_size = max(0, int(info.file_size or 0))
                if extracted_bytes + declared_size > self._MAX_EXTRACTED_BYTES:
                    raise ValueError("Extracted prompt archive is too large")

                resolved_target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with zip_ref.open(info) as source, open(resolved_target, "wb") as target:
                    while True:
                        self._raise_if_cancelled(cancel_event)
                        chunk = source.read(self._CHUNK_SIZE)
                        if not chunk:
                            break
                        written += len(chunk)
                        if extracted_bytes + written > self._MAX_EXTRACTED_BYTES:
                            raise ValueError("Extracted prompt archive is too large")
                        target.write(chunk)
                extracted_bytes += written

        if extracted_files == 0:
            raise ValueError("The downloaded repository does not contain a Prompts directory")

    @staticmethod
    def _find_prompt_prefix(infos: list[zipfile.ZipInfo]) -> tuple[str, ...]:
        for info in infos:
            parts = PurePosixPath(info.filename).parts
            for index, part in enumerate(parts):
                if part == "Prompts" and index > 0:
                    return tuple(parts[: index + 1])
        raise ValueError("Prompts directory was not found in the archive")

    @staticmethod
    def _is_symlink(info: zipfile.ZipInfo) -> bool:
        mode = int(info.external_attr or 0) >> 16
        return bool(mode and stat.S_ISLNK(mode))

    def _replace_transactionally(self, staging_path: Path) -> None:
        self.base_path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_path(self.backup_path)

        moved_old = False
        try:
            if self.base_path.exists():
                os.replace(self.base_path, self.backup_path)
                moved_old = True
            os.replace(staging_path, self.base_path)
        except Exception:
            self._remove_path(self.base_path)
            if moved_old and self.backup_path.exists():
                os.replace(self.backup_path, self.base_path)
            raise

    @staticmethod
    def _remove_path(path: Path) -> None:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            elif path.exists() or path.is_symlink():
                path.unlink()
        except FileNotFoundError:
            return

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Prompt update was cancelled")
