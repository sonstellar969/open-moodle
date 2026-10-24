"""HTTP client for Moodle's REST Web Services API."""

from __future__ import annotations

import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
import urllib.parse
import httpx

from open_moodle.config import get_base_url, normalize_moodle_url

_TOKEN_IN_TEXT = re.compile(r"(?i)\b(token|wstoken)=([^&\s\"']+)")
_REDACT_INSTALLED = False


class _RedactTokenFilter(logging.Filter):
    """Drop token values from log lines emitted by HTTP libraries."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            record.args = tuple(
                redact_secrets(arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


def install_log_redaction() -> None:
    """Attach a token redaction filter without changing global log levels."""
    global _REDACT_INSTALLED
    if _REDACT_INSTALLED:
        return
    token_filter = _RedactTokenFilter()
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).addFilter(token_filter)
    _REDACT_INSTALLED = True


def redact_secrets(text: str) -> str:
    """Replace token query values so secrets do not land in output or logs."""
    if not text:
        return ""
    return _TOKEN_IN_TEXT.sub(r"\1=REDACTED", text)


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


class UnsafeDownloadError(Exception):
    """Raised when a download URL is outside this Moodle site."""
    pass


def calculate_attendance_metrics(attended: int, total: int, threshold: float = 75.0) -> dict[str, Any]:
    """Calculate attendance percentage, safe bunks, or classes needed to hit target threshold."""
    if total <= 0:
        return {
            "percentage": 100.0,
            "status": "OK",
            "safe_bunks": 0,
            "recovery_needed": 0,
            "recovery_possible": True,
        }

    pct = round((attended / total) * 100.0, 2)
    t_ratio = threshold / 100.0

    if pct >= threshold:
        # Maximum additional sessions a student can miss: (attended / (total + k)) >= t_ratio
        if t_ratio > 0:
            safe = int((attended - (t_ratio * total)) / t_ratio)
        else:
            safe = 0
        return {
            "percentage": pct,
            "status": "OK",
            "safe_bunks": max(0, safe),
            "recovery_needed": 0,
            "recovery_possible": True,
        }

    # A 100% target is unreachable once any session has already been missed.
    if t_ratio >= 1.0:
        return {
            "percentage": pct,
            "status": "BELOW TARGET",
            "safe_bunks": 0,
            "recovery_needed": None,
            "recovery_possible": False,
        }

    needed = math.ceil(((t_ratio * total) - attended) / (1.0 - t_ratio))
    return {
        "percentage": pct,
        "status": "BELOW TARGET",
        "safe_bunks": 0,
        "recovery_needed": max(0, needed),
        "recovery_possible": True,
    }


def _grade_percentage(item: dict[str, Any]) -> Optional[float]:
    """Read a grade item's percentage without treating points as session counts."""
    raw_text = str(item.get("percentageformatted") or "").replace("%", "").replace(",", "").strip()
    if raw_text and raw_text not in {"-", "–"}:
        try:
            return round(float(raw_text), 2)
        except ValueError:
            pass
    raw = item.get("graderaw")
    maximum = item.get("grademax")
    try:
        if raw is not None and maximum not in (None, 0, "0"):
            return round((float(raw) / float(maximum)) * 100.0, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


def format_attendance_detail(record: dict[str, Any], threshold: float = 75.0) -> dict[str, Any]:
    """Describe one attendance row for CLI and MCP output.

    Session math runs only when attended and total_sessions are real counts.
    Gradebook rows compare the percentage with the threshold and say why bunks
    are omitted.
    """
    if record.get("sessions_known") and record.get("total_sessions"):
        metrics = calculate_attendance_metrics(
            int(record["attended"]),
            int(record["total_sessions"]),
            threshold=threshold,
        )
        if metrics["status"] == "OK":
            if metrics["safe_bunks"] > 0:
                detail = f"+{metrics['safe_bunks']} safe bunks"
            else:
                detail = "On track"
        elif not metrics["recovery_possible"]:
            detail = "Cannot reach this target after a missed session"
        else:
            detail = f"Needs {metrics['recovery_needed']} classes"
        return {
            "percentage": metrics["percentage"],
            "status": metrics["status"],
            "detail": detail,
            "metrics": metrics,
        }

    percentage = record.get("percentage")
    if percentage is None:
        return {
            "percentage": None,
            "status": "UNKNOWN",
            "detail": "No percentage available",
            "metrics": None,
        }
    status = "OK" if float(percentage) >= threshold else "BELOW TARGET"
    return {
        "percentage": percentage,
        "status": status,
        "detail": "Gradebook percentage. Session counts are unavailable, so safe bunks are not calculated.",
        "metrics": None,
    }


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
        install_log_redaction()
        self._http = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "open-moodle (Python)"},
        )

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
                message=redact_secrets(str(result.get("message", "Unknown Moodle error"))),
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

        raise CapabilityError(
            "No supported course listing function is enabled for this Moodle account. "
            "Need core_enrol_get_users_courses or "
            "core_course_get_enrolled_courses_by_timeline_classification."
        )

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
                all_assignments.append(assign)

        if include_submission_status and all_assignments:
            def _attach(assign: dict[str, Any]) -> None:
                if "id" in assign:
                    assign["submission"] = self.get_submission_status(assign["id"])

            workers = min(4, len(all_assignments))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(_attach, all_assignments))

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

    def _allowed_download_url(self, file_url: str) -> str:
        """Return a URL only when it is a pluginfile on this Moodle host."""
        parsed = urllib.parse.urlsplit(file_url.strip())
        site = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise UnsafeDownloadError("Refusing a file URL that is not http(s).")
        if parsed.hostname is None or parsed.hostname.lower() != (site.hostname or "").lower():
            raise UnsafeDownloadError(
                "Refusing to download a file from a host other than the configured Moodle site. "
                "That request would have sent your token to the other host."
            )
        if parsed.port != site.port and not (
            parsed.port in (None, 80, 443) and site.port in (None, 80, 443)
        ):
            raise UnsafeDownloadError("Refusing a file URL on a different port than the Moodle site.")
        if "pluginfile.php" not in parsed.path:
            raise UnsafeDownloadError(
                "Refusing a file URL that is not a Moodle pluginfile.php path."
            )
        return urllib.parse.urlunsplit(parsed)

    def download_file(self, file_url: str, max_bytes: int = 25 * 1024 * 1024) -> bytes:
        """Download a pluginfile with streaming and a strict byte limit.

        The token is appended only after the URL is checked against this site.
        It stays inside this method and is stripped from raised errors.
        """
        checked = self._allowed_download_url(file_url)
        parsed = urllib.parse.urlsplit(checked)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not any(key.lower() in ("token", "wstoken") for key, _ in query):
            query.append(("token", self.token))
        target_url = urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            "",
        ))

        try:
            with self._http.stream("GET", target_url) as res:
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
        except UnsafeDownloadError:
            raise
        except FileTooLargeError:
            raise
        except httpx.HTTPError as exc:
            raise MoodleAPIError(redact_secrets(str(exc))) from None

    def describe_capabilities(self) -> str:
        """Report which student features this token's web service allows."""
        funcs = self.get_available_functions()
        info = self._site_info or {}
        checks = [
            ("Courses", [
                "core_enrol_get_users_courses",
                "core_course_get_enrolled_courses_by_timeline_classification",
            ]),
            ("Course contents", ["core_course_get_contents"]),
            ("Calendar", [
                "core_calendar_get_action_events_by_timesort",
                "core_calendar_get_calendar_events",
            ]),
            ("Assignments", ["mod_assign_get_assignments"]),
            ("Submission status", ["mod_assign_get_submission_status"]),
            ("Grades", ["gradereport_user_get_grade_items"]),
            ("Forums", [
                "mod_forum_get_forums_by_courses",
                "mod_forum_get_forum_discussions",
            ]),
            ("Notifications", ["message_popup_get_popup_notifications"]),
            ("Attendance sessions", ["mod_attendance_get_sessions"]),
        ]
        lines = [
            f"Site: {info.get('sitename', '')}",
            f"User: {info.get('fullname', '')} (id {info.get('userid', '')})",
            f"Whitelisted functions: {len(funcs)}",
            "",
        ]
        for label, names in checks:
            enabled = [name for name in names if name in funcs]
            if enabled:
                lines.append(f"[available] {label}: {', '.join(enabled)}")
            else:
                lines.append(f"[missing]   {label}: none of {', '.join(names)}")
        lines.append("")
        if "mod_attendance_get_sessions" in funcs:
            lines.append(
                "Attendance sessions are listed for this token. That Moodle function "
                "requires a teacher capability, so student marks still come from the gradebook."
            )
        else:
            lines.append(
                "Student tokens do not include a session register. Attendance percentages "
                "come from gradebook items whose name contains 'attendance'. "
                "Safe-bunk math needs real session counts and stays off."
            )
        return "\n".join(lines)

    def get_attendance(self) -> list[dict[str, Any]]:
        """Fetch attendance as gradebook percentages.

        The attendance plugin's web services (mod_attendance_get_sessions and
        friends) are teacher functions. They do not return the current student's
        session tally. Grade items are reported as percentages only. Point values
        are not treated as classes held or classes attended.
        """
        funcs = self.get_available_functions()
        if "gradereport_user_get_grade_items" not in funcs:
            raise CapabilityError(
                "Grade report API (gradereport_user_get_grade_items) is not enabled, "
                "and student tokens cannot read the attendance session register."
            )

        user_grades = self.get_user_grades()
        records: list[dict[str, Any]] = []
        for ug in user_grades:
            c_id = ug.get("courseid", 0)
            course_name = ug.get("coursefullname") or f"Course {c_id}"
            for item in ug.get("gradeitems", []):
                item_name = item.get("itemname") or ""
                if "attendance" not in item_name.lower():
                    continue
                percentage = _grade_percentage(item)
                if percentage is None:
                    continue
                records.append({
                    "course_id": c_id,
                    "course_name": course_name,
                    "item_name": item_name,
                    "percentage": percentage,
                    "attended": None,
                    "total_sessions": None,
                    "sessions_known": False,
                    "source": "gradebook",
                })

        if records:
            return records

        raise CapabilityError(
            "No gradebook item named attendance was found. "
            "Session counts are not available to this student token, so safe bunks cannot be calculated."
        )

