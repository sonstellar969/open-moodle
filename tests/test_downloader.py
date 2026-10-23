"""Tests for bulk course downloader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from open_moodle.downloader import download_course_materials, sanitize_filename


def test_sanitize_filename():
    assert sanitize_filename("Operating: Systems / Unix") == "Operating_ Systems _ Unix"
    assert sanitize_filename("   hello   ") == "hello"
    assert sanitize_filename("") == "unnamed"
    long_name = "a" * 200 + ".pdf"
    assert len(sanitize_filename(long_name, max_length=50)) <= 50


def test_download_course_materials_skips_existing(tmp_path):
    client = MagicMock()
    client.get_course_contents.return_value = [
        {
            "name": "Lecture 1",
            "modules": [
                {
                    "contents": [
                        {
                            "filename": "slides.pdf",
                            "fileurl": "https://example.com/slides.pdf",
                            "filesize": 10,
                        }
                    ]
                }
            ],
        }
    ]
    client.download_file.return_value = b"0123456789"

    # First run downloads
    dest = tmp_path / "course_download"
    res1 = download_course_materials(client, course_id=1, dest_dir=dest)
    assert res1["downloaded"] == 1
    assert res1["skipped"] == 0

    # Second run skips because size matches
    res2 = download_course_materials(client, course_id=1, dest_dir=dest)
    assert res2["downloaded"] == 0
    assert res2["skipped"] == 1
