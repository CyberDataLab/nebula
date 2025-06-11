#!/usr/bin/env bash

# Halt on first error, undefined var, or any failure in a pipeline
set -euo pipefail

# Error handler: reports the line number and exits
error_handler() {
    local lineno=$1
    echo "❌ Error occurred on line ${lineno}. Aborting." >&2
    exit 1
}

# Trap any command that fails and invoke the handler
trap 'error_handler $LINENO' ERR

# Activate virtual environment
if [[ -f ".venv/bin/activate" ]]; then
    source .venv/bin/activate
    echo "✅ Virtual environment activated."
else
    echo "❌ Virtual environment not found at .venv/bin/activate" >&2
    exit 1
fi

# Change into app/ directory
if cd app/; then
    echo "✅ Changed directory to app/"
else
    echo "❌ Could not change directory to app/" >&2
    exit 1
fi

# Run the Python script
if [[ -f "main.py" ]]; then
    echo "🔄 Running main.py..."
    python main.py
    echo "✅ main.py completed successfully."
else
    echo "❌ main.py not found in app/" >&2
    exit 1
fi
