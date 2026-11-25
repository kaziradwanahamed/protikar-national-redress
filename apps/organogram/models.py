import uuid
from django.contrib.gis.db import models as gis_models
from django.db import models


class RoleLevel(models.TextChoices):
    APPELLATE = "APPELLATE", "Appellate Officer"
    GRO = "GRO", "Grievance Redress Officer (GRO)"
    SUPERVISOR = "SUPERVISOR", "Field Supervisor"
    FIELD_WORKER = "FIELD_WORKER", "Field Worker"


class DoptorOffice(models.Model):
    """
    Government of Bangladesh Doptor (নথি/দপ্তর) office directory record supporting
    full Ministry -> Directorate -> Division -> District -> Upazila -> Office hierarchy.
    """

    class OfficeLayer(models.TextChoices):
        MINISTRY = "MINISTRY", "Ministry / Division"
        DIRECTORATE = "DIRECTORATE", "Directorate / Department"
        CITY_CORP = "CITY_CORP", "City Corporation"
        UTILITY = "UTILITY", "Utility Authority (WASA / DESCO / DPDC / TITAS)"
        ENGINEERING = "ENGINEERING", "Road & Engineering Agency (RHD / LGED)"
        DIVISION = "DIVISION", "Divisional Administration"
        DISTRICT = "DISTRICT", "District Administration (DC Office)"
        UPAZILA = "UPAZILA", "Upazila Administration (UNO Office)"

    office_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doptor_office_id = models.CharField(
        max_length=64, unique=True, db_index=True, help_text="Canonical Doptor Office ID."
    )
    office_code = models.CharField(max_length=64, unique=True, db_index=True)
    name_en = models.CharField(max_length=255)
    name_bn = models.CharField(max_length=255, blank=True)
    office_layer = models.CharField(max_length=24, choices=OfficeLayer.choices, db_index=True)
    ministry_code = models.CharField(max_length=64, blank=True, db_index=True)
    directorate_code = models.CharField(max_length=64, blank=True, db_index=True)
    division_code = models.CharField(max_length=16, blank=True, db_index=True)
    district_code = models.CharField(max_length=16, blank=True, db_index=True)
    upazila_code = models.CharField(max_length=16, blank=True, db_index=True)
    parent_office = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="child_offices",
    )
    bbs_geo_code = models.CharField(
        max_length=16, blank=True, db_index=True, help_text="BBS administrative geocode."
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organogram_doptor_office"
        ordering = ["office_layer", "name_en"]
        indexes = [
            models.Index(fields=["office_layer", "is_active"], name="idx_office_layer_active"),
            models.Index(fields=["bbs_geo_code", "office_layer"], name="idx_office_bbs_layer"),
        ]

    def __str__(self) -> str:
        return f"{self.name_en} ({self.doptor_office_id})"


class DoptorSeat(models.Model):
    """
    Official organogram seat (পদবি) decoupled from individual officer transfers.
    Tickets bind to `doptor_seat_id` so transfers never create orphaned black holes.
    """

    seat_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    doptor_seat_id = models.CharField(
        max_length=64, unique=True, db_index=True, help_text="Canonical Doptor Seat/Organogram ID."
    )
    office = models.ForeignKey(
        DoptorOffice, on_delete=models.CASCADE, related_name="seats"
    )
    designation_en = models.CharField(max_length=255)
    designation_bn = models.CharField(max_length=255, blank=True)
    role_level = models.CharField(max_length=16, choices=RoleLevel.choices, db_index=True)
    parent_seat = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subordinate_seats",
        help_text="Immediate supervisor seat (immediate_supervisor_seat_id) in Doptor hierarchy.",
    )
    additional_charge_seat = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="additional_charge_for_seats",
        help_text="Designated additional-charge seat when primary seat is vacant.",
    )
    doptor_hr_email = models.EmailField(
        blank=True,
        help_text="Doptor HR focal email for automated vacant-seat alerts.",
    )
    incumbent_officer_id = models.CharField(max_length=64, blank=True, db_index=True)
    incumbent_name_en = models.CharField(max_length=255, blank=True)
    incumbent_name_bn = models.CharField(max_length=255, blank=True)
    is_vacant = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organogram_doptor_seat"
        ordering = ["office", "role_level", "designation_en"]
        indexes = [
            models.Index(fields=["office", "role_level", "is_active"], name="idx_seat_office_role"),
        ]

    @property
    def is_occupied(self) -> bool:
        return bool(self.is_active and not self.is_vacant and self.incumbent_officer_id)

    @property
    def additional_charge_seat_id(self) -> str | None:
        return self.additional_charge_seat.doptor_seat_id if self.additional_charge_seat else None

    @property
    def immediate_supervisor_seat_id(self) -> str | None:
        return self.parent_seat.doptor_seat_id if self.parent_seat else None

    def __str__(self) -> str:
        return f"{self.designation_en} — {self.office.office_code} [{self.role_level}]"


class DoptorVacancyAlert(models.Model):
    """Tracks automated Doptor HR vacancy alerts triggered by Zero-Black-Hole Seat Routing."""

    class FallbackTier(models.TextChoices):
        ADDITIONAL_CHARGE = "ADDITIONAL_CHARGE", "Routed to Additional Charge Seat"
        IMMEDIATE_SUPERVISOR = "IMMEDIATE_SUPERVISOR", "Auto-Routed to Immediate Supervisor"
        UNRESOLVED = "UNRESOLVED", "No Occupied Seat Found in Chain"

    class DispatchStatus(models.TextChoices):
        PENDING = "PENDING", "Pending HR Dispatch"
        SENT = "SENT", "Dispatched to Doptor HR"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged by Doptor HR"

    alert_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vacant_seat = models.ForeignKey(
        DoptorSeat, on_delete=models.CASCADE, related_name="vacancy_alerts"
    )
    routed_to_seat = models.ForeignKey(
        DoptorSeat,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="received_fallback_alerts",
    )
    complaint_id = models.UUIDField(null=True, blank=True, db_index=True)
    fallback_tier = models.CharField(
        max_length=24, choices=FallbackTier.choices, db_index=True
    )
    hr_dispatch_status = models.CharField(
        max_length=16, choices=DispatchStatus.choices, default=DispatchStatus.PENDING, db_index=True
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "organogram_doptor_vacancy_alert"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"VacancyAlert({self.vacant_seat.doptor_seat_id} -> {self.fallback_tier})"


class ServiceAreaPolygon(gis_models.Model):
    """
    PostGIS MultiPolygon registry storing BBS administrative boundaries and
    overlapping utility/infrastructure service jurisdictions across Bangladesh.
    """

    class ZoneType(models.TextChoices):
        BBS_DIVISION = "BBS_DIVISION", "BBS Division"
        BBS_DISTRICT = "BBS_DISTRICT", "BBS District (Zila)"
        BBS_UPAZILA = "BBS_UPAZILA", "BBS Upazila / Thana"
        BBS_UNION = "BBS_UNION", "BBS Union / Pourashava"
        CITY_CORP_WARD = "CITY_CORP_WARD", "City Corporation Ward (DNCC/DSCC/CCC)"
        WASA_MODS_ZONE = "WASA_MODS_ZONE", "WASA MODS Zone"
        DESCO_FEEDER = "DESCO_FEEDER", "DESCO Feeder / S&D Zone"
        DPDC_FEEDER = "DPDC_FEEDER", "DPDC Feeder / NOCS Zone"
        RHD_ROAD = "RHD_ROAD", "RHD National/Regional Highway Corridor"
        LGED_ROAD = "LGED_ROAD", "LGED Upazila/Union Road Corridor"
        DISASTER_ZONE = "DISASTER_ZONE", "Disaster / Crisis Freeze Zone"

    area_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    zone_code = models.CharField(max_length=64, unique=True, db_index=True)
    zone_type = models.CharField(max_length=24, choices=ZoneType.choices, db_index=True)
    bbs_geo_code = models.CharField(
        max_length=16, blank=True, db_index=True, help_text="BBS 2/4/6/8-digit administrative geocode."
    )
    name_en = models.CharField(max_length=255)
    name_bn = models.CharField(max_length=255, blank=True)
    parent_area = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="child_areas",
    )
    primary_office = models.ForeignKey(
        DoptorOffice,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_areas",
    )
    default_gro_seat = models.ForeignKey(
        DoptorSeat,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="routed_service_areas",
        help_text="Default GRO seat for automated point-in-polygon ticket routing.",
    )
    geom = gis_models.MultiPolygonField(
        srid=4326,
        spatial_index=True,
        help_text="WGS84 (EPSG:4326) MultiPolygon boundary of the service or administrative zone.",
    )
    metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organogram_service_area_polygon"
        ordering = ["zone_type", "zone_code"]
        indexes = [
            models.Index(fields=["zone_type", "is_active"], name="idx_sap_type_active"),
            models.Index(fields=["bbs_geo_code", "zone_type"], name="idx_sap_bbs_type"),
        ]

    def __str__(self) -> str:
        return f"[{self.zone_type}] {self.name_en} ({self.zone_code})"
