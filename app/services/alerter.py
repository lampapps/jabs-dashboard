"""Alert and notification system for backup events.

Monitors backup events and triggers notifications (email, etc.) based on configured rules.
"""

import time
from typing import Dict, Any, Optional, List
from app.models.db_core import get_db_connection



class AlertRule:
    """Configuration for when to trigger an alert."""

    def __init__(
        self,
        name: str,
        event_type: str,
        condition: str = "any",
        notify_on: str = "failure",
        enabled: bool = True,
        cooldown_minutes: int = 60
    ):
        """Initialize alert rule.

        Args:
            name: Alert rule name
            event_type: Type of event ('backup_complete', 'error', etc.)
            condition: Trigger condition ('any', 'repeated', 'threshold')
            notify_on: What to notify about ('failure', 'success', 'always')
            enabled: Whether rule is active
            cooldown_minutes: Minimum minutes between alerts for same issue
        """
        self.name = name
        self.event_type = event_type
        self.condition = condition
        self.notify_on = notify_on
        self.enabled = enabled
        self.cooldown_minutes = cooldown_minutes
        self.last_triggered = {}  # Dict of (instance_id, job_name) -> timestamp


class AlertManager:
    """Manages alert rules and triggering."""

    def __init__(self):
        """Initialize alert manager with default rules."""
        self.rules: List[AlertRule] = []
        self._setup_default_rules()

    def _setup_default_rules(self):
        """Setup sensible default alert rules."""
        # Alert on any backup failure
        self.add_rule(AlertRule(
            name="backup_failed",
            event_type="error",
            condition="any",
            notify_on="failure",
            enabled=True,
            cooldown_minutes=60
        ))

        # Alert if backup takes too long (would need event data check)
        self.add_rule(AlertRule(
            name="backup_slow",
            event_type="backup_complete",
            condition="threshold",
            notify_on="failure",
            enabled=True,
            cooldown_minutes=120
        ))

        # Alert if agent goes offline
        self.add_rule(AlertRule(
            name="agent_offline",
            event_type="agent_heartbeat_missed",
            condition="repeated",
            notify_on="failure",
            enabled=True,
            cooldown_minutes=60
        ))

    def add_rule(self, rule: AlertRule):
        """Add an alert rule."""
        self.rules.append(rule)

    def check_and_trigger_alerts(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check if any alert rules match the event and trigger them.

        Args:
            event: Event dictionary with instance_id, event_type, message, etc.

        Returns:
            List of alerts that were triggered
        """
        alerts = []

        for rule in self.rules:
            if not rule.enabled:
                continue

            # Check if event type matches
            if rule.event_type != event.get('event_type'):
                continue

            # Check cooldown
            key = (event.get('agent_id'), event.get('job_name'))
            now = time.time()
            last_trigger = rule.last_triggered.get(key, 0)

            if now - last_trigger < (rule.cooldown_minutes * 60):
                continue

            # Check condition
            should_trigger = False

            if rule.condition == "any":
                should_trigger = True
            elif rule.condition == "threshold":
                # Check if it's a slow backup (> 1 hour)
                duration = event.get('data', {}).get('duration_seconds', 0)
                should_trigger = duration > 3600
            elif rule.condition == "repeated":
                # Check if there are repeated failures
                should_trigger = False  # TODO: Implement error metric checking

            if should_trigger:
                rule.last_triggered[key] = now

                alert = {
                    'rule_name': rule.name,
                    'event_type': event.get('event_type'),
                    'agent_id': event.get('agent_id'),
                    'message': event.get('message'),
                    'severity': self._get_severity(rule.event_type),
                    'timestamp': now
                }

                alerts.append(alert)

        return alerts

    def _get_severity(self, event_type: str) -> str:
        """Determine alert severity based on event type."""
        severity_map = {
            'error': 'critical',
            'backup_failed': 'critical',
            'agent_offline': 'warning',
            'backup_slow': 'warning',
            'warning': 'info',
        }
        return severity_map.get(event_type, 'info')


def store_alert(alert: Dict[str, Any]) -> int:
    """Store an alert in the database.

    Args:
        alert: Alert dictionary with rule_name, event_type, message, etc.

    Returns:
        Alert ID
    """
    with get_db_connection() as conn:
        c = conn.cursor()

        # Create alerts table if it doesn't exist
        c.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                agent_id INTEGER,
                message TEXT NOT NULL,
                severity TEXT NOT NULL,
                acknowledged BOOLEAN DEFAULT 0,
                acknowledged_at REAL,
                timestamp REAL NOT NULL,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
        """)

        c.execute("""
            INSERT INTO alerts (rule_name, event_type, agent_id, message, severity, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            alert.get('rule_name'),
            alert.get('event_type'),
            alert.get('agent_id'),
            alert.get('message'),
            alert.get('severity'),
            alert.get('timestamp', time.time())
        ))

        conn.commit()
        return c.lastrowid


def get_recent_alerts(hours: int = 24, severity: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get recent alerts.

    Args:
        hours: Look back this many hours
        severity: Filter by severity ('critical', 'warning', 'info')

    Returns:
        List of alert dictionaries
    """
    cutoff_time = time.time() - (hours * 3600)

    with get_db_connection() as conn:
        c = conn.cursor()

        if severity:
            c.execute("""
                SELECT * FROM alerts
                WHERE timestamp > ? AND severity = ?
                ORDER BY timestamp DESC
            """, (cutoff_time, severity))
        else:
            c.execute("""
                SELECT * FROM alerts
                WHERE timestamp > ?
                ORDER BY timestamp DESC
            """, (cutoff_time,))

        return [dict(row) for row in c.fetchall()]


def acknowledge_alert(alert_id: int) -> bool:
    """Mark an alert as acknowledged.

    Args:
        alert_id: ID of alert to acknowledge

    Returns:
        True if successful, False otherwise
    """
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE alerts
            SET acknowledged = 1, acknowledged_at = ?
            WHERE id = ?
        """, (time.time(), alert_id))
        conn.commit()
        return c.rowcount > 0


# Global alert manager instance
_alert_manager = None


def get_alert_manager() -> AlertManager:
    """Get or create global alert manager."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
