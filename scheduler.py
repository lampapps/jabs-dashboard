"""Standalone entry point for the JABS dashboard's periodic background tasks.

Runs the digest email check, the offline-agent alert check, and the
retention purge in one process, so a single HOST cron entry (see
README.md) is enough to drive all three. All scheduling is config-driven
rather than an in-process background thread:

- Digest email: sent only when the cron-like `email.digest.schedule` in
  config/global.yaml is due (see app/services/emailer.py:maybe_send_digest).
- Offline agent alert: checked on every invocation; sends an immediate email
  the moment an enabled agent's grace period lapses without a heartbeat/event
  (see app/services/offline_alerts.py:check_offline_agents).
- Retention purge: runs unconditionally on every invocation, deleting
  completed backup_jobs (and cascaded events) older than
  `retention.max_days` (see app/services/retention.py).

This keeps scheduling independent of whether the web server process is
running, and mirrors how the backup agent's own scheduler is invoked
externally by cron.
"""

from app import create_app
from app.services.emailer import maybe_send_digest
from app.services.offline_alerts import check_offline_agents
from app.services.retention import purge_old_records


def main():
    """Check/send the digest email if due, check for newly offline agents,
    and purge old records."""
    app = create_app()
    with app.app_context():
        maybe_send_digest()
        check_offline_agents()
        purge_old_records()


if __name__ == "__main__":
    main()
