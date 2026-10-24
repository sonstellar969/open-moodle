"""Bulk resource downloader for Moodle courses."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Callable, Optional

from open_moodle.client import MoodleClient


_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Sanitize a single path segment for every common filesystem."""
    # Keep only the last segment so names like ../secret cannot escape a folder.
    cleaned = name.replace("\\", "/").split("/")[-1]
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "unnamed"
    stem = os.path.splitext(cleaned)[0].upper()
    if stem in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        base, ext = os.path.splitext(cleaned)
        cleaned = base[: max(1, max_length - len(ext))] + ext
    return cleaned


def _path_inside(root: Path, candidate: Path) -> Path:
    """Resolve candidate and refuse anything outside root."""
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"Refusing to write outside {resolved_root}")
    return resolved


def download_course_materials(
    client: MoodleClient,
    course_id: int,
    dest_dir: Path,
    max_file_size: int = 50 * 1024 * 1024,
    progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
) -> dict[str, Any]:
    """Download all resource files from a course into structured topic folders.

    progress_callback signature: (filename: str, current_idx: int, total_files: int, status: str)
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    contents = client.get_course_contents(course_id)

    # First pass: collect all downloadable file descriptors
    items_to_process: list[tuple[str, str, str, int]] = []
    for s_idx, section in enumerate(contents, start=1):
        raw_sec_name = section.get("name") or f"Section {s_idx}"
        sec_folder = f"{s_idx:02d}_{sanitize_filename(raw_sec_name)}"

        for mod in section.get("modules", []):
            for item in mod.get("contents", []):
                file_url = item.get("fileurl")
                filename = item.get("filename", "")
                filesize = item.get("filesize", 0)

                if file_url and filename:
                    items_to_process.append((sec_folder, filename, file_url, filesize))

    total = len(items_to_process)
    downloaded = 0
    skipped = 0
    failed = 0
    total_bytes = 0
    errors: list[str] = []
    claimed: set[Path] = set()

    for idx, (sec_folder, filename, file_url, filesize) in enumerate(items_to_process, start=1):
        try:
            target_dir = _path_inside(dest_dir, dest_dir / sec_folder)
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = _allocate_path(target_dir, filename, claimed)
            target_path = _path_inside(dest_dir, target_path)
        except ValueError as exc:
            failed += 1
            errors.append(f"{filename}: {exc}")
            if progress_callback:
                progress_callback(filename, idx, total, "failed")
            continue

        # Check if file exists and matches size
        if target_path.exists() and filesize > 0 and target_path.stat().st_size == filesize:
            skipped += 1
            if progress_callback:
                progress_callback(filename, idx, total, "skipped")
            continue

        if progress_callback:
            progress_callback(filename, idx, total, "downloading")

        try:
            data = client.download_file(file_url, max_bytes=max_file_size)
            tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            tmp_path.write_bytes(data)
            tmp_path.replace(target_path)

            downloaded += 1
            total_bytes += len(data)
            if progress_callback:
                progress_callback(filename, idx, total, "done")
        except Exception as exc:
            failed += 1
            errors.append(f"{filename}: {exc}")
            if progress_callback:
                progress_callback(filename, idx, total, "failed")

    return {
        "course_id": course_id,
        "destination": str(dest_dir.resolve()),
        "total_files": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "total_bytes": total_bytes,
        "errors": errors[:8],
    }


def _allocate_path(target_dir: Path, filename: str, claimed: set[Path]) -> Path:
    """Pick a free file name so two resources cannot overwrite each other."""
    safe = sanitize_filename(filename)
    stem, suffix = os.path.splitext(safe)
    candidate = target_dir / safe
    number = 2
    while candidate in claimed:
        candidate = target_dir / f"{stem}_{number}{suffix}"
        number += 1
    claimed.add(candidate)
    return candidate
