# Stage 1: Builder
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt-get update && apt-get install -y software-properties-common \
  && add-apt-repository ppa:deadsnakes/ppa \
  && apt-get update && apt-get install -y \
  python3.11 \
  python3.11-dev \
  python3.11-distutils \
  python3.11-venv \
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
RUN uv sync --group core

# Stage 2: Final
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid

# Install runtime dependencies
RUN apt-get update && apt-get install -y software-properties-common \
  && add-apt-repository ppa:deadsnakes/ppa \
  && apt-get update && apt-get install -y \
  python3.11 \
  python3.11-venv \
  tzdata \
  curl \
  net-tools \
  iproute2 \
  iputils-ping \
  && ln -fs /usr/share/zoneinfo/Europe/Madrid /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata \
  && rm -rf /var/lib/apt/lists/*

# Update alternatives
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2 \
  && update-alternatives --install /usr/bin/python python /usr/bin/python3 1

# Copy virtual environment
COPY --from=builder /app/.venv /.venv
ENV PATH="/.venv/bin:$PATH"

# Note: No entrypoint was defined in the original file, so none is added here.
# If an entrypoint is needed, it should be added.
