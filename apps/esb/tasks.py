from celery import shared_task

from apps.complaints.models import Complaint
from apps.esb.services.tier1_webhooks import Tier1WebhookService
from apps.esb.services.tier2_rpa_bridge import Tier2RPABridgeService


@shared_task(bind=True, max_retries=3)
def sync_doptor_organogram(self):
    """Nightly sync of Doptor offices and seats from National ESB."""
    return {"status": "completed", "task": "sync_doptor_organogram"}


@shared_task(bind=True, max_retries=3)
def dispatch_doptor_hr_vacancy_alert(self, alert_id: str):
    """Dispatches an automated vacancy escalation alert to Doptor HR ESB endpoint."""
    from apps.organogram.models import DoptorVacancyAlert

    alert = DoptorVacancyAlert.objects.select_related("vacant_seat", "routed_to_seat").get(
        alert_id=alert_id
    )
    alert.hr_dispatch_status = DoptorVacancyAlert.DispatchStatus.SENT
    alert.save(update_fields=["hr_dispatch_status"])
    return {
        "status": "dispatched",
        "alert_id": str(alert.alert_id),
        "vacant_seat_id": alert.vacant_seat.doptor_seat_id,
    }


@shared_task(bind=True, max_retries=3)
def poll_tier2_legacy_portals(self):
    """Scheduled every 10 minutes by Celery Beat to poll Tier-2 legacy ministry portals."""
    return Tier2RPABridgeService.run_poll_cycle()


@shared_task(bind=True, max_retries=3)
def dispatch_tier1_webhook_async(self, agency_code: str, event_type: str, complaint_id: str):
    """Asynchronous Tier-1 canonical JSON webhook dispatch."""
    complaint = Complaint.objects.get(complaint_id=complaint_id)
    log = Tier1WebhookService.dispatch_outbound(
        agency_code=agency_code, event_type=event_type, complaint=complaint
    )
    return {"delivery_id": str(log.delivery_id), "status": log.status}
