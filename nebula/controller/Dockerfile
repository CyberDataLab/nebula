FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y tzdata \
    && ln -fs /usr/share/zoneinfo/Europe/Madrid /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata

ENV TZ=Europe/Madrid

# Install python3.11.7
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update && apt-get install -y python3.11 python3.11-dev python3.11-distutils python3.11-venv

# Install curl and network tools
RUN apt-get install -y curl net-tools iproute2 iputils-ping

# Update alternatives to make Python 3.11 the default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1

# Install gcc and git
RUN apt-get update && apt-get install -y build-essential gcc g++ clang git make cmake g++-aarch64-linux-gnu dos2unix

# Install docker
RUN apt-get install -y ca-certificates curl gnupg
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
RUN chmod a+r /etc/apt/keyrings/docker.gpg
RUN echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN apt-get update

RUN apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

ADD https://astral.sh/uv/install.sh /uv-installer.sh

RUN sh /uv-installer.sh && rm /uv-installer.sh

ENV PATH="/root/.local/bin/:$PATH"

COPY pyproject.toml .

RUN uv python install 3.11.7

RUN uv python pin 3.11.7

RUN uv sync --group controller --group core

ENV PATH="/.venv/bin:$PATH"

COPY /nebula/controller/start_services.sh .

RUN dos2unix start_services.sh

RUN chmod +x start_services.sh

ENTRYPOINT ["/bin/bash", "/start_services.sh"]
