from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery('voiceai', broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.task_routes = {
    'app.workers.tasks.run_preview': {'queue': settings.celery_preview_queue},
    'app.workers.tasks.run_train': {'queue': settings.celery_train_queue},
    'app.workers.tasks.run_tts': {'queue': settings.celery_render_queue},
}
celery_app.conf.task_track_started = True
