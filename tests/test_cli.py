"""Tests for CLI arguments and command routing."""

from __future__ import annotations

from unittest.mock import patch

from open_moodle.cli import main


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit:
        pass
    captured = capsys.readouterr()
    assert "open-moodle" in captured.out or "open-moodle" in captured.err


def test_cli_whoami_routed():
    with patch("open_moodle.cli.cmd_whoami", return_value=0) as mock_whoami:
        code = main(["whoami", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_whoami.assert_called_once()


def test_cli_courses_routed():
    with patch("open_moodle.cli.cmd_courses", return_value=0) as mock_courses:
        code = main(["courses", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_courses.assert_called_once()


def test_cli_announcements_routed():
    with patch("open_moodle.cli.cmd_announcements", return_value=0) as mock_ann:
        code = main(["announcements", "201", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_ann.assert_called_once()


def test_cli_grades_routed():
    with patch("open_moodle.cli.cmd_grades", return_value=0) as mock_grades:
        code = main(["grades", "--course", "201", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_grades.assert_called_once()


def test_cli_brief_routed():
    with patch("open_moodle.cli.cmd_brief", return_value=0) as mock_brief:
        code = main(["brief", "--days", "7", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_brief.assert_called_once()


def test_cli_attendance_routed():
    with patch("open_moodle.cli.cmd_attendance", return_value=0) as mock_att:
        code = main(["attendance", "--threshold", "80.0", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_att.assert_called_once()


def test_cli_search_routed():
    with patch("open_moodle.cli.cmd_search", return_value=0) as mock_search:
        code = main(["search", "paging", "--course", "201"])
        assert code == 0
        mock_search.assert_called_once()


def test_cli_sync_routed():
    with patch("open_moodle.cli.cmd_sync", return_value=0) as mock_sync:
        code = main(["sync", "201", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_sync.assert_called_once()


def test_cli_download_routed():
    with patch("open_moodle.cli.cmd_download", return_value=0) as mock_dl:
        code = main(["download", "201", "--dest", "/tmp/dl", "--url", "https://test.edu", "--token", "tok"])
        assert code == 0
        mock_dl.assert_called_once()

