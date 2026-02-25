# Voice AI MVP (CPU-only, Ubuntu 24.04)

Нативный MVP-сервис синтеза русской речи с voice cloning preview, обучаемыми voice profile, ударениями, режимами `story`/`poem`, REST API + Gradio UI.

## Что реализовано
- **FastAPI API** (`/health`, `/v1/voices`, `/v1/tts`, `/v1/jobs`, и т.д.).
- **Celery workers** (preview/train/render) с Redis broker/backend.
- **PostgreSQL** для метаданных (voices, samples, profiles, jobs, artifacts).
- **CPU TTS backend**: Silero TTS (PyTorch CPU) + profile adaptation (embedding-based style params).
- **Text frontend для русского**:
  - нормализация,
  - поддержка `ё`,
  - автоударения через `ruaccent-predictor`,
  - пользовательские overrides `data/accent_overrides.json`,
  - приоритет: ручные ударения > overrides > auto predictor.
- **Два режима чтения**:
  - `story`: по предложениям, мягкие паузы;
  - `poem`: по строкам, паузы между строками и строфами.
- **Audio pipeline**: ffmpeg convert, trim silence, normalize loudness, chunk render, concat, export wav/mp3.
- **Systemd units**: API, 3 воркера, Gradio UI.
- **Одна команда установки**: `scripts/install.sh`.

## Структура проекта
```text
app/
  api/main.py
  core/config.py
  db/session.py
  models/entities.py
  schemas/api.py
  services/
    repository.py
    tts_backend.py
    audio/processing.py
    text/frontend.py
  workers/
    celery_app.py
    tasks.py
  ui/gradio_app.py
scripts/
  install.sh
  smoke_test.sh
systemd/
  voice-api.service
  voice-worker-preview.service
  voice-worker-train.service
  voice-worker-render.service
  voice-gradio.service
sql/init.sql
requirements.txt
.env.example
data/accent_overrides.json
```

## Установка (одной командой)
```bash
cd /workspace/MyTTS
sudo bash scripts/install.sh
```

## Проверка статуса сервисов
```bash
sudo systemctl status voice-api.service
sudo systemctl status voice-worker-preview.service
sudo systemctl status voice-worker-train.service
sudo systemctl status voice-worker-render.service
sudo systemctl status voice-gradio.service
```

## API smoke
```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/v1/voices
curl -s http://127.0.0.1:8000/v1/jobs
```

## Тестовый POST `/v1/tts`
```bash
curl -s -X POST http://127.0.0.1:8000/v1/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "voice_id": "<VOICE_ID>",
    "profile_id": null,
    "text": "Жили-были дед да баба. У них была курочка Ряба.",
    "mode": "story",
    "format": "wav",
    "speed": 1.0,
    "use_accenting": true,
    "use_user_overrides": true
  }'
```

## UI
- Gradio: `http://127.0.0.1:7860`

## Замены тяжелых компонентов на CPU-friendly
1. **Полный fine-tune TTS** заменен на **light speaker adaptation** через эмбеддинг-профиль (energy + pitch_hint), сохраняемый как profile params JSON.
2. **Production TTS** использует **Silero CPU** вместо тяжелых мультимодельных SOTA стеков.
3. **Voice cloning preview** реализован как zero-shot-like preview на основе референса и профильных параметров (без полного GPU-heavy cloning).

## Локальный запуск без systemd (dev)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.api.main:app --reload
celery -A app.workers.celery_app.celery_app worker -Q preview --loglevel=INFO
celery -A app.workers.celery_app.celery_app worker -Q train --loglevel=INFO
celery -A app.workers.celery_app.celery_app worker -Q render --loglevel=INFO
python -m app.ui.gradio_app
```
