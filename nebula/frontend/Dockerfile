# Stage 1: Builder
FROM python:3.11-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y \
  build-essential \
  git \
  curl \
  ca-certificates \
  gnupg \
  && rm -rf /var/lib/apt/lists/*

# Install uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"

WORKDIR /app

# Copy dependency definition
COPY pyproject.toml .

# Install dependencies
RUN uv python install 3.11.7
RUN uv python pin 3.11.7
RUN uv sync --group frontend

# Stage 2: Final
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
  tzdata \
  nginx \
  curl \
  net-tools \
  iproute2 \
  iputils-ping \
  dos2unix \
  && ln -fs /usr/share/zoneinfo/Europe/Madrid /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata \
  && rm -rf /var/lib/apt/lists/*

# Copy virtual environment
COPY --from=builder /app/.venv /.venv
ENV PATH="/.venv/bin:$PATH"

WORKDIR /
COPY /nebula/frontend/start_services.sh .
RUN dos2unix start_services.sh && chmod +x start_services.sh

ENTRYPOINT ["/bin/bash", "/start_services.sh"]
