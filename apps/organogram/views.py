from django.contrib.auth import login
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsDoptorOfficer, IsGROOrOversight
from apps.complaints.models import Complaint
from apps.organogram.models import DoptorOffice, DoptorSeat, DoptorVacancyAlert
from apps.organogram.serializers import (
    DoptorOfficeSerializer,
    DoptorSeatSerializer,
    DoptorSSOLoginSerializer,
    DoptorVacancyAlertSerializer,
    SeatRouteRequestSerializer,
)
from apps.organogram.services.doptor_sso import DoptorSSOError, DoptorSSOService
from apps.organogram.services.seat_router import SeatRoutingError, ZeroBlackHoleSeatRouter


class DoptorSSOLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = DoptorSSOLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = DoptorSSOService().authenticate_and_sync(
                serializer.validated_data["doptor_token"]
            )
        except DoptorSSOError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        login(request, result.user, backend="apps.accounts.backends.DoptorSSOBackend")
        return Response(
            {
                "status": "authenticated",
                "officer_id": result.user.doptor_officer_id,
                "doptor_seat_id": result.seat.doptor_seat_id,
                "role_level": result.seat.role_level,
                "office": DoptorOfficeSerializer(result.office).data,
                "synced_hierarchy": result.synced_hierarchy_codes,
            }
        )


class DoptorOfficeListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsDoptorOfficer]
    queryset = DoptorOffice.objects.filter(is_active=True)
    serializer_class = DoptorOfficeSerializer
    filterset_fields = ("office_layer", "ministry_code", "bbs_geo_code")
    search_fields = ("office_code", "name_en", "name_bn", "doptor_office_id")


class DoptorSeatListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsDoptorOfficer]
    queryset = DoptorSeat.objects.select_related(
        "office", "additional_charge_seat", "parent_seat"
    ).filter(is_active=True)
    serializer_class = DoptorSeatSerializer
    filterset_fields = ("role_level", "is_vacant", "office__office_code")
    search_fields = ("doptor_seat_id", "designation_en", "incumbent_name_en")


class DynamicSeatRouteView(APIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request):
        serializer = SeatRouteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        router = ZeroBlackHoleSeatRouter()

        try:
            if data.get("complaint_id"):
                complaint = get_object_or_404(Complaint, complaint_id=data["complaint_id"])
                assignment, resolution = router.assign_complaint_to_seat(
                    complaint=complaint,
                    target_seat_id=data["target_seat_id"],
                    due_at=data.get("due_at"),
                )
                return Response(
                    {
                        "assignment_id": str(assignment.assignment_id),
                        "requested_seat_id": resolution.requested_seat.doptor_seat_id,
                        "resolved_seat_id": resolution.resolved_seat.doptor_seat_id,
                        "resolved_officer_id": resolution.resolved_seat.incumbent_officer_id,
                        "fallback_tier": resolution.fallback_tier,
                        "vacancy_alert_id": (
                            str(resolution.vacancy_alert.alert_id)
                            if resolution.vacancy_alert
                            else None
                        ),
                    },
                    status=status.HTTP_201_CREATED,
                )

            resolution = router.resolve_seat(target_seat_id=data["target_seat_id"])
            return Response(
                {
                    "requested_seat_id": resolution.requested_seat.doptor_seat_id,
                    "resolved_seat_id": resolution.resolved_seat.doptor_seat_id,
                    "resolved_officer_id": resolution.resolved_seat.incumbent_officer_id,
                    "fallback_tier": resolution.fallback_tier,
                    "vacancy_alert_id": (
                        str(resolution.vacancy_alert.alert_id)
                        if resolution.vacancy_alert
                        else None
                    ),
                }
            )
        except SeatRoutingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)


class DoptorVacancyAlertListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]
    queryset = DoptorVacancyAlert.objects.select_related("vacant_seat", "routed_to_seat").all()
    serializer_class = DoptorVacancyAlertSerializer
    filterset_fields = ("fallback_tier", "hr_dispatch_status")
