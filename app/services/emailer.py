"""Email digest service for the JABS dashboard.

Unlike the backup agent (which sends immediate error/backup_complete emails),
the dashboard only sends a periodic digest email summarizing backup activity
across all registered agents. The digest is rendered from an HTML template
and sent whenever the HOST's cron invokes send_digest.py (see README.md).
"""

import json
import os
import smtplib
import socket
import time
from datetime import datetime
from email.mime.text import MIMEText

from dotenv import load_dotenv
from flask import render_template

from app.settings import EMAIL_CONFIG, ENV_PATH, ENV_MODE, DATA_DIR
from app.utils.logger import setup_logger, sizeof_fmt
from app.models.backup_jobs import list_completed_jobs_since

email_logger = setup_logger("email", log_file="email.log")

load_dotenv(ENV_PATH)

DIGEST_STATE_PATH = os.path.join(DATA_DIR, "digest_state.json")


def _get_smtp_credentials():
    """Fetch SMTP username and password from environment variables."""
    username = os.environ.get("JABS_SMTP_USERNAME")
    password = os.environ.get("JABS_SMTP_PASSWORD")
    return username, password


def _send_email(subject, body, html=False):
    """Send an email with the given subject and body."""
    if not EMAIL_CONFIG:
        email_logger.debug("No email config found; skipping send.")
        return False

    username, password = _get_smtp_credentials()
    if ENV_MODE == "development":
        subject = f"[DEV] {subject}"
    if not username:
        email_logger.error("No SMTP username found in environment variable JABS_SMTP_USERNAME.")
        return False
    if not password:
        email_logger.error("No SMTP password found in environment variable JABS_SMTP_PASSWORD.")
        return False

    to_addrs = EMAIL_CONFIG.get("to_addrs") or []
    if not to_addrs:
        email_logger.error("No recipient addresses configured (email.to_addrs).")
        return False

    msg_type = "html" if html else "plain"
    msg = MIMEText(body, msg_type)
    msg["Subject"] = subject
    msg["From"] = username
    msg["To"] = ", ".join(to_addrs)

    try:
        server = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"], timeout=10)
        try:
            if EMAIL_CONFIG.get("use_tls"):
                server.starttls()
            server.login(username, password)
            server.sendmail(username, to_addrs, msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:  # pylint: disable=broad-except
                pass
        email_logger.info(f"Digest email sent: '{subject}' to {to_addrs}")
        return True
    except (smtplib.SMTPException, OSError, socket.timeout) as e:
        email_logger.error(f"Failed to send digest email '{subject}': {e}")
        return False


def _load_last_sent():
    """Return the unix timestamp the digest was last sent, or None."""
    try:
        with open(DIGEST_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("last_sent")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _save_last_sent(ts):
    """Persist the unix timestamp the digest was last sent."""
    os.makedirs(os.path.dirname(DIGEST_STATE_PATH), exist_ok=True)
    with open(DIGEST_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_sent": ts}, f)


def _group_by_host(jobs):
    """Group jobs by hostname, sorted alphabetically by host and
    chronologically (oldest first) within each host group.

    Returns a list of {"hostname": ..., "jobs": [...]} dicts.
    """
    by_host = {}
    for job in jobs:
        by_host.setdefault(job.get("hostname") or "Unknown", []).append(job)

    grouped = []
    for hostname in sorted(by_host.keys()):
        host_jobs = sorted(by_host[hostname], key=lambda j: j.get("completed_at") or 0)
        grouped.append({"hostname": hostname, "jobs": host_jobs})
    return grouped


def send_digest_email():
    """Build and send the daily digest email covering activity since the last send.

    Returns True if an email was sent, False otherwise (nothing to report, or
    the send failed).
    """
    now = time.time()
    last_sent = _load_last_sent()
    # Default lookback window if we've never sent a digest: 24 hours.
    since_ts = last_sent if last_sent else (now - 86400)

    jobs = list_completed_jobs_since(since_ts)
    if not jobs:
        email_logger.info("No completed backup jobs since last digest; skipping send.")
        _save_last_sent(now)
        return False

    succeeded = [j for j in jobs if j.get("status") in ("completed", "success", "skipped")]
    failed = [j for j in jobs if j.get("status") in ("error", "failed")]

    for job in jobs:
        job["bytes_processed_fmt"] = sizeof_fmt(job.get("bytes_processed") or 0)
        job["completed_at_fmt"] = (
            datetime.fromtimestamp(job["completed_at"]).strftime("%Y-%m-%d %H:%M:%S")
            if job.get("completed_at") else "-"
        )

    html_body = render_template(
        "email/digest_email.html",
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        period_start=datetime.fromtimestamp(since_ts).strftime("%Y-%m-%d %H:%M:%S"),
        period_end=datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        jobs=jobs,
        succeeded=succeeded,
        failed=failed,
        succeeded_by_host=_group_by_host(succeeded),
        failed_by_host=_group_by_host(failed),
    )

    subject = f"JABS Daily Digest ({datetime.now().strftime('%Y-%m-%d')}) — {len(succeeded)} OK, {len(failed)} failed"
    sent = _send_email(subject, html_body, html=True)
    if sent:
        _save_last_sent(now)
    return sent

