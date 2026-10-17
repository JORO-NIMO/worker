#!/bin/bash
set -e

echo "[WORKER-DOCKER] Initializing Autonomous Agent Worker Container..."

# Ensure config exists
if [ ! -f "$WORKER_CONFIG_PATH" ]; then
    if [ -f "/var/www/worker/config.example.json" ]; then
        echo "[WORKER-DOCKER] Creating config.json from template..."
        cp /var/www/worker/config.example.json "$WORKER_CONFIG_PATH"
    fi
fi

# Ensure data directory and DB setup
mkdir -p /var/www/worker/data /var/www/worker/logs

if [ "$1" = "run-all" ]; then
    echo "[WORKER-DOCKER] Starting Background Daemon and Web Dashboard (:8888)..."
    python3 /var/www/worker/core/worker_daemon.py &
    DAEMON_PID=$!
    
    python3 /var/www/worker/web/dashboard_server.py &
    SERVER_PID=$!
    
    trap "kill -TERM $DAEMON_PID $SERVER_PID" SIGTERM SIGINT
    wait -n
    exit $?
fi

exec "$@"
