from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'voice-ai'
    app_host: str = '0.0.0.0'
    app_port: int = 8000

    database_url: str = 'postgresql+psycopg2://voiceai:voiceai@127.0.0.1:5432/voiceai'
    redis_url: str = 'redis://127.0.0.1:6379/0'

    data_root: str = '/opt/voice-ai/data'
    uploads_dir: str = '/opt/voice-ai/data/uploads'
    voices_dir: str = '/opt/voice-ai/data/voices'
    profiles_dir: str = '/opt/voice-ai/data/profiles'
    jobs_dir: str = '/opt/voice-ai/data/jobs'
    outputs_dir: str = '/opt/voice-ai/data/outputs'
    models_dir: str = '/opt/voice-ai/data/models'
    accent_overrides_path: str = 'data/accent_overrides.json'

    celery_preview_queue: str = 'preview'
    celery_train_queue: str = 'train'
    celery_render_queue: str = 'render'


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
