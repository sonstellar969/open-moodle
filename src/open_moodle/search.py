"""Local SQLite FTS5 search index for course resources and documents."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Optional

from open_moodle.client import FileTooLargeError, MoodleClient
from open_moodle.parsers import extract_content

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".txt",
    ".md",
    ".py",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".html",
    ".json",
}


def get_default_db_path() -> Path:
    """Return default SQLite database path for local FTS index."""
    cache_home = os.environ.get("OPEN_MOODLE_CACHE_DIR") or os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        base = Path(cache_home)
    else:
        base = Path.home() / ".cache"
    dir_path = base / "open-moodle"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "search_index.db"


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Initialize SQLite FTS5 database tables and return connection."""
    path = db_path or get_default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            file_key TEXT PRIMARY KEY,
            course_id INTEGER,
            filename TEXT,
            timemodified INTEGER,
            filesize INTEGER,
            indexed_at REAL
        );
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks USING fts5(
            course_id UNINDEXED,
            course_name,
            module_name,
            filename,
            page_or_chunk,
            content,
            tokenize='porter unicode61'
        );
    """)
    conn.commit()
    return conn


def sanitize_fts_query(query: str) -> str:
    """Extract alphanumeric words and format into safe FTS5 query."""
    words = re.findall(r"[\w]+", query)
    if not words:
        return '""'
    return " ".join(f'"{w}"' for w in words)


def split_text_into_chunks(text: str, max_chunk_chars: int = 1500) -> list[tuple[str, str]]:
    """Split extracted document text into logical pages or manageable chunks.

    Returns list of (label, chunk_text).
    """
    if not text.strip():
        return []

    # Check if text contains explicit page/slide delimiters
    page_splits = list(re.finditer(r"---\s*(Page|Slide)\s*(\d+)\s*---", text, re.IGNORECASE))
    if page_splits:
        chunks: list[tuple[str, str]] = []
        for i, match in enumerate(page_splits):
            label = f"{match.group(1)} {match.group(2)}"
            start = match.end()
            end = page_splits[i + 1].start() if i + 1 < len(page_splits) else len(text)
            chunk_content = text[start:end].strip()
            if chunk_content:
                chunks.append((label, chunk_content))
        if chunks:
            return chunks

    # Fallback: sliding window chunking by character count
    chunks = []
    paragraphs = text.split("\n\n")
    current_chunk: list[str] = []
    current_len = 0
    chunk_idx = 1

    for para in paragraphs:
        p = para.strip()
        if not p:
            continue
        if current_len + len(p) > max_chunk_chars and current_chunk:
            chunks.append((f"Section {chunk_idx}", "\n\n".join(current_chunk)))
            chunk_idx += 1
            current_chunk = [p]
            current_len = len(p)
        else:
            current_chunk.append(p)
            current_len += len(p)

    if current_chunk:
        chunks.append((f"Section {chunk_idx}", "\n\n".join(current_chunk)))

    return chunks


def index_course_materials(
    client: MoodleClient,
    course_id: int,
    course_name: str = "",
    max_file_size: int = 25 * 1024 * 1024,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Download and index all text-extractable course files into local FTS5 database."""
    conn = init_db(db_path)
    contents = client.get_course_contents(course_id)

    if not course_name:
        try:
            courses = client.get_enrolled_courses()
            for c in courses:
                if c.get("id") == course_id:
                    course_name = c.get("fullname", f"Course {course_id}")
                    break
        except Exception:
            course_name = f"Course {course_id}"

    indexed_count = 0
    skipped_count = 0
    failed_count = 0

    for section in contents:
        sec_name = section.get("name", "General")
        for mod in section.get("modules", []):
            mod_name = mod.get("name", sec_name)
            for item in mod.get("contents", []):
                file_url = item.get("fileurl")
                filename = item.get("filename", "")
                filesize = item.get("filesize", 0)
                timemodified = item.get("timemodified", 0)

                if not file_url or not filename:
                    continue

                ext = Path(filename).suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                file_key = f"{course_id}_{filename}_{timemodified}"

                # Check if file was already indexed
                cur = conn.execute(
                    "SELECT 1 FROM indexed_files WHERE file_key = ?",
                    (file_key,),
                )
                if cur.fetchone():
                    skipped_count += 1
                    continue

                # Download and extract
                try:
                    raw_data = client.download_file(file_url, max_bytes=max_file_size)
                    text = extract_content(raw_data, filename)
                    chunks = split_text_into_chunks(text)

                    # Delete any previous version of chunks for this file
                    conn.execute(
                        "DELETE FROM file_chunks WHERE course_id = ? AND filename = ?",
                        (course_id, filename),
                    )

                    # Insert new chunks into FTS5
                    for label, chunk_text in chunks:
                        conn.execute(
                            """
                            INSERT INTO file_chunks (course_id, course_name, module_name, filename, page_or_chunk, content)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (course_id, course_name, mod_name, filename, label, chunk_text),
                        )

                    # Mark file as indexed
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO indexed_files (file_key, course_id, filename, timemodified, filesize, indexed_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (file_key, course_id, filename, timemodified, filesize, time.time()),
                    )
                    conn.commit()
                    indexed_count += 1
                except (FileTooLargeError, Exception):
                    failed_count += 1
                    continue

    conn.close()
    return {
        "course_id": course_id,
        "course_name": course_name,
        "indexed": indexed_count,
        "skipped": skipped_count,
        "failed": failed_count,
    }


def search_index(
    query: str,
    course_id: Optional[int] = None,
    limit: int = 5,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Query local FTS5 index for relevant document snippets with BM25 ranking."""
    path = db_path or get_default_db_path()
    if not path.exists():
        return []

    conn = sqlite3.connect(str(path))
    safe_q = sanitize_fts_query(query)
    if not safe_q or safe_q == '""':
        conn.close()
        return []

    sql = """
        SELECT
            course_id,
            course_name,
            module_name,
            filename,
            page_or_chunk,
            snippet(file_chunks, 5, '<b>', '</b>', '...', 28) AS matched_snippet,
            bm25(file_chunks) AS score
        FROM file_chunks
        WHERE file_chunks MATCH ?
    """
    params: list[Any] = [safe_q]

    if course_id:
        sql += " AND course_id = ?"
        params.append(course_id)

    sql += " ORDER BY score ASC LIMIT ?"
    params.append(limit)

    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    conn.close()

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append({
            "course_id": r[0],
            "course_name": r[1],
            "module_name": r[2],
            "filename": r[3],
            "page_or_chunk": r[4],
            "snippet": r[5],
            "score": r[6],
        })
    return results


def clear_course_index(course_id: int, db_path: Optional[Path] = None) -> int:
    """Remove indexed chunks and tracking records for a course."""
    path = db_path or get_default_db_path()
    if not path.exists():
        return 0

    conn = sqlite3.connect(str(path))
    conn.execute("DELETE FROM file_chunks WHERE course_id = ?", (course_id,))
    cur = conn.execute("DELETE FROM indexed_files WHERE course_id = ?", (course_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted
