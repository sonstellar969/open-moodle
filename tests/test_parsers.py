"""Tests for configuration and parsers."""

from __future__ import annotations

import io
from open_moodle.config import get_base_url, normalize_moodle_url
from open_moodle.parsers import extract_content, strip_html


def test_normalize_moodle_url():
    cases = [
        ("https://lms.college.edu", "https://lms.college.edu/webservice/rest/server.php"),
        ("https://lms.college.edu/", "https://lms.college.edu/webservice/rest/server.php"),
        (
            "https://lms.college.edu/webservice/rest/server.php",
            "https://lms.college.edu/webservice/rest/server.php",
        ),
        ("lms.college.edu", "https://lms.college.edu/webservice/rest/server.php"),
    ]
    for raw, expected in cases:
        assert normalize_moodle_url(raw) == expected


def test_get_base_url():
    url = "https://lms.college.edu/webservice/rest/server.php"
    assert get_base_url(url) == "https://lms.college.edu"


def test_strip_html():
    raw_html = "<p>Submit assignment before <b>Friday</b>.<br/>No late submissions.</p>"
    stripped = strip_html(raw_html)
    assert "Submit assignment before Friday." in stripped
    assert "No late submissions." in stripped
    assert "<p>" not in stripped
    assert "<b>" not in stripped


def make_test_pdf(text: str = "Operating Systems Sample Page") -> bytes:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_extract_plain_text():
    sample = b"Operating Systems Unit 1 Notes\n1. Process Concept\n2. Threads"
    text = extract_content(sample, filename="notes.txt")
    assert "Operating Systems Unit 1 Notes" in text
    assert "1. Process Concept" in text


def test_extract_handles_url_with_query_params():
    pdf_bytes = make_test_pdf("Lecture 1 Introduction")
    text = extract_content(
        pdf_bytes,
        filename="https://lms.college.edu/pluginfile.php/123/file.pdf?forcedownload=1",
    )
    assert "# PDF Document" in text
    assert "Lecture 1 Introduction" in text


def test_extract_magic_bytes_without_filename():
    pdf_bytes = make_test_pdf("Anonymous File Content")
    text = extract_content(pdf_bytes, filename="")
    assert "# PDF Document" in text
    assert "Anonymous File Content" in text


def test_extract_corrupted_pdf_handles_gracefully():
    corrupted = b"%PDF-1.5 this is not valid binary pdf content"
    text = extract_content(corrupted, filename="corrupted.pdf")
    assert "[Failed to parse PDF document:" in text
