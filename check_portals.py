#!/usr/bin/env python3
"""
Portal availability checker.

- Checks if the Staging and Dev portals are reachable via HTTP GET.
- Sends an alert email when a portal goes DOWN.
- Sends a recovery email when a previously-down portal comes back UP.
- Persists state between runs in a private GitHub Gist so no duplicate
  emails are ever sent for the same outage, even across fresh CI runners.
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Email config ───────────────────────────────────────────────────────────────
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
EMAIL_SENDER   = os.getenv("EMAIL_SENDER")    # e.g. hellolucifer007@gmail.com
EMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_TO       = os.getenv("EMAIL_TO")        # e.g. rishabh.gupta@vetty.co

# ── Gist config ────────────────────────────────────────────────────────────────
# GIST_TOKEN : fine-grained PAT with "Gists" read+write scope
# GIST_ID    : the ID from your Gist URL → github.com/gist/<username>/<GIST_ID>
GIST_TOKEN     = os.getenv("GIST_TOKEN")
GIST_ID        = os.getenv("GIST_ID")
GIST_FILENAME  = "portal_state.json"   # the file inside the Gist

GIST_API_BASE  = "https://api.github.com"

# ── Portals to check ───────────────────────────────────────────────────────────
# URLs are read from env vars so they never need to be hardcoded.
# STAGING_URL and DEV_URL must be set in .env or GitHub Secrets.
PORTALS = [
    {
        "name": "Staging Portal",
        "url":  os.getenv("STAGING_URL", "").strip(),
    },
    {
        "name": "Dev Portal",
        "url":  os.getenv("DEV_URL", "").strip(),
    },
]

# Request timeout in seconds
TIMEOUT = 10


# ── Gist state helpers ─────────────────────────────────────────────────────────

def _gist_headers() -> dict:
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load_state() -> dict:
    """
    Fetch portal_state.json from the Gist.
    Falls back to an empty dict if the Gist is unreachable or the file
    doesn't exist yet (first run).
    """
    if not GIST_TOKEN or not GIST_ID:
        print("  [WARN] GIST_TOKEN or GIST_ID not set — starting with empty state.")
        return {}

    try:
        resp = requests.get(
            f"{GIST_API_BASE}/gists/{GIST_ID}",
            headers=_gist_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        if GIST_FILENAME not in files:
            # First run — file doesn't exist in the Gist yet
            return {}
        raw_url = files[GIST_FILENAME]["raw_url"]
        raw     = requests.get(raw_url, timeout=TIMEOUT)
        raw.raise_for_status()
        return json.loads(raw.text)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as exc:
        print(f"  [WARN] Could not load state from Gist: {exc} — starting fresh.")
        return {}


def save_state(state: dict) -> None:
    """
    Write portal_state.json back to the Gist via PATCH.
    Creates the file inside the Gist automatically if it doesn't exist.
    """
    if not GIST_TOKEN or not GIST_ID:
        print("  [WARN] GIST_TOKEN or GIST_ID not set — state not saved.")
        return

    payload = {
        "files": {
            GIST_FILENAME: {
                "content": json.dumps(state, indent=2)
            }
        }
    }
    try:
        resp = requests.patch(
            f"{GIST_API_BASE}/gists/{GIST_ID}",
            headers=_gist_headers(),
            json=payload,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        print("  [OK]   State saved to Gist.")
    except requests.RequestException as exc:
        print(f"  [ERR]  Failed to save state to Gist: {exc}")


# ── Email ──────────────────────────────────────────────────────────────────────

def _build_html(heading: str, color: str, body_lines: list[str]) -> str:
    rows = "".join(f"<p style='margin:4px 0'>{line}</p>" for line in body_lines)
    return f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;padding:20px">
      <div style="max-width:600px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden">
        <div style="background:{color};padding:20px">
          <h2 style="color:#fff;margin:0">{heading}</h2>
        </div>
        <div style="padding:24px">
          {rows}
        </div>
        <div style="background:#f5f5f5;padding:12px 24px;font-size:12px;color:#888">
          Automated alert · Portal Health Check · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
        </div>
      </div>
    </body></html>
    """


def send_email(subject: str, html_body: str) -> None:
    """Send an HTML email via Gmail SMTP."""
    if not EMAIL_PASSWORD:
        print("  [WARN] GMAIL_APP_PASSWORD not set — skipping email.")
        return
    if not EMAIL_SENDER or not EMAIL_TO:
        print("  [WARN] EMAIL_SENDER or EMAIL_TO not set — skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Portal Monitor <{EMAIL_SENDER}>"
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_TO, msg.as_string())
        print(f"  [OK]   Email sent to {EMAIL_TO}")
    except smtplib.SMTPException as exc:
        print(f"  [ERR]  Failed to send email: {exc}")


def send_down_alert(portal: dict, reason: str) -> None:
    name    = portal["name"]
    url     = portal["url"]
    subject = f"🚨 ALERT: {name} is DOWN"
    html    = _build_html(
        heading=f"🚨 {name} is DOWN",
        color="#d32f2f",
        body_lines=[
            f"<strong>Portal:</strong> {name}",
            f"<strong>URL:</strong> <a href='{url}'>{url}</a>",
            f"<strong>Reason:</strong> {reason}",
            "<br>",
            "The portal is <strong>unreachable</strong>. Please investigate immediately.",
        ],
    )
    send_email(subject, html)


def send_recovery_alert(portal: dict, downtime_since: str) -> None:
    name    = portal["name"]
    url     = portal["url"]
    subject = f"✅ RECOVERY: {name} is back UP"
    html    = _build_html(
        heading=f"✅ {name} is back UP",
        color="#2e7d32",
        body_lines=[
            f"<strong>Portal:</strong> {name}",
            f"<strong>URL:</strong> <a href='{url}'>{url}</a>",
            f"<strong>Was down since:</strong> {downtime_since}",
            "<br>",
            "The portal is <strong>reachable again</strong>. No further action needed.",
        ],
    )
    send_email(subject, html)


# ── Portal check ───────────────────────────────────────────────────────────────

def check_portal(portal: dict) -> tuple[bool, str]:
    """
    Perform an HTTP GET to the portal URL.
    Returns (is_up: bool, reason: str).
    """
    url = portal["url"]
    try:
        resp = requests.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
            headers={"User-Agent": "PortalHealthCheck/1.0"},
        )
        if resp.status_code < 500:
            return True, f"HTTP {resp.status_code}"
        else:
            return False, f"HTTP {resp.status_code} (server error)"

    except requests.ConnectionError:
        return False, "Connection error (DNS / network failure)"
    except requests.Timeout:
        return False, f"Request timed out after {TIMEOUT}s"
    except requests.RequestException as exc:
        return False, f"Unexpected error: {exc}"


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    # Validate required env vars up front
    missing = [p["name"] for p in PORTALS if not p["url"]]
    if missing:
        print(f"[ERROR] Missing URL env vars for: {', '.join(missing)}")
        print("        Set STAGING_URL and DEV_URL in .env or GitHub Secrets.")
        sys.exit(2)

    print("=== Portal Health Check ===")
    print(f"    {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    print("Loading state from Gist …")
    state    = load_state()   # { portal_name: {"down": bool, "since": "ISO timestamp"} }
    any_down = False
    print()

    for portal in PORTALS:
        name = portal["name"]
        prev = state.get(name, {"down": False, "since": None})

        print(f"Checking {name} ({portal['url']}) …")
        is_up, reason = check_portal(portal)

        if is_up:
            print(f"  [UP]   {name} — {reason}")
            if prev["down"]:
                print(f"  [INFO] Previously down since {prev['since']} — sending recovery alert.")
                send_recovery_alert(portal, prev["since"])
            state[name] = {"down": False, "since": None}

        else:
            any_down = True
            print(f"  [DOWN] {name} — {reason}")
            if not prev["down"]:
                down_since = datetime.now(timezone.utc).isoformat()
                print("  [INFO] New outage detected — sending alert.")
                send_down_alert(portal, reason)
                state[name] = {"down": True, "since": down_since}
            else:
                print(f"  [INFO] Still down since {prev['since']} — alert already sent, skipping.")

        print()

    print("Saving state to Gist …")
    save_state(state)
    print()

    if not any_down:
        print("✅ All portals are up and reachable.")
    else:
        print("❌ One or more portals are DOWN.")
        sys.exit(1)


if __name__ == "__main__":
    main()
