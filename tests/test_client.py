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


def test_calculate_attendance_metrics():
    from open_moodle.client import calculate_attendance_metrics

    # Over threshold (34/44 = 77.27% -> 1 safe bunk)
    m1 = calculate_attendance_metrics(34, 44, threshold=75.0)
    assert m1["status"] == "OK"
    assert m1["percentage"] == 77.27
    assert m1["safe_bunks"] == 1
    assert m1["recovery_needed"] == 0

    # Below threshold (24/43 = 55.81% -> 33 classes needed)
    m2 = calculate_attendance_metrics(24, 43, threshold=75.0)
    assert m2["status"] == "BELOW TARGET"
    assert m2["percentage"] == 55.81
    assert m2["safe_bunks"] == 0
    assert m2["recovery_needed"] == 33

    # Zero sessions
    m3 = calculate_attendance_metrics(0, 0, threshold=75.0)
    assert m3["status"] == "OK"
    assert m3["safe_bunks"] == 0


def test_get_attendance_via_mod_attendance():
    client = MoodleClient("https://lms.college.edu", "secret_tok")
    client._available_functions = {"mod_attendance_get_attendance"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "courses": [
            {
                "courseid": 201,
                "coursename": "Operating Systems",
                "totalsessions": 44,
                "attended": 34,
                "percentage": 77.27,
            }
        ]
    }
    mock_resp.raise_for_status.return_value = None

    with patch.object(client._http, "post", return_value=mock_resp):
        records = client.get_attendance()
        assert len(records) == 1
        assert records[0]["course_name"] == "Operating Systems"
        assert records[0]["attended"] == 34
        assert records[0]["total_sessions"] == 44
        assert records[0]["percentage"] == 77.27

    client.close()


def test_get_attendance_capability_error():
    client = MoodleClient("https://lms.college.edu", "secret_tok")
    client._available_functions = {"core_webservice_get_site_info"}
    client._site_info = {"sitename": "Test"}

    with pytest.raises(CapabilityError, match="Attendance tracking functions"):
        client.get_attendance()

    client.close()

