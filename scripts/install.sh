#!/usr/bin/env bash
set -euo pipefail

log(){ echo "[$(date +'%F %T')] $*"; }

if [[ $(id -u) -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install.sh" >&2
  exit 1
fi

if [[ -f /etc/os-release ]]; then
  . /etc/os-release
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
    log "Warning: tested on Ubuntu 24.04.x, detected ${PRETTY_NAME:-unknown}"
  fi
fi

log "Installing apt packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y software-properties-common curl git ffmpeg redis-server postgresql postgresql-contrib python3-venv python3-pip

PY_BIN="python3.11"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python3.12"
  apt-get install -y python3.12 python3.12-venv || true
fi
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  log "python3.11/3.12 not found, fallback to python3"
  PY_BIN="python3"
fi

id -u voiceai >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash voiceai

for d in /opt/voice-ai/app /opt/voice-ai/data /opt/voice-ai/data/voices /opt/voice-ai/data/profiles /opt/voice-ai/data/jobs /opt/voice-ai/data/uploads /opt/voice-ai/data/outputs /opt/voice-ai/data/models /opt/voice-ai/logs /opt/voice-ai/scripts /opt/voice-ai/config; do
  mkdir -p "$d"
done

log "Syncing application files"
rsync -a --delete --exclude '.git' ./ /opt/voice-ai/app/
cp -f /opt/voice-ai/app/data/accent_overrides.json /opt/voice-ai/config/accent_overrides.json
[[ -f /opt/voice-ai/config/.env ]] || cp /opt/voice-ai/app/.env.example /opt/voice-ai/config/.env

log "Configuring PostgreSQL"
systemctl enable --now postgresql redis-server
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='voiceai'" | grep -q 1 || sudo -u postgres psql -c "CREATE USER voiceai WITH PASSWORD 'voiceai';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='voiceai'" | grep -q 1 || sudo -u postgres createdb -O voiceai voiceai
sudo -u postgres psql -d voiceai -f /opt/voice-ai/app/sql/init.sql

log "Building virtualenv"
if [[ ! -d /opt/voice-ai/.venv ]]; then
  "$PY_BIN" -m venv /opt/voice-ai/.venv
fi
/opt/voice-ai/.venv/bin/pip install --upgrade pip setuptools wheel
/opt/voice-ai/.venv/bin/pip install -r /opt/voice-ai/app/requirements.txt

chown -R voiceai:voiceai /opt/voice-ai

log "Installing systemd units"
install -m 0644 /opt/voice-ai/app/systemd/voice-api.service /etc/systemd/system/voice-api.service
install -m 0644 /opt/voice-ai/app/systemd/voice-worker-preview.service /etc/systemd/system/voice-worker-preview.service
install -m 0644 /opt/voice-ai/app/systemd/voice-worker-train.service /etc/systemd/system/voice-worker-train.service
install -m 0644 /opt/voice-ai/app/systemd/voice-worker-render.service /etc/systemd/system/voice-worker-render.service
install -m 0644 /opt/voice-ai/app/systemd/voice-gradio.service /etc/systemd/system/voice-gradio.service

systemctl daemon-reload
systemctl enable --now voice-api.service voice-worker-preview.service voice-worker-train.service voice-worker-render.service voice-gradio.service

log "Smoke test"
sleep 3
curl -fsS http://127.0.0.1:8000/health >/dev/null
log "Install completed"
