# Moodle Web Services API Reference

This document outlines the standard Moodle REST web service functions used by `open-moodle`.

---

## Endpoint Overview

All API requests are sent as HTTP `POST` requests to:

```
https://lms.university.edu/webservice/rest/server.php
```

Every request includes three mandatory query or form parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `wstoken` | string | 32-character authentication token |
| `wsfunction` | string | Target Moodle function name |
| `moodlewsrestformat` | string | Output format, typically `json` |

---

## Core Functions Used

### 1. `core_webservice_get_site_info`

Fetches user metadata, university site title, Moodle release version, and whitelisted API functions.

**Parameters:** None

**Key return fields:**
- `sitename`: Institution or portal title
- `username`: Student login ID
- `fullname`: Student display name
- `userid`: Numeric user identifier
- `release`: Installed Moodle release string
- `functions`: Array of permitted function names

---

### 2. `core_enrol_get_users_courses`

Fetches all courses in which a specific student is actively enrolled.

**Parameters:**
- `userid` (int): Target user ID

**Key return fields:**
- `id`: Course numeric identifier
- `shortname`: Course code (e.g., `CS301`)
- `fullname`: Course title
- `summary`: Syllabus summary HTML

---

### 3. `core_course_get_contents`

Fetches the complete course outline, including section headers, lecture modules, assignments, and files.

**Parameters:**
- `courseid` (int): Course numeric identifier

**Key return fields:**
- `id`: Section identifier
- `name`: Section header title
- `modules`: List of activities in the section
  - `name`: Module label
  - `modname`: Module type (`resource`, `assign`, `forum`, `quiz`)
  - `contents`: Attached files with `fileurl`, `filename`, `filesize`, `mimetype`

---

### 4. `core_calendar_get_action_events_by_timesort`

Fetches upcoming actionable events (such as pending assignment submissions and scheduled quizzes).

**Parameters:**
- `timesortfrom` (int): Unix timestamp for the start of the window
- `timesortto` (int): Unix timestamp for the end of the window
- `limitnum` (int): Maximum events to return

**Key return fields:**
- `events`: Array of event objects containing `name`, `formattedtime`, `course`, and `url`

---

### 5. `mod_assign_get_assignments`

Fetches assignment briefs, submission deadlines, and grading criteria.

**Parameters:**
- `courseids[0]` (int, optional): Filter by course ID

**Key return fields:**
- `courses`: Array of courses containing `assignments`
  - `name`: Assignment title
  - `intro`: Instructions or problem description
  - `duedate`: Submission deadline timestamp
  - `cutoffdate`: Hard cutoff timestamp

---

### 6. `message_popup_get_popup_notifications`

Pulls system bell notifications delivered to the user.

**Parameters:**
- `useridto` (int): Recipient user ID
- `limit` (int): Batch size

---

### 7. Attendance

`open-moodle` does not call `mod_attendance_get_sessions`. That function exists on the attendance plugin and requires a teacher capability (`mod/attendance:manageattendances`, `takeattendances`, or `changeattendances`). It does not return the current student's tally.

Student attendance is read from `gradereport_user_get_grade_items`. Items whose name contains "attendance" are shown as percentages. Point values are not treated as session counts, and safe-bunk math stays off unless a record actually includes `attended` and `total_sessions`.

---

### 8. `gradereport_user_get_grade_items`

Pulls student grade items, marks, percentages, and feedback comments.

**Parameters:**
- `userid` (int): Target user ID
- `courseid` (int, optional): Filter by course ID

---

### 9. `mod_forum_get_forums_by_courses` & `mod_forum_get_forum_discussions`

Pulls genuine instructor announcements and discussion threads from course news forums.

---

### 10. `mod_assign_get_submission_status`

Checks whether an assignment has been submitted, saved as draft, or untouched, along with grading states.

**Parameters:**
- `assignid` (int): Target assignment ID

---

## File Downloads via `pluginfile.php`

Files hosted on Moodle are delivered through `pluginfile.php`. Standard browsers authenticate using session cookies. When accessing these files via an automated client or AI tool, you must append the web service token to the download URL:

```
https://lms.university.edu/webservice/pluginfile.php/1234/mod_resource/content/1/notes.pdf?token=YOUR_TOKEN
```

`open-moodle` automatically handles this authentication parameter during file retrieval.
