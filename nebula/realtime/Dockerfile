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
RUN uv venv
RUN uv pip install -r pyproject.toml

# Stage 2: Final
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    tzdata \
    curl \
    net-tools \
    iproute2 \
    dos2unix \
    && ln -fs /usr/share/zoneinfo/Europe/Madrid /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment
COPY --from=builder /app/.venv /.venv
ENV PATH="/.venv/bin:$PATH"

WORKDIR /app
COPY . .

ENV PYTHONPATH=/app

CMD ["python", "main.py"]
