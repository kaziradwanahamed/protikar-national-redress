from config.settings.base import *  # noqa: F401, F403

DEBUG = True
DEMO_MODE = True
ALLOWED_HOSTS = ["*"]

# Local zero-dependency media storage (no MinIO required for `manage.py runserver`)
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Zero-dependency in-memory Cache & Channels layer for local Ubuntu runserver
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "bd-grievance-dev-cache",
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Run Celery tasks & AI triage synchronously when Redis/Kafka/ai-service are not running locally
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
USE_REMOTE_AI_SERVICE = env.bool("USE_REMOTE_AI_SERVICE", default=False)
