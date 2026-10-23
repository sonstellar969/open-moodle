"""Tests for authentication token requests and verification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from open_moodle.auth import AuthenticationError, request_token, verify_credentials


def test_request_token_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "token": "valid_token_123",
        "privatetoken": "private_456",
    }
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        res = request_token("https://lms.college.edu", "student123", "password")
        assert res["token"] == "valid_token_123"


def test_request_token_invalid_login_raises():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "error": "Invalid login, please try again",
        "errorcode": "invalidlogin",
    }
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(AuthenticationError, match="Invalid username or password"):
            request_token("https://lms.college.edu", "student123", "wrong_pass")


def test_verify_credentials_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "sitename": "University LMS",
        "fullname": "John Doe",
        "userid": 42,
    }
    mock_resp.raise_for_status.return_value = None

    with patch("httpx.Client.post", return_value=mock_resp):
        info = verify_credentials("https://lms.college.edu", "valid_token")
        assert info["sitename"] == "University LMS"
        assert info["fullname"] == "John Doe"
