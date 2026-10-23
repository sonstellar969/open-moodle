"""HTTP client for Moodle's REST Web Services API."""

from __future__ import annotations

import time
from typing import Any, Optional
import httpx

from open_moodle.config import get_base_url, normalize_moodle_url


class MoodleAPIError(Exception):
    """Raised when Moodle returns an API-level error response."""

    def __init__(self, message: str, errorcode: str = "", exception: str = ""):
        super().__init__(message)
        self.errorcode = errorcode
        self.exception = exception


class MoodleClient:
    """Interface to Moodle REST web services."""

    def __init__(
        self,
        endpoint_url: str,
        token: str,
        timeout: float = 30.0,
    ):
        self.endpoint_url = normalize_moodle_url(endpoint_url)
        self.base_url = get_base_url(self.endpoint_url)
        self.token = token
        self._user_id: Optional[int] = None
        self._http = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._http.close()

    def __enter__(self) -> MoodleClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def call(self, wsfunction: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Invoke a Moodle Web Service function.

        Sends POST request with wstoken, wsfunction, and moodlewsrestformat=json.
        """
        data: dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
        }
        if params:
            data.update(params)

        response = self._http.post(self.endpoint_url, data=data)
        response.raise_for_status()

        result = response.json()
        if isinstance(result, dict) and result.get("exception"):
            raise MoodleAPIError(
                message=result.get("message", "Unknown Moodle error"),
                errorcode=result.get("errorcode", ""),
                exception=result.get("exception", ""),
            )

        return result

    def get_site_info(self) -> dict[str, Any]:
        """Fetch general site information and verify user authentication."""
        info = self.call("core_webservice_get_site_info")
        if isinstance(info, dict) and "userid" in info:
            self._user_id = info["userid"]
        return info

    def get_user_id(self) -> int:
        """Get the current authenticated user's ID, fetching site info if not cached."""
        if self._user_id is None:
            info = self.get_site_info()
            self._user_id = info.get("userid", 0)
        return self._user_id

    def get_enrolled_courses(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Fetch courses the user is actively enrolled in."""
        uid = user_id or self.get_user_id()
        try:
            courses = self.call("core_enrol_get_users_courses", {"userid": uid})
            if isinstance(courses, list):
                return courses
        except MoodleAPIError:
            pass

        # Fallback to general course list if enrolment function is restricted
        courses_data = self.call("core_course_get_courses_by_field", {"field": "id", "value": ""})
        if isinstance(courses_data, dict) and "courses" in courses_data:
            return courses_data["courses"]
        return []

    def get_course_contents(self, course_id: int) -> list[dict[str, Any]]:
        """Fetch the full hierarchical contents of a course (sections, modules, files)."""
        contents = self.call("core_course_get_contents", {"courseid": course_id})
        if isinstance(contents, list):
            return contents
        return []

    def get_upcoming_events(self, days_ahead: int = 30) -> list[dict[str, Any]]:
        """Fetch action events and calendar deadlines within the next N days."""
        now = int(time.time())
        try:
            res = self.call(
                "core_calendar_get_action_events_by_timesort",
                {
                    "timesortfrom": now - 3600,
                    "timesortto": now + (days_ahead * 86400),
                    "limitnum": 50,
                },
            )
            if isinstance(res, dict) and "events" in res:
                return res["events"]
        except MoodleAPIError:
            pass

        # Fallback to standard calendar events
        try:
            res = self.call(
                "core_calendar_get_calendar_events",
                {
                    "events": {
                        "courseids": [],
                        "groupids": [],
                        "categoryids": [],
                    },
                    "options": {
                        "userevents": 1,
                        "siteevents": 1,
                        "timestart": now - 3600,
                        "timeend": now + (days_ahead * 86400),
                    },
                },
            )
            if isinstance(res, dict) and "events" in res:
                return res["events"]
        except MoodleAPIError:
            pass

        return []

    def get_assignments(self, course_ids: Optional[list[int]] = None) -> list[dict[str, Any]]:
        """Fetch assignments for specified courses or all enrolled courses."""
        params: dict[str, Any] = {}
        if course_ids:
            for idx, cid in enumerate(course_ids):
                params[f"courseids[{idx}]"] = cid

        try:
            data = self.call("mod_assign_get_assignments", params)
            if isinstance(data, dict) and "courses" in data:
                all_assignments = []
                for course_entry in data["courses"]:
                    c_title = course_entry.get("fullname", "")
                    c_id = course_entry.get("id", 0)
                    for assign in course_entry.get("assignments", []):
                        assign["course_title"] = c_title
                        assign["course_id"] = c_id
                        all_assignments.append(assign)
                return all_assignments
        except MoodleAPIError:
            pass

        return []

    def get_notifications(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent popup notifications and announcements."""
        uid = self.get_user_id()
        try:
            res = self.call(
                "message_popup_get_popup_notifications",
                {
                    "useridto": uid,
                    "limit": limit,
                    "offset": 0,
                },
            )
            if isinstance(res, dict) and "notifications" in res:
                return res["notifications"]
        except MoodleAPIError:
            pass

        return []

    def download_file(self, file_url: str) -> bytes:
        """Download a file from Moodle using token authentication.

        Appends ?token=... to the URL if not already present, ensuring
        authenticated downloads from pluginfile.php and webservice endpoints.
        """
        target_url = file_url
        if "token=" not in target_url:
            separator = "&" if "?" in target_url else "?"
            target_url = f"{target_url}{separator}token={self.token}"

        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "open-moodle/0.1.0 (Python)",
        }
        res = self._http.get(target_url, headers=headers)
        res.raise_for_status()
        return res.content
