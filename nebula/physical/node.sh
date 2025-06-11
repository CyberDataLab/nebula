###############################################################################
# RUN NEBULA PHYSICAL NODE ─────────────────────────────────────
###############################################################################
VENV_DIR=".venv" 
APP_PORT=8000

source "${VENV_DIR}/bin/activate"

if pgrep -f "gunicorn .* api:app" &>/dev/null; then
  echo "✔ Gunicorn is already running – nothing to do."
  exit 0
fi

echo "· Launching Gunicorn (Flask) on port ${APP_PORT} …"
export FLASK_APP=api.py
exec gunicorn -w 1 -b "0.0.0.0:${APP_PORT}" "api:app"