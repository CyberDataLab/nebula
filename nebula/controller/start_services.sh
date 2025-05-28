#!/bin/bash

# Print commands and their arguments as they are executed (debugging)
set -x

# Print in console debug messages
echo "Starting services..."

cd nebula
echo "path $(pwd)"
# Start Gunicorn
NEBULA_SOCK=nebula.sock

echo "NEBULA_PRODUCTION: $NEBULA_PRODUCTION"
if [ "$NEBULA_PRODUCTION" = "False" ]; then
    echo "Starting Gunicorn in dev mode..."
    uvicorn nebula.controller.controller:app --host 0.0.0.0 --port 5000  &
else
    echo "Starting Gunicorn in production mode..."
    uvicorn nebula.controller.controller:app --host 0.0.0.0 --port 5000  &
fi

tail -f /dev/null
