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
        "--- Page 1 ---\nFirst slide content on CPU scheduling.\n"
        "--- Page 2 ---\nSecond slide content on memory management.\n"
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


def test_search_index_end_to_end(tmp_path):
    db_path = tmp_path / "test_search.db"
    conn = init_db(db_path)

    # Insert test chunk directly
    conn.execute(
        """
        INSERT INTO file_chunks (course_id, course_name, module_name, filename, page_or_chunk, content)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (101, "Networks", "Transport Layer", "tcp.pdf", "Page 4", "Sliding window protocol provides reliable byte stream flow control."),
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
