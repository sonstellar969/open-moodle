"""Tests for MoodleClient HTTP methods, capability checks, and token sanitization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from open_moodle.client import (
    CapabilityError,
    FileTooLargeError,
    MoodleAPIError,
    MoodleClient,
    flatten_moodle_params,
    strip_token_from_url,
)


def test_strip_token_from_url():
    url = "https://lms.college.edu/pluginfile.php/123/file.pdf?forcedownload=1&token=secret123"
    sanitized = strip_token_from_url(url)
    assert "token=" not in sanitized
    assert "secret123" not in sanitized
    assert "forcedownload=1" in sanitized


def test_flatten_moodle_params():
    nested = {
        "options": {"timestart": 100, "timeend": 200},
        "courseids": [10, 20],
    }
    flattened = flatten_moodle_params(nested)
    assert flattened["options[timestart]"] == 100
    assert flattened["options[timeend]"] == 200
    assert flattened["courseids[0]"] == 10
    assert flattened["courseids[1]"] == 20


def test_capability_error_on_forbidden_function():
    client = MoodleClient("https://lms.college.edu", "dummy_token")
    client._site_info = {"sitename": "Test LMS"}
    client._available_functions = {"core_webservice_get_site_info", "core_enrol_get_users_courses"}

    with pytest.raises(CapabilityError, match="is not permitted or enabled"):
        client.call("mod_assign_get_assignments")

    client.close()


def test_client_error_response_raises():
    client = MoodleClient("https://lms.college.edu", "dummy_token")
    client._available_functions = {"core_webservice_get_site_info"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "exception": "moodle_exception",
        "errorcode": "invalidtoken",
        "message": "Invalid token - token expired",
    }
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "post", return_value=mock_resp):
        with pytest.raises(MoodleAPIError) as exc_info:
            client.call("core_webservice_get_site_info", check_caps=False)

        assert exc_info.value.errorcode == "invalidtoken"
        assert "Invalid token" in str(exc_info.value)

    client.close()


def test_course_contents_sanitizes_urls():
    client = MoodleClient("https://lms.college.edu", "tok")
    client._available_functions = {"core_course_get_contents"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {
            "id": 1,
            "name": "Topic 1",
            "modules": [
                {
                    "name": "Slides",
                    "url": "https://lms.college.edu/mod/resource/view.php?id=10&token=leak1",
                    "contents": [
                        {
                            "filename": "slides.pdf",
                            "fileurl": "https://lms.college.edu/pluginfile.php/1/slides.pdf?token=leak2",
                        }
                    ],
                }
            ],
        }
    ]
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "post", return_value=mock_resp):
        contents = client.get_course_contents(101)
        mod = contents[0]["modules"][0]
        assert "leak1" not in mod["url"]
        assert "leak2" not in mod["contents"][0]["fileurl"]

    client.close()


def test_download_file_size_limit_exceeded():
    client = MoodleClient("https://lms.college.edu", "secret_token_123")

    mock_res = MagicMock()
    mock_res.raise_for_status.return_value = None
    # 2MB chunks, limit is 1MB
    mock_res.iter_bytes.return_value = [b"x" * (1024 * 1024), b"y" * (1024 * 1024)]

    with patch.object(client._http, "stream") as mock_stream:
        mock_stream.return_value.__enter__.return_value = mock_res
        with pytest.raises(FileTooLargeError, match="exceeds maximum download size limit"):
            client.download_file("https://lms.college.edu/pluginfile.php/1/huge.pdf", max_bytes=1024 * 1024)

    client.close()
