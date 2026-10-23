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

Pulls system notifications and announcements delivered to the user.

**Parameters:**
- `useridto` (int): Recipient user ID
- `limit` (int): Batch size

---

## File Downloads via `pluginfile.php`

Files hosted on Moodle are delivered through `pluginfile.php`. Standard browsers authenticate using session cookies. When accessing these files via an automated client or AI tool, you must append the web service token to the download URL:

```
https://lms.university.edu/webservice/pluginfile.php/1234/mod_resource/content/1/notes.pdf?token=YOUR_TOKEN
```

`open-moodle` automatically handles this authentication parameter during file retrieval.
