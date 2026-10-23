"""Configuration and credential management for open-moodle."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".config" / "open-moodle"
CONFIG_FILE = CONFIG_DIR / "config.json"


def normalize_moodle_url(raw_url: str) -> str:
    """Normalize a Moodle URL to ensure it points to the server root or server.php.

    Accepts forms like:
      - https://lms.university.edu
      - https://lms.university.edu/
      - https://lms.university.edu/webservice/rest/server.php
    Returns:
      https://lms.university.edu/webservice/rest/server.php
    """
    clean = raw_url.strip().rstrip("/")
    if not clean.startswith(("http://", "https://")):
        clean = "https://" + clean

    if clean.endswith("/webservice/rest/server.php"):
        return clean

    return f"{clean}/webservice/rest/server.php"


def get_base_url(normalized_url: str) -> str:
    """Extract the base domain URL from a normalized server.php URL."""
    suffix = "/webservice/rest/server.php"
    if normalized_url.endswith(suffix):
        return normalized_url[: -len(suffix)]
    return normalized_url


def load_config() -> dict[str, str]:
    """Load configuration dictionary from disk if available."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_config(url: str, token: str, extra: Optional[dict[str, str]] = None) -> None:
    """Save Moodle credentials to ~/.config/open-moodle/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {
        "url": normalize_moodle_url(url),
        "token": token.strip(),
    }
    if extra:
        payload.update(extra)

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    # Set permissions so only current user can read credentials
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def get_credentials(
    url_override: Optional[str] = None,
    token_override: Optional[str] = None,
) -> tuple[str, str]:
    """Resolve Moodle URL and Token.

    Order of priority:
      1. Explicit arguments
      2. Environment variables (MOODLE_URL, MOODLE_TOKEN)
      3. Stored config file (~/.config/open-moodle/config.json)

    Raises ValueError if credentials cannot be resolved.
    """
    url = url_override or os.environ.get("MOODLE_URL")
    token = token_override or os.environ.get("MOODLE_TOKEN")

    if not url or not token:
        saved = load_config()
        if not url:
            url = saved.get("url")
        if not token:
            token = saved.get("token")

    if not url or not token:
        missing = []
        if not url:
            missing.append("MOODLE_URL")
        if not token:
            missing.append("MOODLE_TOKEN")
        raise ValueError(
            f"Missing required Moodle credentials: {', '.join(missing)}.\n"
            "Set the environment variables, run 'open-moodle login', or pass them as options."
        )

    return normalize_moodle_url(url), token.strip()
