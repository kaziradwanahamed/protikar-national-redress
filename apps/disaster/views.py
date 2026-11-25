from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsGROOrOversight
from apps.disaster.models import CrisisZone, EmergencyCommandDispatch
from apps.disaster.serializers import (
    CrisisToggleSerializer,
    EmergencyCommandDispatchSerializer,
    SurgeIngestSerializer,
)
from apps.disaster.services.circuit_breaker import DisasterCircuitBreakerService
from apps.disaster.services.h3_surge_pipeline import H3SurgeIngestionService
from apps.organogram.models import ServiceAreaPolygon


class CrisisZoneToggleView(APIView):
    """MoDMR / DC manual emergency toggle activating/deactivating Crisis Mode & P3/P4 SLA freeze."""

    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request):
        serializer = CrisisToggleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if data["action"] == "DEACTIVATE":
            zone = get_object_or_404(CrisisZone, crisis_code=data["crisis_code"])
            resumed = DisasterCircuitBreakerService.deactivate_crisis_zone(
                crisis_zone=zone, actor_seat_id=request.user.doptor_seat_id or "MODMR-CMD"
            )
            return Response(
                {"status": "deactivated", "crisis_code": zone.crisis_code, "resumed_tickets": resumed}
            )

        area = get_object_or_404(ServiceAreaPolygon, zone_code=data["zone_code"])
        zone = DisasterCircuitBreakerService.activate_crisis_zone(
            crisis_code=data["crisis_code"],
            name_en=data["name_en"],
            name_bn=data["name_bn"],
            disaster_type=data["disaster_type"],
            trigger_source=data["trigger_source"],
            geom=area.geom,
            affected_area_polygon=area,
            activated_by_seat=request.user.doptor_seat_id or "MODMR-CMD",
        )
        return Response(
            {
                "status": "activated",
                "crisis_id": str(zone.crisis_id),
                "crisis_code": zone.crisis_code,
                "frozen_ticket_count": zone.frozen_ticket_count,
            },
            status=status.HTTP_201_CREATED,
        )


class SurgeIngestView(APIView):
    """High-throughput async Kafka + H3 Res-8 Redis counter + P1 Fast-Lane ingest endpoint."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SurgeIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        crisis_zone = (
            CrisisZone.objects.filter(crisis_id=data["crisis_id"]).first()
            if data.get("crisis_id")
            else None
        )
        result = H3SurgeIngestionService.ingest_surge_report(
            lat=data["lat"],
            lon=data["lon"],
            message=data["message"],
            citizen_phone=data["citizen_phone"],
            crisis_zone=crisis_zone,
        )
        return Response(
            {
                "h3_res8_index": result.h3_res8_index,
                "hex_counter_value": result.hex_counter_value,
                "kafka_topic": result.kafka_topic,
                "fastlane_triggered": result.fastlane_triggered,
                "matched_rescue_keywords": result.matched_rescue_keywords,
                "dispatch_id": result.dispatch_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CrisisHeatmapView(APIView):
    """Serves live Redis O(1) H3 Resolution-8 macro-incident heatmap without locking PostgreSQL."""

    permission_classes = [AllowAny]

    def get(self, request, crisis_id):
        cells = H3SurgeIngestionService.get_live_h3_heatmap(crisis_id=str(crisis_id))
        return Response({"crisis_id": str(crisis_id), "h3_resolution": 8, "cells": cells})


class EmergencyFastLaneListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]
    queryset = EmergencyCommandDispatch.objects.all()
    serializer_class = EmergencyCommandDispatchSerializer
    filterset_fields = ("status", "h3_res8_index")
