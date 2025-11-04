# syntax=docker/dockerfile:1
FROM postgres:17.5-alpine3.22

# Provide a basic healthcheck so orchestrators can verify readiness. `pg_isready`
# ships with the image, so no extra packages are required.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD pg_isready -d "$${POSTGRES_DB}" -U "$${POSTGRES_USER}" || exit 1
