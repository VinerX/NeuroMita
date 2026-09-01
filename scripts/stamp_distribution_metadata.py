from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable


MARKER_PATH = "Settings/distribution.json"
SCHEMA_VERSION = 1
VALID_CONTOURS = {"test", "release"}
_CHUNK_SIZE = 1024 * 1024


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(_CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _pyz_members(archive: zipfile.ZipFile) -> list[str]:
    return [
        info.filename
        for info in archive.infolist()
        if not info.is_dir() and info.filename.casefold().endswith(".pyz")
    ]


def _distribution_marker_member(pyz_members: Iterable[str]) -> str:
    """Place the marker next to the packaged .pyz, preserving archive layout."""
    parents = {
        PurePosixPath(str(member).replace("\\", "/")).parent
        for member in pyz_members
    }
    if not parents:
        raise RuntimeError("No .pyz artifact found")
    if len(parents) != 1:
        raise RuntimeError(
            "Packaged .pyz artifacts do not share one directory; "
            f"cannot choose distribution marker location: {sorted(map(str, parents))}"
        )

    parent = next(iter(parents))
    if str(parent) in {"", "."}:
        return MARKER_PATH
    return (parent / MARKER_PATH).as_posix()


def _is_distribution_marker_member(name: str) -> bool:
    normalized = str(name or "").replace("\\", "/").strip("/").casefold()
    marker = MARKER_PATH.casefold()
    return normalized == marker or normalized.endswith("/" + marker)


def _pyz_hashes(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path, "r") as archive:
        members = _pyz_members(archive)
        if not members:
            raise RuntimeError(f"No .pyz artifact found in {path}")
        result: dict[str, str] = {}
        for member in members:
            with archive.open(member, "r") as stream:
                result[member] = _sha256_stream(stream)
        return result


def _copy_member(
    source: zipfile.ZipFile,
    target: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> None:
    if info.is_dir():
        target.writestr(info, b"")
        return
    with source.open(info, "r") as src, target.open(info, "w") as dst:
        while True:
            chunk = src.read(_CHUNK_SIZE)
            if not chunk:
                break
            dst.write(chunk)


def build_metadata(
    *,
    contour: str,
    source_repo: str,
    source_tag: str,
    source_commit: str,
) -> dict[str, object]:
    contour = str(contour or "").strip().casefold()
    if contour not in VALID_CONTOURS:
        raise ValueError(f"Unsupported contour: {contour!r}")

    source_repo = str(source_repo or "").strip()
    source_tag = str(source_tag or "").strip()
    source_commit = str(source_commit or "").strip()
    if not source_repo or not source_tag or not source_commit:
        raise ValueError("source_repo, source_tag and source_commit are required")

    return {
        "schema": SCHEMA_VERSION,
        "contour": contour,
        "source_repo": source_repo,
        "source_tag": source_tag,
        "source_commit": source_commit,
    }


def stamp_archive(
    archive_path: str | os.PathLike[str],
    *,
    contour: str,
    source_repo: str,
    source_tag: str,
    source_commit: str,
) -> dict[str, str]:
    """Insert/replace Settings/distribution.json without changing .pyz bytes.

    The outer ZIP may be rewritten, but every embedded .pyz is hashed before
    and after.  The operation fails instead of publishing if any hash changes.
    This same helper can therefore be reused by the future Promote workflow
    when changing only ``contour=test`` to ``contour=release``.
    """
    path = Path(archive_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    metadata = build_metadata(
        contour=contour,
        source_repo=source_repo,
        source_tag=source_tag,
        source_commit=source_commit,
    )
    marker_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    before = _pyz_hashes(path)
    marker_member = _distribution_marker_member(before.keys())
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(
            temp_path,
            "w",
            allowZip64=True,
        ) as target:
            # Drop every old copy of the marker so the resulting archive has
            # exactly one authoritative distribution record.
            for info in source.infolist():
                if _is_distribution_marker_member(info.filename):
                    continue
                _copy_member(source, target, info)

            marker = zipfile.ZipInfo(marker_member)
            marker.compress_type = zipfile.ZIP_DEFLATED
            marker.external_attr = 0o100644 << 16
            target.writestr(marker, marker_bytes)

        after = _pyz_hashes(temp_path)
        if before != after:
            raise RuntimeError(
                "Embedded .pyz hash changed while stamping distribution metadata: "
                f"before={before}, after={after}"
            )

        os.replace(temp_path, path)
        return before
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stamp Settings/distribution.json into a NeuroMita release ZIP.",
    )
    parser.add_argument("--archive", required=True, help="Path to PythonBuild-*.zip")
    parser.add_argument("--contour", required=True, choices=sorted(VALID_CONTOURS))
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--source-commit", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    hashes = stamp_archive(
        args.archive,
        contour=args.contour,
        source_repo=args.source_repo,
        source_tag=args.source_tag,
        source_commit=args.source_commit,
    )
    print(f"Stamped distribution metadata: contour={args.contour}")
    for member, digest in hashes.items():
        print(f"Verified unchanged: {member} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
