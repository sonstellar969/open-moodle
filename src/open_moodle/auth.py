"""Authentication utilities for acquiring and validating Moodle tokens."""

from __future__ import annotations

import base64
import http.server
import re
import secrets
import threading
import time
from typing import Any, Optional
import urllib.parse
import webbrowser
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


def extract_token_from_callback(raw_input: str, passport: str = "") -> Optional[str]:
    """Extract and decode a Moodle mobile token from callback URL or token string."""
    text = raw_input.strip()
    if not text:
        return None

    # Check if raw input is already a 32-character hex token
    if re.fullmatch(r"[a-fA-F0-9]{32}", text):
        return text

    # Parse query or fragment from URL
    candidate = text
    if "token=" in text:
        m = re.search(r"token=([^&#\s]+)", text)
        if m:
            candidate = m.group(1)

    # Try decoding base64 if it looks like passport:::token or siteurl:::token
    try:
        padded = candidate + "=" * (-len(candidate) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        if ":::" in decoded:
            parts = decoded.split(":::")
            for part in reversed(parts):
                clean_part = part.strip()
                if re.fullmatch(r"[a-fA-F0-9]{32}", clean_part):
                    return clean_part
            if parts[-1].strip():
                return parts[-1].strip()
    except Exception:
        pass

    if re.fullmatch(r"[a-fA-F0-9]{32}", candidate):
        return candidate

    return candidate or None


def login_sso(
    site_url: str,
    timeout: float = 120.0,
    service: str = "moodle_mobile_app",
) -> tuple[str, str]:
    """Perform browser-assisted SSO login and capture token.

    Returns tuple of (token, launch_url).
    """
    clean_url = normalize_moodle_url(site_url)
    base = get_base_url(clean_url)
    passport = secrets.token_hex(16)

    captured_token: list[str] = []
    shutdown_event = threading.Event()

    class SSOHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            qs = dict(urllib.parse.parse_qsl(parsed.query))
            token_candidate = qs.get("token") or ""

            extracted = extract_token_from_callback(token_candidate, passport=passport)
            if extracted:
                captured_token.append(extracted)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """
                <!DOCTYPE html>
                <html>
                <head><title>Moodle Login Success</title></head>
                <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 80vh; margin: 0; background: #f8fafc;">
                    <div style="background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); text-align: center; max-width: 450px;">
                        <h2 style="color: #16a34a; margin-top: 0;">Authentication Successful</h2>
                        <p style="color: #475569;">open-moodle has received your token. You may close this tab and return to your terminal.</p>
                    </div>
                </body>
                </html>
                """
                self.wfile.write(html.strip().encode("utf-8"))
                shutdown_event.set()
            else:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"No valid token found in callback request.")

    server = http.server.HTTPServer(("127.0.0.1", 0), SSOHandler)
    server.timeout = 1.0
    port = server.server_port

    callback_url = f"http://127.0.0.1:{port}/callback"
    launch_url = (
        f"{base}/admin/tool/mobile/launch.php?"
        f"service={service}&passport={passport}&urlscheme={urllib.parse.quote(callback_url)}"
    )

    def serve():
        while not shutdown_event.is_set():
            server.handle_request()

    listener_thread = threading.Thread(target=serve, daemon=True)
    listener_thread.start()

    try:
        webbrowser.open(launch_url)
    except Exception:
        pass

    start_time = time.time()
    try:
        while time.time() - start_time < timeout:
            if shutdown_event.is_set() and captured_token:
                return captured_token[0], launch_url
            time.sleep(0.5)
    finally:
        server.server_close()

    if captured_token:
        return captured_token[0], launch_url

    raise AuthenticationError("SSO login timed out waiting for browser callback.")

