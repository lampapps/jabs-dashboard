"""Standalone entry point for sending the JABS dashboard's digest email.

This is intended to be invoked by the HOST's cron at whatever time/frequency
the digest should go out (e.g. once daily). All scheduling is controlled by
the crontab entry itself -- this script simply sends the digest, covering
activity since the last successful send, every time it's run. See
README.md for the recommended crontab entry.
"""

from app import create_app
from app.services.emailer import send_digest_email


def main():
    """Send the digest email covering activity since the last send."""
    app = create_app()
    with app.app_context():
        send_digest_email()


if __name__ == "__main__":
    main()
