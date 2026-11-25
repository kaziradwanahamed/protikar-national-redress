from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsDoptorOfficer, IsGROOrOversight
from apps.ai_triage.models import (
    MasterIncidentSubscription,
    SubTicketDependency,
    TriageRun,
)
from apps.ai_triage.serializers import (
    MasterIncidentSubscriptionSerializer,
    SubTicketDependencySerializer,
    TriageRunSerializer,
    TriggerTriageSerializer,
)
from apps.ai_triage.services.classifier import AGENCY_ROUTING_RULES, TAXONOMY_METADATA
from apps.ai_triage.services.pipeline import AITriageOrchestrator
from apps.ai_triage.services.splitter import CompoundComplaintSplitter
from apps.ai_triage.tasks import run_complaint_triage
from apps.complaints.models import Complaint


class TriggerComplaintTriageView(APIView):
    """Triggers synchronous or async Celery AI triage for a submitted complaint."""

    permission_classes = [IsAuthenticated]

    def post(self, request, complaint_id):
        complaint = get_object_or_404(Complaint, complaint_id=complaint_id)
        serializer = TriggerTriageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo_urls = serializer.validated_data["photo_urls"]

        if serializer.validated_data["run_async"]:
            task = run_complaint_triage.delay(str(complaint.complaint_id), photo_urls=photo_urls)
            return Response(
                {"status": "queued", "task_id": task.id, "complaint_id": str(complaint.complaint_id)},
                status=status.HTTP_202_ACCEPTED,
            )

        run = AITriageOrchestrator.process_complaint(
            complaint=complaint, photo_urls=photo_urls
        )
        return Response(TriageRunSerializer(run).data, status=status.HTTP_201_CREATED)


class TriageRunListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsDoptorOfficer]
    serializer_class = TriageRunSerializer
    filterset_fields = ("routing_decision", "gro_one_click_reassign_flag", "primary_agency_code")

    def get_queryset(self):
        return TriageRun.objects.select_related("complaint").all()


class SubTicketDependencyListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsDoptorOfficer]
    serializer_class = SubTicketDependencySerializer

    def get_queryset(self):
        return SubTicketDependency.objects.select_related(
            "prerequisite_ticket", "dependent_ticket"
        ).filter(parent_case_id=self.kwargs["complaint_id"])


class ReleaseDependentSubTicketsView(APIView):
    """Marks a prerequisite sub-ticket satisfied and routes newly unblocked child tickets."""

    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request, complaint_id):
        completed = get_object_or_404(Complaint, complaint_id=complaint_id)
        released = CompoundComplaintSplitter.release_dependent_subtickets(completed)
        return Response(
            {
                "completed_tracking_code": completed.tracking_code,
                "released_tracking_codes": [c.tracking_code for c in released],
            }
        )


class MasterIncidentSubscribersView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, IsDoptorOfficer]
    serializer_class = MasterIncidentSubscriptionSerializer

    def get_queryset(self):
        return MasterIncidentSubscription.objects.filter(
            master_complaint_id=self.kwargs["complaint_id"]
        )


class TaxonomySummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "taxonomy": TAXONOMY_METADATA,
                "active_routing_rules": [
                    {
                        "ministry_code": r["ministry_code"],
                        "agency_code": r["agency_code"],
                        "category_code": r["category_code"],
                        "zone_type": r["zone_type"],
                        "engineering_phase": r["engineering_phase"],
                    }
                    for r in AGENCY_ROUTING_RULES
                ],
            }
        )
