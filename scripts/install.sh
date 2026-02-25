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
apt-get install -y software-properties-common curl git rsync ffmpeg redis-server postgresql postgresql-contrib python3-venv python3-pip

PY_BIN="python3.11"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  log "Trying to install Python 3.11 for better dependency compatibility"
  if apt-cache show python3.11 >/dev/null 2>&1; then
    apt-get install -y python3.11 python3.11-venv || true
  else
    log "Python 3.11 packages are unavailable in current APT sources, skipping"
  fi
fi
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
sudo -u postgres psql -d voiceai -c "ALTER SCHEMA public OWNER TO voiceai;"
sudo -u postgres psql -d voiceai -c "GRANT ALL ON SCHEMA public TO voiceai;"
sudo -u postgres psql -d voiceai -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO voiceai;"
sudo -u postgres psql -d voiceai -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO voiceai;"
sudo -u postgres psql -d voiceai -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO voiceai;"
sudo -u postgres psql -d voiceai -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO voiceai;"

log "Building virtualenv"
if [[ ! -d /opt/voice-ai/.venv ]]; then
  "$PY_BIN" -m venv /opt/voice-ai/.venv
fi
/opt/voice-ai/.venv/bin/pip install --upgrade pip setuptools wheel

log "Installing Python requirements"
if ! /opt/voice-ai/.venv/bin/pip install -r /opt/voice-ai/app/requirements.txt; then
  log "Primary dependency install failed, applying fallback for ruaccent-predictor"
  sed -i 's/^ruaccent-predictor==.*/ruaccent-predictor>=1.1.0,<2.0.0/' /opt/voice-ai/app/requirements.txt || true
  /opt/voice-ai/.venv/bin/pip install -r /opt/voice-ai/app/requirements.txt
fi

chown -R voiceai:voiceai /opt/voice-ai

log "Preflight import check"
PYTHONPATH=/opt/voice-ai/app /opt/voice-ai/.venv/bin/python - <<'PY'
import importlib
importlib.import_module('app.models.entities')
importlib.import_module('app.api.main')
importlib.import_module('app.workers.tasks')
print('preflight import ok')
PY

log "Installing systemd units"
install -m 0644 /opt/voice-ai/app/systemd/voice-api.service /etc/systemd/system/voice-api.service
install -m 0644 /opt/voice-ai/app/systemd/voice-worker-preview.service /etc/systemd/system/voice-worker-preview.service
install -m 0644 /opt/voice-ai/app/systemd/voice-worker-train.service /etc/systemd/system/voice-worker-train.service
install -m 0644 /opt/voice-ai/app/systemd/voice-worker-render.service /etc/systemd/system/voice-worker-render.service
install -m 0644 /opt/voice-ai/app/systemd/voice-gradio.service /etc/systemd/system/voice-gradio.service

systemctl daemon-reload
systemctl enable --now voice-api.service voice-worker-preview.service voice-worker-train.service voice-worker-render.service voice-gradio.service

# quick early diagnostic if API failed hard
if ! systemctl is-active --quiet voice-api.service; then
  log "voice-api.service is not active right after start"
  systemctl --no-pager --full status voice-api.service || true
fi

log "Smoke test"
for i in {1..45}; do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    log "Install completed"
    exit 0
  fi
  sleep 1
done

log "voice-api did not become healthy in time"
systemctl --no-pager --full status voice-api.service || true
journalctl -u voice-api.service -n 100 --no-pager || true
exit 1
