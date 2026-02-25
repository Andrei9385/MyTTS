# Voice AI MVP (CPU-only, Ubuntu 24.04)

Нативный MVP-сервис синтеза русской речи с voice cloning preview, обучаемыми voice profile, ударениями, режимами `story`/`poem`, REST API + Gradio UI.

## Что реализовано
- **FastAPI API** (`/health`, `/v1/voices`, `/v1/tts`, `/v1/jobs`, и т.д.).
- **Celery workers** (preview/train/render) с Redis broker/backend.
- **PostgreSQL** для метаданных (voices, samples, profiles, jobs, artifacts).
- **CPU TTS backend**: XTTS-v2 (Coqui `tts_models/multilingual/multi-dataset/xtts_v2`) + multi-reference voice cloning + cached profile conditioning.
- **Text frontend для русского**:
  - нормализация,
  - поддержка `ё`,
  - автоударения через `ruaccent` (если пакет доступен в окружении),
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

### TTS с фонемным входом (эксперимент)
```bash
curl -s -X POST http://127.0.0.1:8000/v1/tts \
  -H 'Content-Type: application/json' \
  -d '{
    "voice_id": "<VOICE_ID>",
    "text": "Жила-была Маша",
    "input_mode": "phoneme",
    "phoneme_text": "ZH I L A | B Y L A | M A SH A",
    "mode": "story",
    "format": "wav",
    "speed": 1.0
  }'
```

### G2P API (text -> phoneme stream)
```bash
curl -s -X POST http://127.0.0.1:8000/v1/g2p \
  -H 'Content-Type: application/json' \
  -d '{"text":"Жила-была Маша"}'
```

## UI
- Wizard UI (FastAPI served): `http://127.0.0.1:8000/`
- Legacy Gradio (optional): `http://127.0.0.1:7860`

## Пошаговая инструкция для лучшего качества аудио
1. **Подготовьте качественные референсы голоса**
   - Запишите 3–10 файлов по 5–20 секунд.
   - Используйте тихую комнату, один микрофон, без музыки/эха/шумов.
   - Говорите естественно, средним темпом, не шепотом.

2. **Создайте голос в Wizard (Шаг 1)**
   - Откройте `http://127.0.0.1:8000/`.
   - Укажите понятное имя голоса и загрузите все референсы сразу.
   - Нажмите **«Создать голос»** и дождитесь успешного ответа.

3. **Проверьте preview (Шаг 2)**
   - Используйте 2–3 разные тестовые фразы (короткая, средняя, эмоциональная).
   - Если голос звучит «грязно» или нестабильно — замените самые шумные референсы и повторите шаг 1.

4. **Улучшите профиль (Шаг 3)**
   - Нажмите **«Улучшить профиль»** после успешного preview.
   - Профиль стабилизирует голос на длинных текстах.
   - Для нового набора записей создавайте новый профиль.

5. **Сделайте финальный рендер (Шаг 4)**
   - Для прозы/сказок выбирайте `story`, для стихов — `poem`.
   - Рекомендуемая скорость: `0.9–1.05`.
   - Для максимальной совместимости сначала рендерьте в `wav`, потом при необходимости в `mp3`.

6. **Настройте произношение через overrides**
   - В блоке «Исправить произношение» добавьте проблемные слова.
   - Формат: `слово` → `сло́во`.
   - После добавления override перерендерьте тот же фрагмент для проверки.
   - Для проверки выберите режим ударений **"Только мои overrides"** — так вы сразу поймёте, что применились именно ваши ручные правки.

7. **Проверяйте «Подготовленный текст» в шаге 4**
   - После завершения задачи мастер показывает текст, который реально ушёл в синтез (с уже проставленными ударениями).
   - Если в нём есть `де́ревцем`, а в аудио вы всё равно слышите иначе — это ограничение модели/интонации, а не потеря override.

8. **Итеративно повышайте качество**
   - Лучший результат обычно достигается за 2–3 цикла: референсы → preview → профиль → рендер.
   - Если артефакты остаются, уменьшайте длину входного текста (по абзацам) и проверяйте каждый блок отдельно.

### Практические рекомендации
- Оптимальная частота исходной записи: 44.1kHz или 48kHz, mono/stereo не критично (конвертация выполняется в пайплайне).
- Не смешивайте очень разные условия записи (разные помещения/микрофоны) в одном голосе.
- Для длинных задач сначала проверяйте короткий pilot-фрагмент 1–2 предложения.
- Если после обновления страницы шаг «завис», используйте кнопку **«Сбросить текущий шаг»** в Wizard и запустите шаг заново.

## Точная инструкция для вашего текста (про Машеньку)
1. **Режим в шаге 4**: выберите `story (проза)`, а не `poem`.
2. **Скорость**: начните с `0.95` (если слишком медленно — `1.0`).
3. **Формат**: сначала `wav`, после проверки можно `mp3`.
4. **Сделайте 2 прохода**:
   - проход A: синтез без изменений, послушайте проблемные слова;
   - проход B: добавьте overrides и синтезируйте снова.

### Рекомендуемые overrides для этого текста
Добавьте в блоке «Ручная правка ударений» (слово → форма):
- `деревцем` → `де́ревцем`
- `чащу` → `ча́щу`
- `избушка` → `избу́шка`
- `ставенки` → `ста́венки`
- `души` → `души́` (если модель читает не так, как вы хотите)

> Важно: указывайте форму **с тем же написанием**, что в тексте. Например, `деревцем`, а не `деревце`.

### Что делать в шаге 3 «Улучшение профиля»
- Это **необязательный** шаг, но он помогает на длинных текстах.
- Нажмите «Создать/улучшить профиль» один раз после удачного preview.
- Дальше синтезируйте текст в шаге 4 уже с этим профилем.
- Если вы добавили новые качественные референсы голоса, снова выполните шаг 3.

## Замены тяжелых компонентов на CPU-friendly
1. **Полный fine-tune TTS** заменен на **light speaker adaptation** через эмбеддинг-профиль (energy + pitch_hint), сохраняемый как profile params JSON.
2. **Production TTS** использует **XTTS-v2 (Coqui TTS)** как основной движок клонирования голоса.
3. **Voice cloning preview** реализован через XTTS conditioning на основе референса и профильных параметров (CPU-first deployment).

## Важно про ударения: что реально можно ожидать
- В текущем MVP используется **XTTS-v2** и для русского он не гарантирует 100% строгое соблюдение ударений во всех фразах.
- Шаг 3 «Улучшение профиля» улучшает стабильность тембра/голоса, но **не является полноценным обучением орфоэпии**.
- Ручные overrides и режимы `stress_hint_mode` — это подсказки модели, а не жёсткая команда произношения.

### Практическая матрица режимов ударений (рекомендуемый порядок)
1. `stress_hint_mode = none` — базовый и самый «чистый» текст.
2. `stress_hint_mode = plus` — если базовый режим игнорирует ударение в отдельных словах.
3. `stress_hint_mode = plus_and_acute` — если нужно усилить подсказку, но без искажения слов.

> Если слово критично и все 3 режима дают неверный результат, это ограничение текущей модели XTTS-v2 для конкретного контекста.

## Можно ли решить это обучением?
Кратко: **частично**, но не в рамках текущего lightweight-профиля.

Чтобы заметно повысить управляемость ударений, обычно нужен другой пайплайн:
- фонемизация текста (G2P) с явным ударением,
- TTS/вокодер, принимающий фонемный вход,
- отдельное дообучение на русскоязычном датасете с качественными транскрипциями.

То есть для «гарантируемых» ударений требуется переход от text-to-wave подсказок к phoneme-driven схеме.

## План миграции (если нужен строгий контроль ударений)
1. ✅ Добавлен опциональный G2P-слой перед синтезом (`POST /v1/g2p`: `text -> phoneme_text`).
2. ✅ В API добавлен режим `input_mode = text|phoneme` и поле `phoneme_text`.
3. ✅ Для `phoneme` в job/UI сохраняются обе формы: исходный text и `backend_text` после конвертации.
4. ⏳ Прогнать A/B-тесты на целевом корпусе сказок (20–50 фраз) и зафиксировать стабильный режим.

## Дообучение XTTS (экспериментальный старт)
Добавлен вспомогательный скрипт:
```bash
python scripts/fine_tune_xtts.py --dataset-dir /path/to/dataset --output-dir /path/to/output
```

- Скрипт проверяет структуру датасета (`metadata.csv` + `wavs/`) и печатает команду запуска.
- Для реального запуска добавьте `--run`.
- Это **отдельный путь** от легковесного шага “Улучшение профиля” в Wizard.

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


## New persistence
- Added `ui_sessions` table for wizard state restore after refresh/restart.
