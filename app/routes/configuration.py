"""Flask routes for system configuration: dashboard settings."""

import yaml
from flask import Blueprint, render_template, request, jsonify, current_app
from app.settings import GLOBAL_CONFIG_PATH

configuration_bp = Blueprint('configuration', __name__, url_prefix='/configuration')


@configuration_bp.route('/dashboard')
def edit_dashboard_config():
    """Render dashboard configuration editor."""
    try:
        with open(GLOBAL_CONFIG_PATH, 'r') as f:
            config_content = f.read()
        return render_template('dashboard_config.html', config_content=config_content)
    except Exception as e:
        current_app.logger.error(f"Error loading dashboard config: {e}")
        return render_template('dashboard_config.html', config_content='', error=str(e))


@configuration_bp.route('/dashboard/save', methods=['POST'])
def save_dashboard_config():
    """Save dashboard configuration."""
    try:
        data = request.get_json()
        config_content = data.get('config', '').strip()

        if not config_content:
            return jsonify({'success': False, 'error': 'Configuration cannot be empty'}), 400

        # Validate YAML syntax
        try:
            yaml.safe_load(config_content)
        except yaml.YAMLError as e:
            return jsonify({'success': False, 'error': f'Invalid YAML syntax: {str(e)}'}), 400

        # Write to file
        with open(GLOBAL_CONFIG_PATH, 'w') as f:
            f.write(config_content)

        return jsonify({'success': True, 'message': 'Configuration saved'}), 200

    except Exception as e:
        current_app.logger.error(f"Error saving dashboard config: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
