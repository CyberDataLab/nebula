FROM postgres:17.5-alpine3.22

# Rename the official entrypoint so we can wrap it
RUN mv /usr/local/bin/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh.orig

# Copy SQL init file and custom entrypoint script
COPY /nebula/database/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Install Python 3.11.7 from source
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    make \
    openssl-dev \
    bzip2-dev \
    zlib-dev \
    xz-dev \
    readline-dev \
    sqlite-dev \
    libffi-dev \
    curl \
    tar \
    bash

ENV PYTHON_VERSION=3.11.7

RUN curl -O https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz && \
    tar -xzf Python-${PYTHON_VERSION}.tgz && \
    cd Python-${PYTHON_VERSION} && \
    ./configure --prefix=/usr/local --enable-optimizations && \
    make -j$(nproc) && \
    make install && \
    cd .. && rm -rf Python-${PYTHON_VERSION}*

RUN python3.11 --version

# Install uv (alternative to pip, very fast)
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin/:$PATH"

# Install Python dependencies using uv
COPY pyproject.toml .
RUN uv python pin 3.11.7
RUN uv sync --group database

ENV PATH=".venv/bin:$PATH"

# ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# CMD ["postgres"]
