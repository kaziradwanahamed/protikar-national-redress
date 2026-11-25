from celery import shared_task

from apps.ai_triage.services.pipeline import AITriageOrchestrator
from apps.ai_triage.services.splitter import CompoundComplaintSplitter
from apps.complaints.models import Complaint


@shared_task(bind=True, max_retries=3)
def run_complaint_triage(self, complaint_id: str, photo_urls: list[str] | None = None):
    """Async Celery task executing full Multimodal + Classifier + PostGIS + Dedup/Split triage."""
    complaint = Complaint.objects.get(complaint_id=complaint_id)
    run = AITriageOrchestrator.process_complaint(
        complaint=complaint, photo_urls=photo_urls or []
    )
    return {
        "run_id": str(run.run_id),
        "complaint_id": str(complaint.complaint_id),
        "routing_decision": run.routing_decision,
        "confidence_score": run.confidence_score,
    }


@shared_task(bind=True, max_retries=3)
def release_subticket_dependencies(self, completed_ticket_id: str):
    """Unblocks and routes dependent child sub-tickets once a prerequisite agency finishes."""
    completed = Complaint.objects.get(complaint_id=completed_ticket_id)
    released = CompoundComplaintSplitter.release_dependent_subtickets(completed)
    return {
        "completed_ticket_id": completed_ticket_id,
        "released_tracking_codes": [c.tracking_code for c in released],
    }
