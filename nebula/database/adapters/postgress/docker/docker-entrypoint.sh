#!/bin/sh
set -x

# Start the python API in the background
echo "🐍 Starting Nebula Database API in the background..."
(
  # Wait for postgres to be ready
  until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" -h localhost >/dev/null 2>&1; do
    sleep 1
  done
  echo "✅ PostgreSQL is ready, starting API."

  cd nebula
  NEBULA_SOCK=nebula.sock

  uvicorn nebula.database.database_api:app --host 0.0.0.0 --port 5051 --log-level debug --proxy-headers --forwarded-allow-ips "*"
) &

# Run the original postgres entrypoint in the foreground
# This will become the main process of the container
exec /usr/local/bin/docker-entrypoint.sh.orig "$@"
