#!/bin/bash

# Print commands and their arguments as they are executed (debugging)
set -x

# Print in console debug messages
echo "Starting services..."

# Start Nginx in the foreground in a subshell for the script to proceed
nginx &

# Change directory to where app.py is located
NEBULA_FRONTEND_DIR=/nebula/nebula/frontend
#NEBULA_DATABASES_DIR=/nebula/nebula/frontend/databases
cd $NEBULA_FRONTEND_DIR

# Start Gunicorn
NEBULA_SOCK=nebula.sock

NEBULA_FRONTEND_STATIC_DIR=/nebula/nebula/frontend/static
NEBULA_FRONTEND_TEMPLATES_DIR=/nebula/nebula/frontend/templates
echo "NEBULA_PRODUCTION: $NEBULA_PRODUCTION"
if [ "$NEBULA_PRODUCTION" = "False" ]; then
    echo "Starting Gunicorn in dev mode..."
    poetry run uvicorn app:app --uds /tmp/$NEBULA_SOCK --reload --reload-dir $NEBULA_FRONTEND_DIR --reload-exclude '*.db' --reload-exclude '*.db-journal' --log-level debug --proxy-headers --forwarded-allow-ips "*" &
else
    echo "Starting Gunicorn in production mode..."
    poetry run uvicorn app:app --uds /tmp/$NEBULA_SOCK --reload --reload-dir $NEBULA_FRONTEND_DIR --reload-exclude '*.db' --reload-exclude '*.db-journal' --log-level info --proxy-headers --forwarded-allow-ips "*" &
fi

if [ "$NEBULA_ADVANCED_ANALYTICS" = "False" ]; then
    echo "Starting Tensorboard analytics"
    poetry run tensorboard --host 0.0.0.0 --port 8080 --logdir $NEBULA_LOGS_DIR --window_title "NEBULA Statistics" --reload_interval 30 --max_reload_threads 10 --reload_multifile true &
else
    echo "Starting Aim analytics"
    # --dev flag is used to enable development mode
    # aim server --repo $NEBULA_LOGS_DIR --port 8085 &
    poetry run aim init --repo $NEBULA_LOGS_DIR
    poetry run aim up --repo $NEBULA_LOGS_DIR --port 8080 --base-path /nebula/statistics &
fi

tail -f /dev/null
