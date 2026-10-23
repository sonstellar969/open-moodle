"""Bulk resource downloader for Moodle courses."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any, Callable, Optional

from open_moodle.client import FileTooLargeError, MoodleClient


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Sanitize directory or file name for all filesystem platforms."""
    # Replace illegal filesystem characters with underscores
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "unnamed"
    if len(cleaned) > max_length:
        base, ext = os.path.splitext(cleaned)
        cleaned = base[: max_length - len(ext)] + ext
    return cleaned


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

    for idx, (sec_folder, filename, file_url, filesize) in enumerate(items_to_process, start=1):
        target_dir = dest_dir / sec_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / sanitize_filename(filename)

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
        except (FileTooLargeError, Exception):
            failed += 1
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
    }
