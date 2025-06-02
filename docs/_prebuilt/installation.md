# **Installation**

Welcome to the NEBULA platform installation guide. This document explains how to obtain, install, run, and troubleshoot NEBULA.

## **Prerequisites**

For the best experience, ensure the following prerequisites are met:

- **Linux** (Ubuntu 20.04 LTS recommended) or **macOS** (10.15 Catalina or later). Currently, we do not maintain an up-to-date version for Windows.
- Minimum **8 GB RAM** (+32 GB recommended for virtualized devices).
- Minimum **20 GB disk space** for Docker images and containers. Additional space is required for datasets, models, and results.
- **Docker Engine** 24.0.4 or higher (24.0.7 recommended, https://docs.docker.com/engine/install/)
- **Docker Compose** 2.19.0 or higher (2.19.1 recommended, https://docs.docker.com/compose/install/)

## **Obtaining NEBULA**

You can obtain the source code from https://github.com/CyberDataLab/nebula

Or clone the repository using git:

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">git clone https://github.com/CyberDataLab/nebula.git</span></code></pre>

Now, you can move to the source directory:

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">cd nebula</span></code></pre>

### **Installing NEBULA**

Install required dependencies and set up Docker containers by running:

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">make install</span></code></pre>

Next, activate the virtual environment:

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">source .venv/bin/activate</span></code></pre>

If you forget this command, you can type:

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">make shell</span></code></pre>

Your shell prompt should look similar to:

<pre><code><span style="color: grey;">(nebula-dfl)</span> <span style="color: blue;">user@host</span>:~$</code></pre>

### **Using NVIDIA GPU on Nodes (Optional)**

For nodes equipped with **NVIDIA GPUs**, ensure the following prerequisites:

- **NVIDIA Driver**: Version 525.60.13 or later.
- **CUDA**: Version 12.1 is required. After installation, verify with <code>nvidia-smi</code>.
- **NVIDIA Container Toolkit**: Install to enable GPU access within Docker containers.

Follow these guides for proper installation:

- [CUDA Installation Guide for Linux](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/index.html)
- [NVIDIA Container Toolkit Installation Guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

Note: Ensure that the CUDA toolkit version is compatible with your driver and, if needed, update the Docker runtime to support GPU integration.

## **Running NEBULA**

Once the installation is finished, you can check if NEBULA is installed properly using:

<pre><code><span style="color: grey;">(nebula-dfl) </span><span style="color: blue;">user@host</span>:~$ <span style="color: green;">python app/main.py --version</span></code></pre>

To run NEBULA, you can use the following command line:

<pre><code><span style="color: grey;">(nebula-dfl)</span> <span style="color: blue;">user@host</span>:~$ <span style="color: green;">python app/main.py</span></code></pre>

Note: The first run may build the nebula-frontend Docker image, which can take a few minutes.

Display available parameters:

<pre><code><span style="color: grey;">(nebula-dfl)</span> <span style="color: blue;">user@host</span>:~$ <span style="color: green;">python app/main.py --help</span></code></pre>

By default, the frontend is available at http://127.0.0.1:6060. If the 6060 port is unavailable, a random port will be assigned automatically and prompted in the console.

Also, you can define the specific port using the following command line:

<pre><code><span style="color: grey;">(nebula-dfl)</span> <span style="color: blue;">user@host</span>:~$ <span style="color: green;">python app/main.py --webport [PORT]</span></code></pre>

and the default port of the statistics endpoint:

<pre><code><span style="color: grey;">(nebula-dfl)</span> <span style="color: blue;">user@host</span>:~$ <span style="color: green;">python app/main.py --statsport [PORT]</span></code></pre>

## **NEBULA Frontend Credentials**

You can log in with the default credentials:

    - User: admin
    - Password: admin

If these do not work, please contact Enrique Tomás Martínez Beltrán at [enriquetomas@um.es](mailto:enriquetomas@um.es).

## **Stopping NEBULA**

To stop NEBULA, you can use the following command line:

<pre><code><span style="color: grey;">(nebula-dfl)</span> <span style="color: blue;">user@host</span>:~$ <span style="color: green;">python app/main.py --stop</span></code></pre>

Be careful! This command will stop all the containers related to NEBULA:
Frontend, Controller, and Nodes.

## **Troubleshooting**

If frontend is not working, check the logs in app/logs/frontend.log

If any of the following errors appear, take a look at the docker logs of
the nebula-frontend container:

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">docker logs user_nebula-frontend</span></code></pre>

------------------------------------------------------------------------

Network nebula_X Error failed to create network nebula_X: Error response
from daemon: Pool overlaps with other one on this address space

Solution: Delete the docker network nebula_X

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">docker network rm nebula_X</span></code></pre>

------------------------------------------------------------------------

Error: Cannot connect to the Docker daemon at
unix:///var/run/docker.sock. Is the docker daemon running?

Solution: Start the docker daemon

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">sudo dockerdX</span></code></pre>

Solution: Enable the following option in Docker Desktop

Settings -> Advanced -> Allow the default Docker socket to be used

> ![Docker required options](static/docker-required-options.png)

------------------------------------------------------------------------

Error: Cannot connect to the Docker daemon at tcp://X.X.X.X:2375. Is the
docker daemon running?

Solution: Start the docker daemon

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">sudo dockerd -H tcp://X.X.X.X:2375</span></code></pre>

------------------------------------------------------------------------

If frontend is not working, restart docker daemon

<pre><code><span style="color: blue;">user@host</span>:~$ <span style="color: green;">sudo systemctl restart docker</span></code></pre>

------------------------------------------------------------------------

Error: Too many open files

Solution: Increase the number of open files

> ulimit -n 65536

Also, you can add the following lines to the file
/etc/security/limits.conf

> -   soft nofile 65536
> -   hard nofile 65536
