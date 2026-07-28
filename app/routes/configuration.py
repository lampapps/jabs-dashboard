"""Flask routes for system configuration: hosts management and dashboard settings."""

import yaml
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from app.models import hosts
from app.settings import GLOBAL_CONFIG_PATH

configuration_bp = Blueprint('configuration', __name__, url_prefix='/configuration')


@configuration_bp.route('/hosts')
def manage_hosts():
    """Render hosts management page."""
    try:
        hosts_list = hosts.get_hosts_with_job_counts()
        return render_template('hosts.html', hosts=hosts_list)
    except Exception as e:
        current_app.logger.error(f"Error loading hosts: {e}")
        return render_template('hosts.html', hosts=[], error=str(e))


@configuration_bp.route('/hosts/add', methods=['POST'])
def add_host():
    """Register a new agent. Multiple agents may share the same hostname/IP
    (e.g. several agents on one machine) since each gets its own unique API key.
    """
    try:
        data = request.get_json()
        hostname = data.get('hostname', '').strip()
        ip_address = data.get('ip_address', '').strip()
        notes = data.get('notes', '').strip()

        if not hostname or not ip_address:
            return jsonify({'success': False, 'error': 'Hostname and IP address required'}), 400

        host_id, agent_key = hosts.create_host(hostname, ip_address, notes)
        return jsonify({
            'success': True,
            'host_id': host_id,
            'agent_key': agent_key,
            'message': f'Host "{hostname}" registered'
        }), 201

    except Exception as e:
        current_app.logger.error(f"Error adding host: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@configuration_bp.route('/hosts/<int:host_id>/edit', methods=['POST'])
def edit_host(host_id):
    """Update host details."""
    try:
        host = hosts.get_host(host_id)
        if not host:
            return jsonify({'success': False, 'error': 'Host not found'}), 404

        data = request.get_json()
        hostname = data.get('hostname')
        ip_address = data.get('ip_address')
        notes = data.get('notes')
        enabled = data.get('enabled')

        success = hosts.update_host(host_id, hostname=hostname, ip_address=ip_address, notes=notes, enabled=enabled)
        if success:
            return jsonify({'success': True, 'message': 'Host updated'}), 200
        else:
            return jsonify({'success': False, 'error': 'Host not found'}), 404

    except Exception as e:
        current_app.logger.error(f"Error editing host: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@configuration_bp.route('/hosts/<int:host_id>/regenerate-key', methods=['POST'])
def regenerate_host_key(host_id):
    """Generate a new API key for a host, invalidating the old one."""
    try:
        host = hosts.get_host(host_id)
        if not host:
            return jsonify({'success': False, 'error': 'Host not found'}), 404

        new_key = hosts.regenerate_agent_key(host_id)
        return jsonify({'success': True, 'agent_key': new_key, 'message': 'API key regenerated'}), 200

    except Exception as e:
        current_app.logger.error(f"Error regenerating agent key: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@configuration_bp.route('/hosts/<int:host_id>/delete', methods=['POST'])
def delete_host(host_id):
    """Delete a host (cascades to jobs and events)."""
    try:
        host = hosts.get_host(host_id)
        if not host:
            return jsonify({'success': False, 'error': 'Host not found'}), 404

        hostname = host['hostname']
        success = hosts.delete_host(host_id)
        if success:
            return jsonify({'success': True, 'message': f'Host "{hostname}" deleted'}), 200
        else:
            return jsonify({'success': False, 'error': 'Failed to delete host'}), 500

    except Exception as e:
        current_app.logger.error(f"Error deleting host: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
