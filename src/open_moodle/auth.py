"""Authentication utilities for acquiring and validating Moodle tokens."""

from __future__ import annotations

import base64
import hashlib
import http.server
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional
import urllib.parse
import webbrowser
import httpx

from open_moodle.client import install_log_redaction, redact_secrets
from open_moodle.config import get_base_url, normalize_moodle_url

URL_SCHEME = "openmoodle"


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

    install_log_redaction()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            res = client.post(token_endpoint, data=data)
            res.raise_for_status()
            result = res.json()
    except httpx.HTTPError as e:
        raise AuthenticationError(f"HTTP request to token endpoint failed: {redact_secrets(str(e))}") from None
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
        raise AuthenticationError(f"Connection to Moodle failed: {redact_secrets(str(e))}") from None

    if isinstance(body, dict) and body.get("exception"):
        raise AuthenticationError(
            f"Moodle rejected token: {body.get('message', 'Invalid credentials')} "
            f"({body.get('errorcode', '')})"
        )

    if not isinstance(body, dict) or "sitename" not in body:
        raise AuthenticationError("Received unexpected response from Moodle endpoint.")

    return body


def extract_token_from_callback(
    raw_input: str,
    passport: str = "",
    site_url: str = "",
) -> Optional[str]:
    """Extract a Moodle web service token from a launch URL or raw token.

    Moodle redirects to ``<scheme>://token=<base64>``. The payload is
    ``md5(wwwroot + passport):::wstoken`` and may include ``:::privatetoken``.
    When a passport is supplied, the first field must match that digest.
    The web service token is the second field, never the private token.
    """
    text = urllib.parse.unquote(raw_input.strip())
    if not text:
        return None

    if re.fullmatch(r"[a-fA-F0-9]{32}", text):
        if passport:
            return None
        return text

    candidate = text
    matched = re.search(r"token=([^&#\s]+)", text)
    if matched:
        candidate = urllib.parse.unquote(matched.group(1))

    decoded = _b64_text(candidate)
    if decoded and ":::" in decoded:
        parts = [part.strip() for part in decoded.split(":::")]
        if passport:
            expected = _passport_digests(site_url, passport)
            if parts[0] not in expected and parts[0] != passport:
                return None
        if len(parts) >= 2 and re.fullmatch(r"[a-fA-F0-9]{32}", parts[1]):
            return parts[1]
        return None

    if passport:
        return None
    if re.fullmatch(r"[a-fA-F0-9]{32}", candidate):
        return candidate
    return None


def _b64_text(value: str) -> str:
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.b64decode(padded).decode("utf-8")
    except Exception:
        return ""


def _passport_digests(site_url: str, passport: str) -> set[str]:
    """Moodle's site id is md5(wwwroot + passport). Try the likely wwwroot forms."""
    base = get_base_url(normalize_moodle_url(site_url)) if site_url else ""
    roots = {base, base.rstrip("/"), f"{base.rstrip('/')}/"}
    return {hashlib.md5((root + passport).encode("utf-8")).hexdigest() for root in roots if root}


def login_sso(
    site_url: str,
    timeout: float = 120.0,
    service: str = "moodle_mobile_app",
) -> tuple[str, str]:
    """Perform browser-assisted SSO login and capture the token.

    Moodle only accepts a custom URL scheme (letters, digits, ``+``, ``.``, ``-``).
    It redirects to ``openmoodle://token=<base64>``. This registers a temporary
    handler that forwards that URL to a localhost listener, and also accepts a
    pasted launch link. The passport digest must match before the token is kept.

    Returns tuple of (token, launch_url).
    """
    clean_url = normalize_moodle_url(site_url)
    base = get_base_url(clean_url)
    passport = secrets.token_hex(16)

    captured: list[str] = []
    shutdown_event = threading.Event()

    class SSOHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            qs = dict(urllib.parse.parse_qsl(parsed.query))
            raw = qs.get("url") or qs.get("token") or ""
            extracted = extract_token_from_callback(raw, passport=passport, site_url=base)
            if not extracted:
                self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Token rejected. The passport did not match this login.")
                return
            captured.append(extracted)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_SUCCESS_PAGE)
            shutdown_event.set()

    server = http.server.HTTPServer(("127.0.0.1", 0), SSOHandler)
    server.timeout = 0.5
    port = server.server_port
    launch_url = (
        f"{base}/admin/tool/mobile/launch.php?"
        + urllib.parse.urlencode({
            "service": service,
            "passport": passport,
            "urlscheme": URL_SCHEME,
            "confirmed": 1,
        })
    )

    def serve() -> None:
        while not shutdown_event.is_set():
            server.handle_request()

    listener = threading.Thread(target=serve, daemon=True)
    listener.start()
    cleanup = _register_scheme_handler(port)
    print(
        "Complete campus login in the browser.\n"
        f"Moodle opens an {URL_SCHEME}:// link. If your system does not capture it, paste that link and press Enter.",
        flush=True,
    )
    try:
        webbrowser.open(launch_url)
    except Exception:
        pass

    def _read_paste() -> None:
        if not sys.stdin.isatty():
            return
        try:
            pasted = sys.stdin.readline()
        except Exception:
            return
        extracted = extract_token_from_callback(pasted, passport=passport, site_url=base)
        if extracted:
            captured.append(extracted)
            shutdown_event.set()

    if sys.stdin.isatty():
        threading.Thread(target=_read_paste, daemon=True).start()

    deadline = time.time() + timeout
    try:
        while time.time() < deadline and not shutdown_event.is_set():
            time.sleep(0.3)
    finally:
        server.server_close()
        cleanup()

    if captured:
        return captured[0], launch_url
    raise AuthenticationError(
        "SSO login timed out. Paste the openmoodle://token=... link from the Moodle page, "
        "or pass a token with open-moodle login --token."
    )


_SUCCESS_PAGE = b"""<!DOCTYPE html>
<html><head><title>Moodle Login Success</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; align-items: center; justify-content: center; height: 80vh; margin: 0; background: #f8fafc;">
<div style="background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,.1); text-align: center; max-width: 450px;">
<h2 style="color: #16a34a; margin-top: 0;">Authentication Successful</h2>
<p style="color: #475569;">open-moodle has received your token. You may close this tab and return to your terminal.</p>
</div></body></html>"""


def _register_scheme_handler(port: int) -> Callable[[], None]:
    """Register a temporary openmoodle:// handler. Return a cleanup callable."""
    try:
        if sys.platform == "darwin":
            return _register_macos(port)
        if sys.platform.startswith("linux"):
            return _register_linux(port)
        if sys.platform == "win32":
            return _register_windows(port)
    except Exception:
        pass
    return lambda: None


def _handler_script(port: int, directory: Path) -> Path:
    script = directory / "forward_sso.py"
    script.write_text(
        "import sys, urllib.parse, urllib.request\n"
        "raw = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        f"query = urllib.parse.urlencode({{'url': raw}})\n"
        f"urllib.request.urlopen('http://127.0.0.1:{port}/callback?' + query, timeout=10).read()\n",
        encoding="utf-8",
    )
    script.chmod(0o700)
    return script


def _register_macos(port: int) -> Callable[[], None]:
    directory = Path(tempfile.mkdtemp(prefix="open-moodle-sso-"))
    script = _handler_script(port, directory)
    app = directory / "OpenMoodleSSO.app"
    python = sys.executable
    source = (
        "on open location theURL\n"
        f'  do shell script quoted form of "{python}" & " " & '
        f'quoted form of "{script}" & " " & quoted form of theURL\n'
        "end open location\n"
    )
    subprocess.run(["osacompile", "-o", str(app)], input=source, text=True, check=True)
    info = app / "Contents" / "Info.plist"
    with info.open("rb") as handle:
        plist = plistlib.load(handle)
    plist["CFBundleIdentifier"] = "dev.openmoodle.sso"
    plist["CFBundleURLTypes"] = [{
        "CFBundleURLName": "open-moodle SSO",
        "CFBundleURLSchemes": [URL_SCHEME],
    }]
    with info.open("wb") as handle:
        plistlib.dump(plist, handle)
    lsregister = (
        "/System/Library/Frameworks/CoreServices.framework/"
        "Frameworks/LaunchServices.framework/Support/lsregister"
    )
    subprocess.run([lsregister, "-f", str(app)], check=False)

    def cleanup() -> None:
        subprocess.run([lsregister, "-u", str(app)], check=False)
        shutil.rmtree(directory, ignore_errors=True)

    return cleanup


def _register_linux(port: int) -> Callable[[], None]:
    directory = Path(tempfile.mkdtemp(prefix="open-moodle-sso-"))
    script = _handler_script(port, directory)
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    desktop = apps / "open-moodle-sso.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=open-moodle SSO\n"
        "NoDisplay=true\n"
        f"Exec={sys.executable} {script} %u\n"
        f"MimeType=x-scheme-handler/{URL_SCHEME};\n",
        encoding="utf-8",
    )
    subprocess.run(["xdg-mime", "default", desktop.name, f"x-scheme-handler/{URL_SCHEME}"], check=False)

    def cleanup() -> None:
        desktop.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)

    return cleanup


def _register_windows(port: int) -> Callable[[], None]:
    directory = Path(tempfile.mkdtemp(prefix="open-moodle-sso-"))
    script = _handler_script(port, directory)
    command = f'"{sys.executable}" "{script}" "%1"'
    key = r"HKCU\Software\Classes\openmoodle"
    subprocess.run(["reg", "add", key, "/ve", "/d", "URL:open-moodle", "/f"], check=False)
    subprocess.run(["reg", "add", key, "/v", "URL Protocol", "/d", "", "/f"], check=False)
    subprocess.run(["reg", "add", key + r"\shell\open\command", "/ve", "/d", command, "/f"], check=False)

    def cleanup() -> None:
        subprocess.run(["reg", "delete", key, "/f"], check=False)
        shutil.rmtree(directory, ignore_errors=True)

    return cleanup

