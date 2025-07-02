#!/bin/sh
set -e

# 1) Launch the original entrypoint in the background
exec /usr/local/bin/docker-entrypoint.sh.orig "$@" &

pid="$!"

# 2) Wait until PostgreSQL is ready to accept connections
echo "⏳ Waiting for PostgreSQL to be ready..."
until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  sleep 1
done

# 3) Always apply our init SQL
echo "🚀 Applying init-configs.sql..."
psql -v ON_ERROR_STOP=1 \
     -U "$POSTGRES_USER" \
     -d "$POSTGRES_DB" \
     -f /docker-entrypoint-initdb.d/init-configs.sql

# 4) Wait on the main Postgres process
wait "$pid"