"""Tests for configuration resolution and credential management."""

from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from open_moodle.config import (
    get_base_url,
    get_credentials,
    normalize_moodle_url,
    save_config,
)


def test_normalize_moodle_url_variants():
    assert (
        normalize_moodle_url("https://lms.college.edu")
        == "https://lms.college.edu/webservice/rest/server.php"
    )
    assert (
        normalize_moodle_url("https://lms.college.edu/")
        == "https://lms.college.edu/webservice/rest/server.php"
    )
    assert (
        normalize_moodle_url("lms.college.edu")
        == "https://lms.college.edu/webservice/rest/server.php"
    )
    assert (
        normalize_moodle_url("https://lms.college.edu/webservice/rest/server.php")
        == "https://lms.college.edu/webservice/rest/server.php"
    )


def test_get_base_url():
    assert (
        get_base_url("https://lms.college.edu/webservice/rest/server.php")
        == "https://lms.college.edu"
    )
    assert get_base_url("https://lms.college.edu") == "https://lms.college.edu"


def test_get_credentials_via_args():
    url, token = get_credentials("https://arg.edu", "arg_token")
    assert url == "https://arg.edu/webservice/rest/server.php"
    assert token == "arg_token"


def test_get_credentials_via_env():
    with patch.dict(
        os.environ,
        {"MOODLE_URL": "https://env.edu", "MOODLE_TOKEN": "env_token"},
        clear=True,
    ):
        url, token = get_credentials()
        assert url == "https://env.edu/webservice/rest/server.php"
        assert token == "env_token"


def test_get_credentials_missing_raises():
    with patch.dict(os.environ, {}, clear=True):
        with patch("open_moodle.config.load_config", return_value={}):
            with pytest.raises(ValueError, match="Missing required Moodle credentials"):
                get_credentials()
