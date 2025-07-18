#!/bin/sh
set -e

# 1) Run the original entrypoint and wait for it to finish initialization
/usr/local/bin/docker-entrypoint.sh.orig "$@"

# 2) Wait until PostgreSQL accepts connections to the configured database
echo "⏳ Waiting for PostgreSQL to be ready..."
until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; do
  sleep 1
done

# 3) Apply the SQL initialization script
echo "🚀 Applying init-configs.sql..."
psql -v ON_ERROR_STOP=1 \
     -U "$POSTGRES_USER" \
     -d "$POSTGRES_DB" \
     -f /docker-entrypoint-initdb.d/init-configs.sql
