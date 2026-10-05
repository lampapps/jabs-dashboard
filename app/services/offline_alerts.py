"""Offline-agent alert email service for the JABS dashboard.

Unlike the digest email (a periodic summary sent on a cron schedule), this
is event-driven: every time scheduler.py runs, it checks every *enabled*
agent's computed status (see app/models/agents.py:compute_agent_status) and
sends an alert email once an agent is found to be 'offline' (i.e. no
heartbeat/event within its configured grace_period_minutes). Per
`email.offline_alert.max_alerts`/`repeat_interval_minutes` in
config/global.yaml, up to max_alerts emails (0 = unlimited) are sent per
offline streak, spaced at least repeat_interval_minutes apart; the streak's
offline_alert_count/last_offline_alert_at are cleared automatically the
next time the agent sends a heartbeat (see
app/models/agents.py:update_heartbeat), allowing a future offline streak to
alert again from the start.
"""

import time
from datetime import datetime

from flask import render_template

from app.settings import EMAIL_CONFIG
from app.utils.logger import setup_logger
from app.models.agents import list_agents, record_offline_alert_sent
from app.services.emailer import _send_email

email_logger = setup_logger("scheduler", log_file="scheduler.log")


def check_offline_agents():
    """Send an alert email for any enabled agent that is offline and due
    for an alert, per the configured max_alerts/repeat_interval_minutes.

    Returns the number of alert emails successfully sent.
    """
    alert_cfg = EMAIL_CONFIG.get("offline_alert", {}) or {}
    if not alert_cfg.get("enabled", False):
        email_logger.debug("Offline alert email disabled (email.offline_alert.enabled is false); skipping.")
        return 0

    max_alerts = alert_cfg.get("max_alerts", 1)
    repeat_interval_minutes = alert_cfg.get("repeat_interval_minutes", 60)

    agents = list_agents()
    email_logger.debug(f"Checking {len(agents)} agent(s) for offline status.")

    now = time.time()
    sent_count = 0
    for agent in agents:
        if agent.get("status") != "offline":
            email_logger.debug(f"Agent '{agent['hostname']}' (id={agent['id']}) status is '{agent.get('status')}'; skipping.")
            continue

        alert_count = agent.get("offline_alert_count") or 0
        if max_alerts and alert_count >= max_alerts:
            email_logger.debug(
                f"Agent '{agent['hostname']}' (id={agent['id']}) already alerted {alert_count}/{max_alerts} times; skipping."
            )
            continue

        last_alert_at = agent.get("last_offline_alert_at")
        if alert_count > 0 and last_alert_at and (now - last_alert_at) < repeat_interval_minutes * 60:
            email_logger.debug(
                f"Agent '{agent['hostname']}' (id={agent['id']}) alerted {repeat_interval_minutes} min ago; not due yet."
            )
            continue

        email_logger.debug(f"Agent '{agent['hostname']}' (id={agent['id']}) offline; sending alert email ({alert_count + 1}).")

        html_body = render_template(
            "email/agent_offline_email.html",
            agent=agent,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_heartbeat_fmt=(
                datetime.fromtimestamp(agent["last_heartbeat"]).strftime("%Y-%m-%d %H:%M:%S")
                if agent.get("last_heartbeat") else "never"
            ),
            alert_number=alert_count + 1,
            max_alerts=max_alerts,
        )
        subject = f"JABS Alert: Agent '{agent['hostname']}' is offline"

        if _send_email(subject, html_body, html=True):
            record_offline_alert_sent(agent["id"])
            sent_count += 1
            email_logger.debug(f"Sent offline alert for agent '{agent['hostname']}' (id={agent['id']})")
        else:
            email_logger.error(f"Failed to send offline alert for agent '{agent['hostname']}' (id={agent['id']})")


    email_logger.debug(f"Offline alert check complete: {sent_count} alert email(s) sent.")
    return sent_count
