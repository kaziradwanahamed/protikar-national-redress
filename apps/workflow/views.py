from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    HasDoptorSeatRole,
    IsDoptorOfficer,
    IsGROOrOversight,
    IsVerifiedCitizen,
)
from apps.complaints.models import Complaint
from apps.organogram.models import RoleLevel
from apps.workflow.models import CapitalMilestone, DDCCAgendaItem
from apps.workflow.serializers import (
    AdvanceMilestoneSerializer,
    AssignFieldWorkerSerializer,
    CapitalMilestoneSerializer,
    CitizenVerdictSerializer,
    DDCCAgendaItemSerializer,
    OfficerContestSerializer,
    ProcurementHoldSerializer,
    RouteComplaintSerializer,
    SubmitResolutionSerializer,
    TransferRequestSerializer,
    UnfoundedClearSerializer,
    WorkflowTrackerSerializer,
)
from apps.workflow.services.sla_service import TieredSLAService
from apps.workflow.services.state_machine import (
    GrievanceWorkflowEngine,
    WorkflowPermissionError,
    WorkflowTransitionError,
)


class RouteComplaintView(APIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = RouteComplaintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tracker, assignment = TieredSLAService.route_complaint(
            complaint=complaint,
            target_seat_id=serializer.validated_data["target_seat_id"],
            actor_id=str(request.user.id),
            p3_days=serializer.validated_data["p3_days"],
        )
        return Response(
            {
                "status": complaint.status,
                "assignment_id": str(assignment.assignment_id),
                "doptor_seat_id": assignment.doptor_seat_id,
                "tracker": WorkflowTrackerSerializer(tracker).data,
            },
            status=status.HTTP_200_OK,
        )


class AssignFieldWorkerView(APIView):
    permission_classes = [IsAuthenticated, IsDoptorOfficer, HasDoptorSeatRole]
    allowed_role_levels = (RoleLevel.SUPERVISOR, RoleLevel.GRO, RoleLevel.APPELLATE)

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = AssignFieldWorkerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = TieredSLAService.assign_field_worker(
            complaint=complaint,
            supervisor_seat_id=request.user.doptor_seat_id,
            field_worker_seat_id=serializer.validated_data["field_worker_seat_id"],
            actor_id=str(request.user.id),
        )
        return Response(
            {
                "status": complaint.status,
                "assignment_id": str(assignment.assignment_id),
                "field_worker_seat_id": assignment.doptor_seat_id,
                "sub_deadline_at": assignment.due_at,
            },
            status=status.HTTP_201_CREATED,
        )


class SubmitResolutionView(APIView):
    """Two-Key Verification Gate: validates 100m PostGIS distance + supervisor sign-off."""

    permission_classes = [IsAuthenticated, IsDoptorOfficer]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = SubmitResolutionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            report = GrievanceWorkflowEngine.submit_resolution_for_verification(
                complaint=complaint,
                actor_id=str(request.user.id),
                **serializer.validated_data,
            )
        except WorkflowPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except WorkflowTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": complaint.status,
                "report_id": str(report.report_id),
                "gps_verified_dist_m": report.gps_verified_dist_m,
                "citizen_verify_deadline_at": complaint.workflow_tracker.citizen_verify_deadline_at,
            },
            status=status.HTTP_201_CREATED,
        )


class CitizenVerdictView(APIView):
    """Citizen 72-hour verification endpoint (ACCEPT -> CLOSED; REJECT -> reopen & escalate)."""

    permission_classes = [IsAuthenticated, IsVerifiedCitizen]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = CitizenVerdictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            report = GrievanceWorkflowEngine.record_citizen_verdict(
                complaint=complaint,
                citizen_actor_id=str(request.user.id),
                **serializer.validated_data,
            )
        except WorkflowTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": complaint.status,
                "citizen_verdict": report.citizen_verdict,
                "escalation_level": complaint.escalation_level,
            }
        )


class TransferComplaintView(APIView):
    """Anti-Gaming Transfer endpoint (max 2 transfers, first 15% SLA, P1 accept-first)."""

    permission_classes = [IsAuthenticated, IsDoptorOfficer]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = TransferRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outcome = GrievanceWorkflowEngine.request_transfer(
                complaint=complaint,
                from_seat_id=request.user.doptor_seat_id,
                target_seat_id=serializer.validated_data["target_seat_id"],
                reason=serializer.validated_data["reason"],
                actor_id=str(request.user.id),
            )
        except WorkflowTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(outcome)


class ProcurementHoldView(APIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = ProcurementHoldSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            milestones = GrievanceWorkflowEngine.place_on_hold_procurement(
                complaint=complaint,
                seat_id=request.user.doptor_seat_id or "GRO-SEAT",
                actor_id=str(request.user.id),
                **serializer.validated_data,
            )
        except WorkflowTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "status": complaint.status,
                "milestones": CapitalMilestoneSerializer(milestones, many=True).data,
            }
        )


class PublicCapitalMilestoneListView(generics.ListAPIView):
    """Public Capital Milestone Tracker for ON_HOLD_PROCUREMENT tickets."""

    permission_classes = [AllowAny]
    serializer_class = CapitalMilestoneSerializer

    def get_queryset(self):
        return CapitalMilestone.objects.filter(complaint_id=self.kwargs["complaint_id"])


class AdvanceCapitalMilestoneView(APIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = AdvanceMilestoneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        milestone = GrievanceWorkflowEngine.advance_capital_milestone(
            complaint=complaint,
            seat_id=request.user.doptor_seat_id or "GRO-SEAT",
            actor_id=str(request.user.id),
            **serializer.validated_data,
        )
        return Response(CapitalMilestoneSerializer(milestone).data)


class OfficerContestView(APIView):
    """48-hour Right of Reply before KPI/APA penalties apply."""

    permission_classes = [IsAuthenticated, IsDoptorOfficer]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = OfficerContestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tracker = GrievanceWorkflowEngine.contest_by_officer(
                complaint=complaint,
                seat_id=request.user.doptor_seat_id,
                actor_id=str(request.user.id),
                **serializer.validated_data,
            )
        except WorkflowTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "status": complaint.status,
                "officer_rebuttal_deadline_at": tracker.officer_rebuttal_deadline_at,
            }
        )


class UnfoundedClearView(APIView):
    """Marks a grievance UNFOUNDED_CLEARED: zero officer penalty + citizen strike."""

    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = UnfoundedClearSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            outcome = GrievanceWorkflowEngine.mark_unfounded_cleared(
                complaint=complaint,
                adjudicator_user=request.user,
                **serializer.validated_data,
            )
        except WorkflowTransitionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(outcome)


class DDCCAgendaListView(generics.ListAPIView):
    """Monthly DDCC agenda items auto-surfaced for Tier-3+ SLA breaches."""

    permission_classes = [IsAuthenticated, IsGROOrOversight]
    queryset = DDCCAgendaItem.objects.select_related("complaint", "escalation_event").all()
    serializer_class = DDCCAgendaItemSerializer
    filterset_fields = ("district_bbs_code", "agenda_month", "status")
