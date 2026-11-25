import uuid
from django.contrib.gis.db import models as gis_models
from django.db import models
from django.utils import timezone

from apps.complaints.models import Complaint
from apps.organogram.models import ServiceAreaPolygon


class CrisisZone(gis_models.Model):
    """
    Active or historical disaster polygon where Crisis Mode Circuit Breaker is engaged
    (auto-triggered at >5x rolling baseline velocity or manually toggled by MoDMR/DC).
    """

    class DisasterType(models.TextChoices):
        CYCLONE = "CYCLONE", "Cyclone / Storm Surge"
        FLOOD = "FLOOD", "Monsoon / Riverine Flood"
        FLASH_FLOOD = "FLASH_FLOOD", "Haor / Flash Flood"
        EARTHQUAKE = "EARTHQUAKE", "Earthquake"
        FIRE_INDUSTRIAL = "FIRE_INDUSTRIAL", "Major Urban / Industrial Fire"
        HEATWAVE = "HEATWAVE", "Severe Heatwave / Health Crisis"

    class TriggerSource(models.TextChoices):
        AUTO_5X_VELOCITY = "AUTO_5X_VELOCITY", "Automatic 5x Rolling Velocity Circuit Breaker"
        MODMR_TOGGLE = "MODMR_TOGGLE", "MoDMR Manual Emergency Toggle"
        DC_TOGGLE = "DC_TOGGLE", "Deputy Commissioner (DC) Emergency Toggle"

    crisis_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crisis_code = models.CharField(max_length=64, unique=True, db_index=True)
    name_en = models.CharField(max_length=255)
    name_bn = models.CharField(max_length=255, blank=True)
    disaster_type = models.CharField(
        max_length=24, choices=DisasterType.choices, default=DisasterType.FLOOD, db_index=True
    )
    trigger_source = models.CharField(
        max_length=24, choices=TriggerSource.choices, db_index=True
    )
    affected_area_polygon = models.ForeignKey(
        ServiceAreaPolygon,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="crisis_zones",
    )
    geom = gis_models.MultiPolygonField(
        srid=4326,
        spatial_index=True,
        help_text="WGS84 MultiPolygon defining the active disaster surge boundary.",
    )
    baseline_rate_per_hour = models.FloatField(default=10.0)
    peak_rate_per_hour = models.FloatField(default=0.0)
    frozen_ticket_count = models.PositiveIntegerField(default=0)

    is_active = models.BooleanField(default=True, db_index=True)
    activated_by_seat = models.CharField(max_length=64, blank=True)
    activated_at = models.DateTimeField(default=timezone.now, db_index=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "disaster_crisis_zone"
        ordering = ["-activated_at"]

    def __str__(self) -> str:
        return f"CrisisZone({self.crisis_code} | active={self.is_active})"


class EmergencyCommandDispatch(gis_models.Model):
    """
    P1 Life-Safety Fast-Lane record streamed directly to 999, Fire Service,
    Armed Forces Disaster Cells, and CPP volunteers bypassing routine queues.
    """

    class DispatchStatus(models.TextChoices):
        STREAMED = "STREAMED", "Streamed to Emergency Command"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged by Responder"
        RESCUE_DISPATCHED = "RESCUE_DISPATCHED", "Rescue Team Dispatched"
        RESOLVED = "RESOLVED", "Victim Rescued / Resolved"

    dispatch_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    crisis_zone = models.ForeignKey(
        CrisisZone,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="fastlane_dispatches",
    )
    complaint = models.ForeignKey(
        Complaint,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="emergency_dispatches",
    )
    citizen_phone = models.CharField(max_length=24, blank=True)
    raw_message = models.TextField()
    matched_rescue_keywords = models.JSONField(default=list, blank=True)
    geo_point = gis_models.PointField(
        geography=True, srid=4326, null=True, blank=True, spatial_index=True
    )
    h3_res8_index = models.CharField(max_length=20, blank=True, db_index=True)
    target_responders = models.JSONField(default=list, blank=True)
    kafka_topic = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=24,
        choices=DispatchStatus.choices,
        default=DispatchStatus.STREAMED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "disaster_emergency_command_dispatch"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"FastLane({self.dispatch_id} | {self.h3_res8_index} | {self.status})"
