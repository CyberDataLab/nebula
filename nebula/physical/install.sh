#!/usr/bin/env bash
###############################################################################
# Provision *once* (or update safely) a Raspberry Pi node that will:
#
#   • run inside a DietPi / Debian 12 “Bookworm” ARM64 image
#   • join a Tailscale network
#   • clone the *Nebula-DFL* repository (or update it if already there)
#   • create a per-project Python 3.11 virtual-env with **uv**
#
# Every section is **idempotent**: re-running the script will skip work that is
# already done and only apply missing pieces.
#
# Usage ────────────────────────────────────────────────────────────────────────
#   ./idempotent_node.sh               # run locally on the Pi (as dietpi user)
#
###############################################################################
set -euo pipefail

###############################################################################
# USER CONFIGURATION
###############################################################################
AUTH_KEY="tskey-auth-k26BCauJup11CNTRL-Ytj6n6t6dNCK7nhdDhY4NC8VvsBC2Xvc"  # ← EDIT
REPO_URL="https://github.com/CyberDataLab/nebula.git"
REPO_BRANCH="physical-deployment"
PY_VERSION="3.11.7"               # exact CPython build to install with `uv`
VENV_DIR=".venv"                  # venv folder inside the repo
###############################################################################

sudo -v  # cache sudo credentials once

###############################################################################
# 0 ▸ TIME & CLOCK ────────────────────────────────────────────────────────────
# Synchronise the RTC/NTP early to avoid “Release file … not valid yet” apt
# errors when the Pi’s clock is far in the past.
###############################################################################
echo "· Syncing system clock with NTP …"
sudo timedatectl set-ntp true
sudo timedatectl set-timezone Europe/Madrid
for _ in {1..15}; do
  timedatectl | grep -q "System clock synchronized: yes" && break
  sleep 1
done

###############################################################################
# 1 ▸ APT SOURCE CLEAN-UP ─────────────────────────────────────────────────────
# DietPi sometimes duplicates entries; remove known offenders so that
# `apt-get update` stays quiet.
###############################################################################
for list in \
  /etc/apt/sources.list.d/backports.list \
  /etc/apt/sources.list.d/dietpi-tailscale.list
do
  [[ -f "${list}" ]] && sudo rm -f "${list}"
done

###############################################################################
# 2 ▸ TAILSCALE REPOSITORY  (one-off) ─────────────────────────────────────────
###############################################################################
TS_LIST="/etc/apt/sources.list.d/tailscale.list"
if [[ ! -f "${TS_LIST}" ]]; then
  echo "· Adding Tailscale APT repository …"
  curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.gpg |
    sudo tee /usr/share/keyrings/tailscale-archive-keyring.asc >/dev/null
  echo "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.asc] \
https://pkgs.tailscale.com/stable/debian bookworm main" |
    sudo tee "${TS_LIST}" >/dev/null
fi

###############################################################################
# 3 ▸ BASE PACKAGES ───────────────────────────────────────────────────────────
###############################################################################
echo "· Updating APT cache and installing base packages …"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive \
  apt-get install -y --no-install-recommends \
    tzdata curl net-tools iproute2 iputils-ping \
    build-essential gcc g++ clang git make cmake \
    python3.11 python3.11-venv tailscale

###############################################################################
# 4 ▸ ENSURE systemd DBus (DietPi ≠ systemd by default) ──────────────────────
###############################################################################
SYSTEMCTL_OK=false
if command -v systemctl &>/dev/null; then
  if ! systemctl is-system-running &>/dev/null; then
    echo "· Installing dbus so that systemctl can talk to systemd …"
    sudo apt-get install -y --no-install-recommends dbus
    sudo systemctl unmask systemd-logind.service 2>/dev/null || true
    sudo systemctl start  systemd-logind.service 2>/dev/null || true
    sudo systemctl restart dbus.service          2>/dev/null || true
    sleep 2
  fi
  systemctl is-system-running &>/dev/null && SYSTEMCTL_OK=true
fi
${SYSTEMCTL_OK} || echo "⚠ systemctl unavailable — Tailscale service will not be enabled"

###############################################################################
# 5 ▸ TAILSCALE UP  (idempotent) ──────────────────────────────────────────────
###############################################################################
if ! tailscale status --json &>/dev/null; then
  echo "· Connecting to Tailscale …"
  sudo tailscale up --reset --auth-key="${AUTH_KEY}"
fi
${SYSTEMCTL_OK} && sudo systemctl enable tailscaled 2>/dev/null || true

###############################################################################
# 6 ▸ PYTHON 3.11 AS DEFAULT ──────────────────────────────────────────────────
###############################################################################
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2
sudo update-alternatives --install /usr/bin/python  python  /usr/bin/python3     1

###############################################################################
# 7 ▸ CLONE / UPDATE REPOSITORY ───────────────────────────────────────────────
###############################################################################
wget "${REPO_BRANCH}"

###############################################################################
# 8 ▸ UV & VENV ───────────────────────────────────────────────────────────────
###############################################################################
if ! command -v uv &>/dev/null; then
  echo "· Installing UV package manager …"
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "· Creating Python ${PY_VERSION} virtual-env with uv …"
  uv python install "${PY_VERSION}"
  uv python pin     "${PY_VERSION}"
  uv venv "${VENV_DIR}"
fi

# Activate venv
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

# Install project core dependencies (from pyproject.toml’s [tool.uv] groups)
uv sync --group core

###############################################################################
# 9 ▸ RUNTIME DEPS (Flask + Gunicorn) ─────────────────────────────────────────
###############################################################################
uv pip install --upgrade --no-cache-dir \
  "Flask>=3.0,<4.0" "gunicorn>=22.0"
