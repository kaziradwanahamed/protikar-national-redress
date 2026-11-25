"""Prometheus metrics & NDC readiness probe endpoints for the Grievance Platform."""

from __future__ import annotations

from django.db import connection
from django.http import HttpResponse, JsonResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from apps.complaints.models import AuditLog, Complaint
from apps.disaster.models import CrisisZone, EmergencyCommandDispatch
from apps.workflow.models import EscalationEvent


def readiness_probe(_request):
    """Deep readiness check verifying PostgreSQL/PostGIS connectivity."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT PostGIS_Version();")
            postgis_ver = cursor.fetchone()[0]
    except Exception as exc:
        return JsonResponse({"status": "unready", "error": str(exc)}, status=503)
    return JsonResponse({"status": "ready", "postgis": postgis_ver})


def prometheus_metrics(_request):
    """Live Prometheus exposition endpoint scraped by NDC Prometheus."""
    registry = CollectorRegistry()

    g_complaints = Gauge(
        "bd_grievance_complaints_total",
        "Total complaints grouped by statutory status",
        ["status"],
        registry=registry,
    )
    for status_val, _label in Complaint.ComplaintStatus.choices:
        cnt = Complaint.objects.filter(status=status_val).count()
        if cnt > 0:
            g_complaints.labels(status=status_val).set(cnt)

    Gauge(
        "bd_grievance_sla_breaches_total",
        "Total 100% SLA breach escalations recorded",
        registry=registry,
    ).set(
        EscalationEvent.objects.filter(
            event_type=EscalationEvent.EventType.SLA_BREACH_100
        ).count()
    )

    Gauge(
        "bd_grievance_active_crisis_zones",
        "Currently active Disaster Crisis Zones",
        registry=registry,
    ).set(CrisisZone.objects.filter(is_active=True).count())

    Gauge(
        "bd_grievance_fastlane_dispatches_total",
        "Total P1 Life-Safety Fast-Lane emergency dispatches",
        registry=registry,
    ).set(EmergencyCommandDispatch.objects.count())

    Gauge(
        "bd_grievance_audit_ledger_entries_total",
        "Total immutable SHA-256 AuditLog entries",
        registry=registry,
    ).set(AuditLog.objects.count())

    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
