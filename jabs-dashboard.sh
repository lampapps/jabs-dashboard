#!/bin/bash

#################################################
# JABS Dashboard Standalone Launcher
#
# This script handles setup, validation, and running
# of the JABS Dashboard (monitoring hub) with proper
# environment management.
#
# Usage:
#   jabs-dashboard.sh {setup|start|stop|restart|status|logs}
#   jabs-dashboard.sh help
#################################################

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Server configuration
VENV_PATH="$SCRIPT_DIR/venv"
PYTHON_VENV="$VENV_PATH/bin/python"
RUN_SCRIPT="$SCRIPT_DIR/run.py"
SCHEDULER_SCRIPT="$SCRIPT_DIR/scheduler.py"
PID_FILE="$SCRIPT_DIR/jabs_server.pid"
LOG_FILE="$SCRIPT_DIR/logs/server.log"

# Determine server port based on ENV_MODE
get_server_port() {
    local env_mode="${ENV_MODE:-production}"
    if [ "$env_mode" = "development" ]; then
        echo 5001
    else
        echo 5000
    fi
}

# Color output (ANSI-C quoting so these are raw escape bytes, not literal
# backslash text — needed since show_help's heredoc uses `cat`, not `echo -e`)
GREEN=$'\033[0;32m'
RED=$'\033[0;31m'
YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m' # No Color

# Helper functions
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[JABS Dashboard]${NC} $1"
}

print_section() {
    echo -e "${CYAN}[SECTION]${NC} $1"
}

print_success() {
    echo -e " ${GREEN}✓${NC} $1"
}

# Check Python version
check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
        PYTHON_OK=$(python3 -c 'import sys; print(sys.version_info >= (3,8))')
        if [ "$PYTHON_OK" = "True" ]; then
            print_success "Python 3.8+ found: $PYTHON_VERSION"
            return 0
        else
            print_error "Python version $PYTHON_VERSION found, but 3.8+ is required."
            return 1
        fi
    else
        print_error "Python3 not found."
        return 1
    fi
}

# Check venv module
check_venv_module() {
    if python3 -c "import venv" &>/dev/null; then
        print_success "python3 venv module is available."
        return 0
    else
        print_error "python3 venv module is missing."
        return 1
    fi
}

# Check pip
check_pip() {
    if python3 -m pip --version &>/dev/null; then
        print_success "pip found."
        return 0
    else
        print_error "pip not found."
        return 1
    fi
}

# Setup virtual environment
setup_virtual_env() {
    if [ -d "$VENV_PATH" ] && [ -f "$VENV_PATH/bin/python" ]; then
        print_success "Virtual environment already exists."
        return 0
    fi

    print_header "Setting up virtual environment..."
    if python3 -m venv "$VENV_PATH"; then
        print_success "Virtual environment created."
        return 0
    else
        print_error "Failed to create virtual environment."
        return 1
    fi
}

# Install requirements
install_requirements() {
    local req_file="$SCRIPT_DIR/requirements.txt"
    if [ ! -f "$req_file" ]; then
        print_error "requirements.txt not found at $req_file"
        return 1
    fi

    if "$PYTHON_VENV" -c "import flask" &>/dev/null; then
        print_success "Requirements already installed."
        return 0
    fi

    print_header "Installing requirements..."
    if "$PYTHON_VENV" -m pip install --upgrade pip && "$PYTHON_VENV" -m pip install -r "$req_file"; then
        print_success "Requirements installed."
        return 0
    else
        print_error "Failed to install requirements."
        return 1
    fi
}

# Validate setup
validate_setup() {
    if [[ ! -f "$PYTHON_VENV" ]]; then
        print_error "Virtual environment not found at: $PYTHON_VENV"
        return 1
    fi
    if [[ ! -f "$RUN_SCRIPT" ]]; then
        print_error "Run script not found at: $RUN_SCRIPT"
        return 1
    fi
    if ! "$PYTHON_VENV" -c "import flask" &>/dev/null; then
        print_error "Flask not properly installed."
        return 1
    fi
    print_success "Setup validation complete."
    return 0
}

# Ensure log directory
ensure_log_dir() {
    if [[ ! -d "$(dirname "$LOG_FILE")" ]]; then
        mkdir -p "$(dirname "$LOG_FILE")"
    fi
}

# Ensure monitor badges partial exists
ensure_monitor_badges_partial() {
    local partial_file="$TEMPLATE_DIR/partials/monitor_badges.html"
    if [[ ! -d "$(dirname "$partial_file")" ]]; then
        mkdir -p "$(dirname "$partial_file")"
    fi
    if [[ ! -f "$partial_file" ]]; then
        touch "$partial_file"
    fi
}

# Check if running
is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "$pid"
            return 0
        else
            rm -f "$PID_FILE"
            return 1
        fi
    fi
    return 1
}

# Start server
start_server() {
    if ! validate_setup; then
        print_error "Setup validation failed. Run '$0 setup' first."
        return 1
    fi

    if running_pid=$(is_running); then
        local port=$(get_server_port)
        print_warning "Server is already running (PID: $running_pid)"
        print_status "Access at: http://localhost:$port"
        return 0
    fi

    print_status "Starting JABS Server..."
    ensure_log_dir

    cd "$SCRIPT_DIR"
    nohup "$PYTHON_VENV" "$RUN_SCRIPT" > "$LOG_FILE" 2>&1 &
    local pid=$!
    echo "$pid" > "$PID_FILE"

    sleep 2
    if ps -p "$pid" > /dev/null 2>&1; then
        local port=$(get_server_port)
        print_success "Server started (PID: $pid)"
        print_status "Log file: $LOG_FILE"
        print_status "Access at: http://localhost:$port"
        return 0
    else
        print_error "Failed to start server"
        rm -f "$PID_FILE"
        return 1
    fi
}

# Stop server
stop_server() {
    if ! running_pid=$(is_running); then
        print_warning "Server is not running"
        return 0
    fi

    print_status "Stopping Server (PID: $running_pid)..."
    kill "$running_pid" 2>/dev/null

    local count=0
    while ps -p "$running_pid" > /dev/null 2>&1 && [[ $count -lt 10 ]]; do
        sleep 1
        ((count++))
    done

    if ps -p "$running_pid" > /dev/null 2>&1; then
        print_warning "Forcing termination..."
        kill -9 "$running_pid" 2>/dev/null
    fi

    rm -f "$PID_FILE"
    print_success "Server stopped"
    return 0
}

# Status server
status_server() {
    if running_pid=$(is_running); then
        local port=$(get_server_port)
        print_success "Server is running (PID: $running_pid)"
        print_status "Access at: http://localhost:$port"
        if [[ -f "$LOG_FILE" ]]; then
            echo ""
            echo "Recent logs:"
            tail -5 "$LOG_FILE"
        fi
    else
        print_warning "Server is not running"
    fi
}

# Show logs
show_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        print_status "Showing server logs (Press Ctrl+C to exit):"
        tail -f "$LOG_FILE"
    else
        print_error "Log file not found: $LOG_FILE"
        return 1
    fi
}

# Setup server
setup_server() {
    print_section "JABS Dashboard Setup"

    check_python || return 1
    check_venv_module || return 1
    check_pip || return 1
    setup_virtual_env || return 1
    install_requirements || return 1

    ensure_log_dir
    ensure_monitor_badges_partial

    if validate_setup; then
        print_success "Server setup complete!"
        echo ""
        echo -e "${BOLD}Next steps:${NC}"
        echo -e "  ${CYAN}$0 start${NC}   - Start the server"
        echo -e "  ${CYAN}$0 status${NC}  - Check status"
        echo -e "  ${CYAN}$0 logs${NC}    - View logs"
        echo ""
        echo "To enable the digest email and retention purge, add a single CRON job: crontab -e"
        echo -e "  ${DIM}*/15 * * * * cd $SCRIPT_DIR && venv/bin/python scheduler.py >> logs/scheduler_cron.log > /dev/null 2>&1${NC}"
        return 0
    else
        print_error "Server setup validation failed."
        return 1
    fi
}

# Print ready-to-copy commands for running the server and digest email on
# this host, using this machine's actual paths (including the venv
# interpreter) so they can be pasted directly into a terminal.
print_copy_paste_commands() {
    echo -e "${BOLD}COPY/PASTE COMMANDS${NC} ${DIM}(this host)${NC}:"
    echo ""
    echo -e "  ${DIM}Run server in foreground (not via $0 start):${NC}"
    echo -e "    ${CYAN}$PYTHON_VENV $RUN_SCRIPT${NC}"
    echo ""
    echo -e "  ${DIM}Run the digest-email/retention-purge scheduler manually:${NC}"
    echo -e "    ${CYAN}$PYTHON_VENV $SCHEDULER_SCRIPT${NC}"
    echo ""
}

# Show help
show_help() {
    cat << EOF
${BOLD}JABS Dashboard Launcher${NC}

${BOLD}USAGE:${NC}
  $0 {setup|start|stop|restart|status|logs|reset}
  $0 help

${BOLD}COMMANDS:${NC}
  ${CYAN}setup${NC}    Setup server environment
  ${CYAN}start${NC}    Start server in background
  ${CYAN}stop${NC}     Stop server
  ${CYAN}restart${NC}  Restart server
  ${CYAN}status${NC}   Show server status
  ${CYAN}logs${NC}     Follow server logs
  ${CYAN}reset${NC}    Reset app (clear database, logs, locks)
  ${CYAN}help${NC}     Show this help message

${BOLD}DIRECTORIES:${NC}
  Server:      $SCRIPT_DIR
  Venv:        $VENV_PATH
  Log file:    $LOG_FILE

${BOLD}WEB INTERFACE:${NC}
  After starting server, access at: ${CYAN}http://localhost:5000${NC} (production)
                              or: ${CYAN}http://localhost:5001${NC} (development)
  Port depends on ENV_MODE environment variable (default: production)

${BOLD}EXAMPLES:${NC}
  ${DIM}# Initial setup${NC}
  $0 setup

  ${DIM}# Start server${NC}
  $0 start

  ${DIM}# Start and monitor logs${NC}
  $0 start
  $0 logs

  ${DIM}# Check status${NC}
  $0 status

  ${DIM}# Stop server${NC}
  $0 stop

  ${DIM}# Reset everything (clear DB, logs, locks)${NC}
  $0 reset

EOF
    print_copy_paste_commands
}

# Reset app (clear database, logs, locks)
reset_app() {
    print_section "JABS Dashboard Reset"

    print_warning "This will permanently delete the database, logs, and lock file."
    read -r -p "Are you sure you want to reset the JABS Dashboard? [y/N] " confirm
    case "$confirm" in
        [yY]|[yY][eE][sS]) ;;
        *)
            print_status "Reset cancelled."
            return 1
            ;;
    esac

    # Stop server if running
    if running_pid=$(is_running); then
        print_status "Stopping server before reset..."
        stop_server
        sleep 1
    fi

    # Clear database
    print_status "Clearing database..."
    if [ -f "$SCRIPT_DIR/data/jabs.sqlite" ]; then
        rm -f "$SCRIPT_DIR/data/jabs.sqlite"
        print_success "Database cleared"
    else
        print_status "No database found (skipped)"
    fi

    # Clear logs
    print_status "Clearing logs..."
    if [ -d "$SCRIPT_DIR/logs" ]; then
        rm -f "$SCRIPT_DIR/logs"/*.log
        print_success "Logs cleared"
    else
        print_status "No logs directory found (skipped)"
    fi

    # Clear PID file
    print_status "Clearing lock files..."
    if [ -f "$PID_FILE" ]; then
        rm -f "$PID_FILE"
        print_success "Lock file cleared"
    else
        print_status "No lock file found (skipped)"
    fi

    # Summary
    echo ""
    print_success "Server reset complete!"
    echo ""
    echo -e "${BOLD}Reset items:${NC}"
    echo -e "  ${GREEN}✓${NC} Database cleared"
    echo -e "  ${GREEN}✓${NC} Logs cleared"
    echo -e "  ${GREEN}✓${NC} Lock files cleared"
    echo ""
    echo -e "${BOLD}Preserved items:${NC}"
    echo -e "  ${GREEN}✓${NC} Configuration files"
    echo -e "  ${GREEN}✓${NC} Application code"
    echo -e "  ${GREEN}✓${NC} Virtual environment"
    echo ""
    echo -e "${BOLD}Next steps:${NC}"
    echo -e "  ${CYAN}$0 setup${NC}   - Re-initialize if needed"
    echo -e "  ${CYAN}$0 start${NC}   - Start fresh server"
    return 0
}

# Main function
main() {
    local command="${1:-help}"

    case "$command" in
        setup)
            setup_server
            ;;
        start)
            start_server
            ;;
        stop)
            stop_server
            ;;
        restart)
            stop_server && sleep 1 && start_server
            ;;
        status)
            status_server
            ;;
        logs)
            show_logs
            ;;
        reset)
            reset_app
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# Run main with all arguments
main "$@"
