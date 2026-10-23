"""HTTP client for Moodle's REST Web Services API."""

from __future__ import annotations

import time
from typing import Any, Optional
import urllib.parse
import httpx

from open_moodle.config import get_base_url, normalize_moodle_url


class MoodleAPIError(Exception):
    """Raised when Moodle returns an API-level error response."""

    def __init__(self, message: str, errorcode: str = "", exception: str = ""):
        super().__init__(message)
        self.errorcode = errorcode
        self.exception = exception


class CapabilityError(MoodleAPIError):
    """Raised when a requested Moodle Web Service function is disabled on the server."""
    pass


class FileTooLargeError(Exception):
    """Raised when a file download exceeds the allowed memory/byte limit."""
    pass


def strip_token_from_url(url: str) -> str:
    """Remove sensitive token parameters from a Moodle URL before exposing it."""
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    cleaned_qs = [(k, v) for k, v in qs if k.lower() not in ("token", "wstoken")]
    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urllib.parse.urlencode(cleaned_qs),
        parsed.fragment,
    ))


def flatten_moodle_params(params: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Recursively flatten nested dictionaries and lists into PHP bracket notation.

    Converts:
      {"options": {"timestart": 100}} -> {"options[timestart]": 100}
      {"courseids": [10, 20]} -> {"courseids[0]": 10, "courseids[1]": 20}
    """
    items: dict[str, Any] = {}
    for k, v in params.items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            items.update(flatten_moodle_params(v, prefix=key))
        elif isinstance(v, (list, tuple)):
            for idx, item in enumerate(v):
                list_key = f"{key}[{idx}]"
                if isinstance(item, dict):
                    items.update(flatten_moodle_params(item, prefix=list_key))
                else:
                    items[list_key] = item
        else:
            items[key] = v
    return items


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
        self.token = token.strip()
        self._user_id: Optional[int] = None
        self._site_info: Optional[dict[str, Any]] = None
        self._available_functions: Optional[set[str]] = None
        self._http = httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._http.close()

    def __enter__(self) -> MoodleClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def get_available_functions(self) -> set[str]:
        """Fetch and cache the set of functions whitelisted for this token."""
        if self._available_functions is None:
            info = self.get_site_info()
            raw_funcs = info.get("functions", [])
            self._available_functions = {
                f["name"] for f in raw_funcs if isinstance(f, dict) and "name" in f
            }
        return self._available_functions

    def check_capability(self, wsfunction: str) -> None:
        """Verify that the Moodle server allows calling wsfunction.

        Raises CapabilityError if the function is known to be missing from the token's service.
        """
        funcs = self.get_available_functions()
        if funcs and wsfunction not in funcs:
            sitename = self._site_info.get("sitename", "this LMS") if self._site_info else "this LMS"
            raise CapabilityError(
                message=f"Function '{wsfunction}' is not permitted or enabled by {sitename} for this account.",
                errorcode="functionnotpermitted",
            )

    def call(self, wsfunction: str, params: Optional[dict[str, Any]] = None, check_caps: bool = True) -> Any:
        """Invoke a Moodle Web Service function.

        Sends POST request with wstoken, wsfunction, and moodlewsrestformat=json.
        """
        if check_caps and wsfunction != "core_webservice_get_site_info":
            self.check_capability(wsfunction)

        data: dict[str, Any] = {
            "wstoken": self.token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
        }
        if params:
            data.update(flatten_moodle_params(params))

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
        if self._site_info is None:
            info = self.call("core_webservice_get_site_info", check_caps=False)
            if isinstance(info, dict):
                self._site_info = info
                if "userid" in info:
                    self._user_id = info["userid"]
                raw_funcs = info.get("functions", [])
                self._available_functions = {
                    f["name"] for f in raw_funcs if isinstance(f, dict) and "name" in f
                }
        return self._site_info or {}

    def get_user_id(self) -> int:
        """Get current authenticated user's numeric ID."""
        if self._user_id is None:
            info = self.get_site_info()
            self._user_id = info.get("userid", 0)
        return self._user_id

    def get_enrolled_courses(self, user_id: Optional[int] = None) -> list[dict[str, Any]]:
        """Fetch courses the user is actively enrolled in."""
        uid = user_id or self.get_user_id()
        funcs = self.get_available_functions()

        if "core_enrol_get_users_courses" in funcs:
            courses = self.call("core_enrol_get_users_courses", {"userid": uid})
            if isinstance(courses, list):
                return courses

        if "core_course_get_enrolled_courses_by_timeline_classification" in funcs:
            data = self.call("core_course_get_enrolled_courses_by_timeline_classification", {"classification": "all"})
            if isinstance(data, dict) and "courses" in data:
                return data["courses"]

        if "core_course_get_courses_by_field" in funcs:
            data = self.call("core_course_get_courses_by_field", {"field": "id", "value": ""})
            if isinstance(data, dict) and "courses" in data:
                return data["courses"]

        raise CapabilityError("No supported course listing function is enabled for this Moodle account.")

    def get_course_contents(self, course_id: int) -> list[dict[str, Any]]:
        """Fetch the full hierarchical contents of a course with sanitized file URLs."""
        contents = self.call("core_course_get_contents", {"courseid": course_id})
        if not isinstance(contents, list):
            return []

        # Sanitize URLs in-place so secret tokens never leak in outputs
        for section in contents:
            if not isinstance(section, dict):
                continue
            for mod in section.get("modules", []):
                if not isinstance(mod, dict):
                    continue
                if "url" in mod and mod["url"]:
                    mod["url"] = strip_token_from_url(mod["url"])
                for item in mod.get("contents", []):
                    if isinstance(item, dict) and "fileurl" in item and item["fileurl"]:
                        item["fileurl"] = strip_token_from_url(item["fileurl"])

        return contents

    def get_upcoming_events(self, days_ahead: int = 30) -> list[dict[str, Any]]:
        """Fetch action events and calendar deadlines within the next N days."""
        now = int(time.time())
        funcs = self.get_available_functions()

        if "core_calendar_get_action_events_by_timesort" in funcs:
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

        if "core_calendar_get_calendar_events" in funcs:
            # Encoded properly via flatten_moodle_params into options[timestart], etc.
            res = self.call(
                "core_calendar_get_calendar_events",
                {
                    "events": {"courseids": []},
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

        raise CapabilityError("Calendar functions are disabled on this Moodle server.")

    def get_submission_status(self, assign_id: int) -> dict[str, Any]:
        """Fetch the user's submission state for a specific assignment."""
        funcs = self.get_available_functions()
        if "mod_assign_get_submission_status" not in funcs:
            return {"status": "unknown (api disabled)", "graded": False}

        try:
            res = self.call("mod_assign_get_submission_status", {"assignid": assign_id})
            if not isinstance(res, dict):
                return {"status": "unknown"}

            last_attempt = res.get("lastattempt", {})
            status = last_attempt.get("status", "new")
            feedback = res.get("feedback", {})
            graded = feedback.get("grade") is not None or feedback.get("gradefordisplay") is not None

            return {
                "status": status,  # submitted, draft, new, reloaded
                "graded": graded,
                "timemodified": last_attempt.get("timemodified", 0),
                "locked": last_attempt.get("locked", False),
            }
        except MoodleAPIError:
            return {"status": "unavailable"}

    def get_assignments(
        self,
        course_ids: Optional[list[int]] = None,
        include_submission_status: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetch assignments and attach submission status for each."""
        params: dict[str, Any] = {}
        if course_ids:
            params["courseids"] = course_ids

        data = self.call("mod_assign_get_assignments", params)
        if not isinstance(data, dict) or "courses" not in data:
            return []

        all_assignments: list[dict[str, Any]] = []
        for course_entry in data["courses"]:
            c_title = course_entry.get("fullname", "")
            c_id = course_entry.get("id", 0)
            for assign in course_entry.get("assignments", []):
                assign["course_title"] = c_title
                assign["course_id"] = c_id

                if include_submission_status and "id" in assign:
                    assign["submission"] = self.get_submission_status(assign["id"])

                all_assignments.append(assign)

        return all_assignments

    def get_user_grades(self, course_id: int = 0) -> list[dict[str, Any]]:
        """Fetch grade items and scores for a course (or all courses)."""
        funcs = self.get_available_functions()
        if "gradereport_user_get_grade_items" not in funcs:
            raise CapabilityError("Grade report API (gradereport_user_get_grade_items) is not enabled.")

        uid = self.get_user_id()
        params: dict[str, Any] = {"userid": uid}
        if course_id > 0:
            params["courseid"] = course_id

        res = self.call("gradereport_user_get_grade_items", params)
        if isinstance(res, dict) and "usergrades" in res:
            return res["usergrades"]
        return []

    def get_course_announcements(self, course_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch actual teacher posts from the course Announcements/News forum."""
        funcs = self.get_available_functions()
        if "mod_forum_get_forums_by_courses" not in funcs or "mod_forum_get_forum_discussions" not in funcs:
            raise CapabilityError("Forum web services are not enabled on this Moodle installation.")

        forums = self.call("mod_forum_get_forums_by_courses", {"courseids": [course_id]})
        if not isinstance(forums, list):
            return []

        # Find the announcements forum (typically type 'news' or named Announcements)
        news_forum = None
        for f in forums:
            if f.get("type") == "news" or "announcement" in f.get("name", "").lower():
                news_forum = f
                break

        if not news_forum:
            # Fall back to first available forum
            news_forum = forums[0] if forums else None

        if not news_forum:
            return []

        forum_id = news_forum["id"]
        res = self.call(
            "mod_forum_get_forum_discussions",
            {
                "forumid": forum_id,
                "sortorder": 1,
                "page": 0,
                "perpage": limit,
            },
        )
        if isinstance(res, dict) and "discussions" in res:
            return res["discussions"]
        return []

    def get_notifications(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch recent system bell notifications."""
        uid = self.get_user_id()
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
        return []

    def download_file(self, file_url: str, max_bytes: int = 25 * 1024 * 1024) -> bytes:
        """Download a file with streaming and a strict byte limit.

        Appends ?token=... to the request URL if absent, but keeps the token
        confined to this internal method.
        """
        target_url = file_url
        if "token=" not in target_url:
            separator = "&" if "?" in target_url else "?"
            target_url = f"{target_url}{separator}token={self.token}"

        headers = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "open-moodle/0.1.0 (Python)",
        }

        with self._http.stream("GET", target_url, headers=headers) as res:
            res.raise_for_status()
            content = bytearray()
            for chunk in res.iter_bytes(chunk_size=65536):
                content.extend(chunk)
                if len(content) > max_bytes:
                    limit_mb = max_bytes // (1024 * 1024)
                    raise FileTooLargeError(
                        f"File exceeds maximum download size limit of {limit_mb}MB."
                    )
            return bytes(content)
