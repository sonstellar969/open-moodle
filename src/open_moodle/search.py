"""Local SQLite FTS5 search index for course resources and documents."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Optional

import urllib.parse

from open_moodle.client import FileTooLargeError, MoodleClient, redact_secrets, strip_token_from_url
from open_moodle.parsers import extract_content

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
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
# Legacy OLE files are not parsed. Indexing their error text would pollute search.
LEGACY_EXTENSIONS = {".doc", ".ppt"}
SCHEMA_VERSION = "2"
# snippet() column index for `content` in the FTS5 table below.
_CONTENT_COLUMN = 7


def _restrict_private(path: Path) -> None:
    """Best-effort owner-only permissions for the cache directory and database."""
    try:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)
    except OSError:
        pass


def get_default_db_path() -> Path:
    """Return default SQLite database path for local FTS index."""
    cache_home = os.environ.get("OPEN_MOODLE_CACHE_DIR") or os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        base = Path(cache_home)
    else:
        base = Path.home() / ".cache"
    dir_path = base / "open-moodle"
    dir_path.mkdir(parents=True, exist_ok=True)
    _restrict_private(dir_path)
    return dir_path / "search_index.db"


def init_db(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Initialize SQLite FTS5 database tables and return connection."""
    path = db_path or get_default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _restrict_private(path.parent)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    current = conn.execute(
        "SELECT value FROM index_meta WHERE key = 'schema'"
    ).fetchone()
    if current is None or current[0] != SCHEMA_VERSION:
        conn.execute("DROP TABLE IF EXISTS file_chunks")
        conn.execute("DROP TABLE IF EXISTS indexed_files")
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES ('schema', ?)",
            (SCHEMA_VERSION,),
        )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            file_key TEXT PRIMARY KEY,
            course_id INTEGER,
            filename TEXT,
            file_url TEXT,
            timemodified INTEGER,
            filesize INTEGER,
            indexed_at REAL
        );
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS file_chunks USING fts5(
            file_key UNINDEXED,
            course_id UNINDEXED,
            course_name,
            module_name,
            filename,
            file_url UNINDEXED,
            page_or_chunk,
            content,
            tokenize='porter unicode61'
        );
    """)
    conn.commit()
    _restrict_private(path)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            _restrict_private(sidecar)
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

    # Parsers emit "## Page N" / "## Slide N". Older callers used "--- Page N ---".
    page_splits = list(re.finditer(
        r"(?im)^(?:---\s*)?#{0,3}\s*(Page|Slide)\s+(\d+)\s*(?:---)?\s*$",
        text,
    ))
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
    removed_count = 0
    unsupported_count = 0
    errors: list[str] = []
    seen: set[str] = set()

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
                if ext in LEGACY_EXTENSIONS:
                    unsupported_count += 1
                    errors.append(f"{filename}: legacy {ext} is not indexed")
                    continue
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                file_key = _file_key(course_id, file_url)
                seen.add(file_key)
                safe_url = strip_token_from_url(file_url)

                cur = conn.execute(
                    "SELECT timemodified FROM indexed_files WHERE file_key = ?",
                    (file_key,),
                )
                existing = cur.fetchone()
                if existing and int(existing[0] or 0) == int(timemodified or 0):
                    skipped_count += 1
                    continue

                try:
                    raw_data = client.download_file(file_url, max_bytes=max_file_size)
                    text = extract_content(raw_data, filename, max_pages=None)
                    if text.startswith("[Failed") or text.startswith("[Binary"):
                        failed_count += 1
                        errors.append(f"{filename}: {text.splitlines()[0][:180]}")
                        continue
                    chunks = split_text_into_chunks(text)

                    conn.execute("DELETE FROM file_chunks WHERE file_key = ?", (file_key,))
                    for label, chunk_text in chunks:
                        conn.execute(
                            """
                            INSERT INTO file_chunks (
                                file_key, course_id, course_name, module_name,
                                filename, file_url, page_or_chunk, content
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (file_key, str(course_id), course_name, mod_name, filename, safe_url, label, chunk_text),
                        )

                    conn.execute(
                        """
                        INSERT OR REPLACE INTO indexed_files (
                            file_key, course_id, filename, file_url, timemodified, filesize, indexed_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (file_key, course_id, filename, safe_url, timemodified, filesize, time.time()),
                    )
                    conn.commit()
                    indexed_count += 1
                except (FileTooLargeError, Exception) as exc:
                    failed_count += 1
                    errors.append(f"{filename}: {redact_secrets(str(exc))[:180]}")
                    continue

    stale = conn.execute(
        "SELECT file_key FROM indexed_files WHERE course_id = ?",
        (course_id,),
    ).fetchall()
    for (stale_key,) in stale:
        if stale_key not in seen:
            conn.execute("DELETE FROM file_chunks WHERE file_key = ?", (stale_key,))
            conn.execute("DELETE FROM indexed_files WHERE file_key = ?", (stale_key,))
            removed_count += 1
    conn.commit()
    conn.close()
    return {
        "course_id": course_id,
        "course_name": course_name,
        "indexed": indexed_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "removed": removed_count,
        "unsupported": unsupported_count,
        "errors": errors[:8],
    }


def _file_key(course_id: int, file_url: str) -> str:
    """Stable identity for one resource, ignoring token query parameters."""
    clean = strip_token_from_url(file_url)
    parsed = urllib.parse.urlsplit(clean)
    return f"{course_id}|{parsed.netloc.lower()}|{parsed.path}"


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

    sql = f"""
        SELECT
            course_id,
            course_name,
            module_name,
            filename,
            file_url,
            page_or_chunk,
            snippet(file_chunks, {_CONTENT_COLUMN}, '<b>', '</b>', '...', 28) AS matched_snippet,
            bm25(file_chunks) AS score
        FROM file_chunks
        WHERE file_chunks MATCH ?
    """
    params: list[Any] = [safe_q]

    if course_id:
        sql += " AND course_id = ?"
        params.append(str(course_id))

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
            "file_url": r[4],
            "page_or_chunk": r[5],
            "snippet": r[6],
            "score": r[7],
        })
    return results


def clear_course_index(course_id: int, db_path: Optional[Path] = None) -> int:
    """Remove indexed chunks and tracking records for a course."""
    path = db_path or get_default_db_path()
    if not path.exists():
        return 0

    conn = sqlite3.connect(str(path))
    conn.execute("DELETE FROM file_chunks WHERE course_id = ?", (str(course_id),))
    cur = conn.execute("DELETE FROM indexed_files WHERE course_id = ?", (course_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted
