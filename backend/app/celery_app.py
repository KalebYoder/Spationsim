from celery import Celery
from .core.config import settings

celery_app = Celery(
    "spationsim",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.tick"],
)

celery_app.conf.beat_schedule = {
    "game-tick": {
        "task": "app.tasks.tick.run_tick",
        "schedule": 7200.0,  # 2 hours in seconds
    },
}

celery_app.conf.timezone = "UTC"
celery_app.conf.broker_connection_retry_on_startup = True
