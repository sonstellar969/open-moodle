"""Tests for MoodleClient HTTP methods and error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from open_moodle.client import MoodleAPIError, MoodleClient


def test_client_error_response_raises():
    client = MoodleClient("https://lms.college.edu", "dummy_token")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "exception": "moodle_exception",
        "errorcode": "invalidtoken",
        "message": "Invalid token - token expired",
    }
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "post", return_value=mock_resp):
        with pytest.raises(MoodleAPIError) as exc_info:
            client.call("core_webservice_get_site_info")

        assert exc_info.value.errorcode == "invalidtoken"
        assert "Invalid token" in str(exc_info.value)

    client.close()


def test_download_file_appends_token():
    client = MoodleClient("https://lms.college.edu", "secret_token_123")

    mock_resp = MagicMock()
    mock_resp.content = b"%PDF-1.5 test file content"
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "get", return_value=mock_resp) as mock_get:
        content = client.download_file("https://lms.college.edu/pluginfile.php/123/notes.pdf")
        assert content == b"%PDF-1.5 test file content"

        called_url = mock_get.call_args[0][0]
        assert "token=secret_token_123" in called_url

    client.close()


def test_download_file_retains_existing_token():
    client = MoodleClient("https://lms.college.edu", "secret_token_123")

    mock_resp = MagicMock()
    mock_resp.content = b"sample text"
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "get", return_value=mock_resp) as mock_get:
        url_with_token = "https://lms.college.edu/pluginfile.php/123/notes.txt?token=existing_tok"
        client.download_file(url_with_token)

        called_url = mock_get.call_args[0][0]
        assert called_url == url_with_token

    client.close()
