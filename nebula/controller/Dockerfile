# Stage 1: Builder
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

# Install Python and build dependencies
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

COPY pyproject.toml .

RUN uv python install 3.11.7
RUN uv python pin 3.11.7
RUN uv sync --group controller

# Stage 2: Final
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Madrid

# Install Python runtime and utilities
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
  dos2unix \
  && ln -fs /usr/share/zoneinfo/Europe/Madrid /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata \
  && rm -rf /var/lib/apt/lists/*

# Update alternatives
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2 \
  && update-alternatives --install /usr/bin/python python /usr/bin/python3 1

# Copy virtual environment
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /
COPY /nebula/controller/start_services.sh .
RUN dos2unix start_services.sh && chmod +x start_services.sh

ENTRYPOINT ["/bin/bash", "/start_services.sh"]
