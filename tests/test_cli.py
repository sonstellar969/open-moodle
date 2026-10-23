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
