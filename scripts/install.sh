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
apt-get install -y software-properties-common curl git rsync ffmpeg redis-server postgresql postgresql-contrib python3-venv python3-pip build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev libffi-dev liblzma-dev tk-dev xz-utils

PY_BIN="python3.11"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  log "Trying to install Python 3.11 for XTTS/Coqui compatibility"
  if apt-cache show python3.11 >/dev/null 2>&1; then
    apt-get install -y python3.11 python3.11-venv || true
  else
    log "Python 3.11 packages are unavailable in current APT sources, trying deadsnakes PPA"
    add-apt-repository -y ppa:deadsnakes/ppa || true
    apt-get update || true
    apt-get install -y python3.11 python3.11-venv || true
  fi
fi
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  log "Python 3.11 still missing, building CPython 3.11 from source (one-time)"
  PY311_PREFIX="/opt/python311"
  if [[ ! -x "$PY311_PREFIX/bin/python3.11" ]]; then
    TMPD=$(mktemp -d)
    trap 'rm -rf "$TMPD"' EXIT
    curl -fsSL https://www.python.org/ftp/python/3.11.11/Python-3.11.11.tgz -o "$TMPD/Python-3.11.11.tgz"
    tar -xzf "$TMPD/Python-3.11.11.tgz" -C "$TMPD"
    cd "$TMPD/Python-3.11.11"
    ./configure --prefix="$PY311_PREFIX" --enable-optimizations --with-ensurepip=install
    make -j"$(nproc)"
    make install
    cd - >/dev/null
  fi
  if [[ -x "$PY311_PREFIX/bin/python3.11" ]]; then
    PY_BIN="$PY311_PREFIX/bin/python3.11"
  fi
fi
if ! command -v "$PY_BIN" >/dev/null 2>&1 && [[ ! -x "$PY_BIN" ]]; then
  log "ERROR: Python 3.11 is required for TTS==0.22.0 (XTTS-v2). Unable to install automatically."
  exit 1
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

log "Normalizing dependency pins for XTTS compatibility"
# Ensure resolver-safe NumPy pin for TTS/gruut stack even on partially outdated checkouts
sed -i -E 's/^numpy==2\.[0-9.]+/numpy==1.26.4/' /opt/voice-ai/app/requirements.txt || true

log "Building virtualenv"
if [[ -x /opt/voice-ai/.venv/bin/python ]]; then
  VENV_PY_VER=$(/opt/voice-ai/.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  TARGET_PY_VER=$($PY_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  if [[ "$VENV_PY_VER" != "$TARGET_PY_VER" ]]; then
    log "Recreating venv: existing Python $VENV_PY_VER != target $TARGET_PY_VER"
    rm -rf /opt/voice-ai/.venv
  fi
fi
if [[ ! -d /opt/voice-ai/.venv ]]; then
  "$PY_BIN" -m venv /opt/voice-ai/.venv
fi
/opt/voice-ai/.venv/bin/pip install --upgrade pip setuptools wheel

log "Installing Python requirements"
if ! /opt/voice-ai/.venv/bin/pip install -r /opt/voice-ai/app/requirements.txt; then
  log "Dependency install failed. Retrying once after refreshing requirement file state."
  /opt/voice-ai/.venv/bin/pip install -r /opt/voice-ai/app/requirements.txt || {
    log "ERROR: dependency install still failing. Check Python version and package compatibility.";
    exit 1;
  }
fi

log "Installed core dependency versions"
/opt/voice-ai/.venv/bin/python - <<'PY'
import importlib
import sys

print(f"python={sys.version.split()[0]}")
for module_name in ("numpy", "pandas", "TTS"):
    module = importlib.import_module(module_name)
    print(f"{module_name}={getattr(module, '__version__', 'unknown')}")
PY

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
