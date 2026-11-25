from django.urls import path

from apps.workflow.views import (
    AdvanceCapitalMilestoneView,
    AssignFieldWorkerView,
    CitizenVerdictView,
    DDCCAgendaListView,
    OfficerContestView,
    ProcurementHoldView,
    PublicCapitalMilestoneListView,
    RouteComplaintView,
    SubmitResolutionView,
    TransferComplaintView,
    UnfoundedClearView,
)

app_name = "workflow"

urlpatterns = [
    path("<uuid:complaint_id>/route/", RouteComplaintView.as_view(), name="route"),
    path("<uuid:complaint_id>/assign-field-worker/", AssignFieldWorkerView.as_view(), name="assign-field-worker"),
    path("<uuid:complaint_id>/submit-resolution/", SubmitResolutionView.as_view(), name="submit-resolution"),
    path("<uuid:complaint_id>/citizen-verdict/", CitizenVerdictView.as_view(), name="citizen-verdict"),
    path("<uuid:complaint_id>/transfer/", TransferComplaintView.as_view(), name="transfer"),
    path("<uuid:complaint_id>/hold-procurement/", ProcurementHoldView.as_view(), name="hold-procurement"),
    path("<uuid:complaint_id>/milestones/", PublicCapitalMilestoneListView.as_view(), name="milestones"),
    path("<uuid:complaint_id>/milestones/advance/", AdvanceCapitalMilestoneView.as_view(), name="advance-milestone"),
    path("<uuid:complaint_id>/contest/", OfficerContestView.as_view(), name="contest"),
    path("<uuid:complaint_id>/unfounded-clear/", UnfoundedClearView.as_view(), name="unfounded-clear"),
    path("ddcc-agenda/", DDCCAgendaListView.as_view(), name="ddcc-agenda"),
]
