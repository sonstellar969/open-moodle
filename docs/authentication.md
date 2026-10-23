# Moodle Authentication and Token Guide

This guide explains how Moodle authentication works, why standard token generation pages often fail on university installations, and the methods available to acquire a valid web service token.

---

## Background

Moodle exposes its Web Services REST API through `/webservice/rest/server.php`. Every API call requires an authentication token passed via the `wstoken` parameter or an `Authorization: Bearer` header.

There are four primary ways to obtain a token, depending on how your university administrator configured access.

---

## Method 1: The Mobile Token Endpoint (Standard for Password Logins)

Many universities disable user-facing token management to prevent students from creating arbitrary API keys. However, if the university enables the official Moodle Mobile application, the mobile authentication endpoint remains active.

### How It Works

You can send your student username and password directly to the `/login/token.php` endpoint requesting the `moodle_mobile_app` service.

### CLI Method

You can use the built-in login command:

```bash
open-moodle login
```

The CLI prompts for your Moodle site URL, student username, and password, queries the mobile endpoint, and stores the token locally in `~/.config/open-moodle/config.json`.

### Manual Browser or cURL Method

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

## Method 2: Browser SSO Launch URL (For Microsoft / Google SSO)

When a university enforces Single Sign-On (SSO via Microsoft 365, Google Workspace, or SAML/Shibboleth), `/login/token.php` with direct username/password will reject requests with `invalidlogin`.

Moodle provides a browser-based authentication flow for mobile apps via the `tool_mobile` plugin:

1. Open your browser and navigate to:
   ```
   https://lms.university.edu/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=1&urlscheme=moodlemobile
   ```
2. Log in through your campus SSO provider (Microsoft/Google).
3. Upon successful login, the browser attempts to redirect to a custom protocol URL:
   ```
   moodlemobile://token=TOKEN_VALUE_HERE&privatetoken=...
   ```
4. If your browser asks to open an external application, inspect the prompt or copy the redirect URL from the address bar or developer console.
5. Extract the 32-character string following `token=`.
6. Save it to `open-moodle`:
   ```bash
   open-moodle login --url "https://lms.university.edu" --token "EXTRACTED_TOKEN"
   ```

---

## Method 3: User Account Token Management Page

On installations where administrators permit users to generate keys manually:

1. Log into your Moodle portal in a browser.
2. Click your profile avatar in the top-right corner.
3. Navigate to **Preferences** -> **Security Keys** (or open `/user/managetoken.php`).
4. Look for the row labeled **Moodle mobile web service** or create a new key.
5. Copy the 32-character hexadecimal string.

*Note: If visiting `/user/managetoken.php` results in a blank page or an "Access denied" error, the administrator has disabled this view. Use Method 1 or 2 instead.*

---

## Method 4: Official Mobile App Inspection

If your college blocks web redirects or enforces strict device binding:

1. Install the official Moodle app on your phone or desktop.
2. Log in successfully.
3. Open Developer Tools (in the desktop app) or route traffic through a local proxy (such as Charles, mitmproxy, or HTTP Toolkit).
4. Filter requests for `server.php`.
5. Locate the `wstoken=` parameter in the query string or request body.

---

## Verification

To verify that your token is valid and active, run:

```bash
open-moodle whoami --url "https://lms.university.edu" --token "YOUR_TOKEN"
```

A working token will return your student name, user ID, university site name, and the count of whitelisted API functions.
