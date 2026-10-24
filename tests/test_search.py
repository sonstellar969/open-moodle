"""Tests for local SQLite FTS5 course search index."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock
import pytest

from open_moodle.search import (
    clear_course_index,
    index_course_materials,
    init_db,
    sanitize_fts_query,
    search_index,
    split_text_into_chunks,
)


def test_sanitize_fts_query():
    assert sanitize_fts_query("operating-systems: scheduling?") == '"operating" "systems" "scheduling"'
    assert sanitize_fts_query("") == '""'
    assert sanitize_fts_query("   ") == '""'
    assert sanitize_fts_query("deadlock") == '"deadlock"'


def test_split_text_into_chunks_page_markers():
    text = (
        "# PDF Document\n"
        "## Page 1\n"
        "First slide content on CPU scheduling.\n"
        "## Page 2\n"
        "Second slide content on memory management.\n"
    )
    chunks = split_text_into_chunks(text)
    assert len(chunks) == 2
    assert chunks[0][0] == "Page 1"
    assert "CPU scheduling" in chunks[0][1]
    assert chunks[1][0] == "Page 2"
    assert "memory management" in chunks[1][1]


def test_split_text_into_chunks_fallback_paragraphs():
    long_para1 = "Word " * 200
    long_para2 = "Section " * 200
    text = f"{long_para1}\n\n{long_para2}"
    chunks = split_text_into_chunks(text, max_chunk_chars=500)
    assert len(chunks) >= 2


def test_index_keeps_same_names_and_skips_legacy(tmp_path):
    db_path = tmp_path / "idx.db"
    client = MagicMock()
    client.get_enrolled_courses.return_value = [{"id": 3, "fullname": "OS"}]
    client.get_course_contents.return_value = [
        {
            "name": "Week 1",
            "modules": [
                {
                    "name": "Notes",
                    "contents": [
                        {
                            "filename": "notes.txt",
                            "fileurl": "https://lms.example/pluginfile.php/1/a/notes-a.txt?token=secret",
                            "timemodified": 1,
                            "filesize": 10,
                        },
                        {
                            "filename": "notes.txt",
                            "fileurl": "https://lms.example/pluginfile.php/2/b/notes-b.txt?token=secret",
                            "timemodified": 1,
                            "filesize": 10,
                        },
                        {
                            "filename": "old.doc",
                            "fileurl": "https://lms.example/pluginfile.php/3/old.doc",
                            "timemodified": 1,
                            "filesize": 10,
                        },
                    ],
                }
            ],
        }
    ]

    def _download(url, max_bytes=0):
        if "/1/a/" in url:
            return b"Alpha notes about paging tables and virtual memory."
        return b"Beta notes about file systems and inodes."

    client.download_file.side_effect = _download
    res = index_course_materials(client, course_id=3, db_path=db_path)
    assert res["indexed"] == 2
    assert res["unsupported"] == 1
    hits = search_index("paging", course_id=3, db_path=db_path)
    assert hits
    assert "token" not in (hits[0]["file_url"] or "")
    assert search_index("inodes", course_id=3, db_path=db_path)

    client.get_course_contents.return_value = []
    again = index_course_materials(client, course_id=3, db_path=db_path)
    assert again["removed"] == 2
    assert search_index("paging", course_id=3, db_path=db_path) == []


def test_search_index_end_to_end(tmp_path):
    db_path = tmp_path / "test_search.db"
    conn = init_db(db_path)

    # Insert test chunk directly
    conn.execute(
        """
        INSERT INTO file_chunks (
            file_key, course_id, course_name, module_name, filename, file_url, page_or_chunk, content
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "101|lms|tcp.pdf",
            "101",
            "Networks",
            "Transport Layer",
            "tcp.pdf",
            "https://lms.example/pluginfile.php/1/tcp.pdf",
            "Page 4",
            "Sliding window protocol provides reliable byte stream flow control.",
        ),
    )
    conn.commit()
    conn.close()

    results = search_index("sliding window", course_id=101, db_path=db_path)
    assert len(results) == 1
    assert results[0]["filename"] == "tcp.pdf"
    assert "sliding" in results[0]["snippet"].lower()

    # Clear index
    deleted = clear_course_index(101, db_path=db_path)
    assert search_index("sliding window", course_id=101, db_path=db_path) == []
