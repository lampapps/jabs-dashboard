"""Blueprint registration for app.routes."""

from .dashboard import dashboard_bp
from .api import api_bp
from .logs import logs_bp
from .security import security_bp
from .agent_monitoring import agent_monitoring_bp
from .configuration import configuration_bp
from .agents import agents_bp

def register_blueprints(app):
    """Register all blueprints with the Flask app."""
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(logs_bp)
    app.register_blueprint(security_bp)
    app.register_blueprint(agent_monitoring_bp)
    app.register_blueprint(configuration_bp)
    app.register_blueprint(agents_bp)
