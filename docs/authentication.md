# Moodle Authentication and Token Guide

This guide explains how Moodle authentication works, why standard token generation pages often fail on university installations, and the methods available to acquire a valid web service token.

---

## Background

Moodle exposes its Web Services REST API through `/webservice/rest/server.php`. Every API call requires an authentication token passed via the `wstoken` parameter or an `Authorization: Bearer` header.

There are three primary ways users obtain a token, depending on how the Moodle administrator configured access permissions.

---

## Method 1: The Mobile Token Endpoint (Recommended for Students)

Many universities disable user-facing token management to prevent students from creating arbitrary API keys. However, if the university enables the official Moodle Mobile application, the mobile authentication endpoint remains active.

### How It Works

You can send your student username and password directly to the `/login/token.php` endpoint requesting the `moodle_mobile_app` service.

### CLI Method

You can use the built-in login command:

```bash
open-moodle login
```

The CLI will prompt for your Moodle site URL, student username, and password, then query the mobile endpoint and store the token locally.

### Manual Browser / cURL Method

You can test this in a browser or terminal:

```bash
curl -s "https://lms.university.edu/login/token.php" \
  -d "username=YOUR_STUDENT_ID" \
  -d "password=YOUR_PASSWORD" \
  -d "service=moodle_mobile_app"
```

A successful response returns a JSON payload:

```json
{
  "token": "e6bdc79cba06e4746aa10d0a5783f997",
  "privatetoken": "ARgzuizme97..."
}
```

The `token` value is your API key.

---

## Method 2: User Account Token Management Page

On installations where administrators permit users to generate keys manually:

1. Log into your Moodle portal in a browser.
2. Click your profile avatar in the top-right corner.
3. Navigate to **Preferences** -> **Security Keys** (or open `/user/managetoken.php`).
4. Look for the row labeled **Moodle mobile web service** or create a new key.
5. Copy the 32-character hexadecimal string.

*Note: If visiting `/user/managetoken.php` results in a blank page or an "Access denied" error, the administrator has disabled this view. Use Method 1 instead.*

---

## Method 3: Mobile App Token Extraction

If direct credentials fail because your campus uses Single Sign-On (SSO via Microsoft 365, Google Workspace, or Shibboleth/SAML):

1. Install the official Moodle app on iOS or Android.
2. Complete the login process through your campus SSO provider.
3. Inspect network traffic using a local debugging proxy (e.g., mitmproxy, Charles, or HTTP Toolkit) configured on the device.
4. Filter requests for `server.php`.
5. Locate the `wstoken=` parameter in the query string or form data.

---

## Verification

To verify that your token is valid and active, run:

```bash
open-moodle whoami --url "https://lms.university.edu" --token "YOUR_TOKEN"
```

A working token will return your student name, user ID, and university site name.
