from celery import shared_task

from apps.workflow.services.escalation_daemon import SLAEscalationDaemon


@shared_task(bind=True, max_retries=3)
def check_sla_breaches(self):
    """Celery Beat daemon (every 5 minutes) enforcing SLA warnings, 4-tier escalations & 72h auto-close."""
    return SLAEscalationDaemon.run_sweep()
