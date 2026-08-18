"""Offline-agent alert email service for the JABS dashboard.

Unlike the digest email (a periodic summary sent on a cron schedule), this
is event-driven: every time scheduler.py runs, it checks every *enabled*
agent's computed status (see app/models/agents.py:compute_agent_status) and
sends an immediate alert email the moment an agent is first found to be
'offline' (i.e. no heartbeat/event within its configured
grace_period_minutes). Each agent is only alerted once per offline streak —
the agent's `offline_notified` flag suppresses repeat emails on subsequent
scheduler runs, and is cleared automatically the next time the agent sends
a heartbeat (see app/models/agents.py:update_heartbeat), allowing a future
offline streak to alert again.
"""

from datetime import datetime

from flask import render_template

from app.settings import EMAIL_CONFIG
from app.utils.logger import setup_logger
from app.models.agents import list_agents, set_offline_notified
from app.services.emailer import _send_email

email_logger = setup_logger("scheduler", log_file="scheduler.log")


def check_offline_agents():
    """Send an alert email for any enabled agent that just went offline.

    Returns the number of alert emails successfully sent.
    """
    alert_cfg = EMAIL_CONFIG.get("offline_alert", {}) or {}
    if not alert_cfg.get("enabled", False):
        email_logger.debug("Offline alert email disabled (email.offline_alert.enabled is false); skipping.")
        return 0

    agents = list_agents()
    email_logger.debug(f"Checking {len(agents)} agent(s) for offline status.")

    sent_count = 0
    for agent in agents:
        if agent.get("status") != "offline":
            email_logger.debug(f"Agent '{agent['hostname']}' (id={agent['id']}) status is '{agent.get('status')}'; skipping.")
            continue
        if agent.get("offline_notified"):
            email_logger.debug(
                f"Agent '{agent['hostname']}' (id={agent['id']}) is offline but already notified; skipping."
            )
            continue

        email_logger.info(f"Agent '{agent['hostname']}' (id={agent['id']}) newly offline; sending alert email.")

        html_body = render_template(
            "email/agent_offline_email.html",
            agent=agent,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_heartbeat_fmt=(
                datetime.fromtimestamp(agent["last_heartbeat"]).strftime("%Y-%m-%d %H:%M:%S")
                if agent.get("last_heartbeat") else "never"
            ),
        )
        subject = f"JABS Alert: Agent '{agent['hostname']}' is offline"

        if _send_email(subject, html_body, html=True):
            set_offline_notified(agent["id"], True)
            sent_count += 1
            email_logger.info(f"Sent offline alert for agent '{agent['hostname']}' (id={agent['id']})")
        else:
            email_logger.error(f"Failed to send offline alert for agent '{agent['hostname']}' (id={agent['id']})")

    email_logger.debug(f"Offline alert check complete: {sent_count} alert email(s) sent.")
    return sent_count
