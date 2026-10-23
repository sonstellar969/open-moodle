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


def test_extract_plain_text():
    sample = b"Operating Systems Unit 1 Notes\n1. Process Concept\n2. Threads"
    text = extract_content(sample, filename="notes.txt")
    assert "Operating Systems Unit 1 Notes" in text
    assert "1. Process Concept" in text
