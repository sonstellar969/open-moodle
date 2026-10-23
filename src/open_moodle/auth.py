"""Authentication utilities for acquiring and validating Moodle tokens."""

from __future__ import annotations

from typing import Any
import httpx

from open_moodle.config import get_base_url, normalize_moodle_url


class AuthenticationError(Exception):
    """Raised when authentication with Moodle fails."""
    pass


def request_token(
    site_url: str,
    username: str,
    password: str,
    service: str = "moodle_mobile_app",
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Request a web service token using student or user credentials.

    Hits the standard Moodle mobile token endpoint:
    {base_url}/login/token.php?username=...&password=...&service=moodle_mobile_app

    This works even on installations where /user/managetoken.php is disabled for students.
    """
    clean_url = normalize_moodle_url(site_url)
    base = get_base_url(clean_url)
    token_endpoint = f"{base}/login/token.php"

    data = {
        "username": username.strip(),
        "password": password,
        "service": service,
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            res = client.post(token_endpoint, data=data)
            res.raise_for_status()
            result = res.json()
    except httpx.HTTPError as e:
        raise AuthenticationError(f"HTTP request to token endpoint failed: {e}") from e
    except Exception as e:
        raise AuthenticationError(f"Failed to parse token endpoint response: {e}") from e

    if not isinstance(result, dict):
        raise AuthenticationError(f"Unexpected response structure from {token_endpoint}")

    if "error" in result:
        err_msg = result.get("error", "Unknown error")
        error_code = result.get("errorcode", "")
        if error_code == "invalidlogin":
            raise AuthenticationError("Invalid username or password.")
        if error_code == "servicenotavailable":
            raise AuthenticationError(
                f"Service '{service}' is not enabled on this Moodle installation."
            )
        raise AuthenticationError(f"Token request failed: {err_msg} ({error_code})")

    if "token" not in result:
        raise AuthenticationError(
            f"No token returned by Moodle. Response received: {result}"
        )

    return result


def verify_credentials(
    endpoint_url: str,
    token: str,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Verify that a given URL and token can successfully fetch site info."""
    clean_url = normalize_moodle_url(endpoint_url)
    data = {
        "wstoken": token.strip(),
        "wsfunction": "core_webservice_get_site_info",
        "moodlewsrestformat": "json",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            res = client.post(clean_url, data=data)
            res.raise_for_status()
            body = res.json()
    except Exception as e:
        raise AuthenticationError(f"Connection to Moodle failed: {e}") from e

    if isinstance(body, dict) and body.get("exception"):
        raise AuthenticationError(
            f"Moodle rejected token: {body.get('message', 'Invalid credentials')} "
            f"({body.get('errorcode', '')})"
        )

    if not isinstance(body, dict) or "sitename" not in body:
        raise AuthenticationError("Received unexpected response from Moodle endpoint.")

    return body
