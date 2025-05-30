#!/bin/bash

# Print commands and their arguments as they are executed (debugging)
set -x

# Print in console debug messages
echo "Starting services..."

# Start Nginx in the foreground in a subshell for the script to proceed
nginx &

# Change directory to where app.py is located
NEBULA_FRONTEND_DIR=/nebula/nebula/frontend
cd $NEBULA_FRONTEND_DIR

# Start Gunicorn
NEBULA_SOCK=nebula.sock

NEBULA_FRONTEND_STATIC_DIR=/nebula/nebula/frontend/static
NEBULA_FRONTEND_TEMPLATES_DIR=/nebula/nebula/frontend/templates
echo "NEBULA_PRODUCTION: $NEBULA_PRODUCTION"
if [ "$NEBULA_PRODUCTION" = "False" ]; then
    echo "Starting Gunicorn in dev mode..."
    uvicorn app:app --uds /tmp/$NEBULA_SOCK --log-level debug --proxy-headers --forwarded-allow-ips "*" &
else
    echo "Starting Gunicorn in production mode..."
    uvicorn app:app --uds /tmp/$NEBULA_SOCK --log-level info --proxy-headers --forwarded-allow-ips "*" &
fi

if [ "$NEBULA_ADVANCED_ANALYTICS" = "False" ]; then
    echo "Starting Tensorboard analytics"
    tensorboard --host 0.0.0.0 --port 8080 --logdir $NEBULA_LOGS_DIR --window_title "NEBULA Statistics" --reload_interval 30 --max_reload_threads 10 --reload_multifile true &
else
    echo "Advanced analytics are enabled"
fi

tail -f /dev/null
