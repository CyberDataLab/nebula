#!/bin/bash

# Print commands and their arguments as they are executed (debugging)
set -x

# Print in console debug messages
echo "Starting services..."

cd nebula
echo "path $(pwd)"
# Start Gunicorn
NEBULA_SOCK=nebula.sock

echo "Starting Gunicorn..."
uvicorn nebula.controller.controller:app --host 0.0.0.0 --port $NEBULA_CONTROLLER_PORT --log-level debug --proxy-headers --forwarded-allow-ips "*" &

tail -f /dev/null
