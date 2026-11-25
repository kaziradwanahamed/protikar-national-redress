import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

app = Celery("bd_grievance_platform")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_routes = {
    "apps.ai_triage.tasks.*": {"queue": "ai_triage"},
    "apps.esb.tasks.*": {"queue": "esb"},
    "apps.workflow.tasks.*": {"queue": "workflow"},
}

app.conf.beat_schedule = {
    "sla-breach-watchdog-every-5-min": {
        "task": "apps.workflow.tasks.check_sla_breaches",
        "schedule": crontab(minute="*/5"),
    },
    "tier2-legacy-rpa-bridge-every-10-min": {
        "task": "apps.esb.tasks.poll_tier2_legacy_portals",
        "schedule": crontab(minute="*/10"),
    },
    "doptor-organogram-sync-nightly": {
        "task": "apps.esb.tasks.sync_doptor_organogram",
        "schedule": crontab(hour=2, minute=30),
    },
}
