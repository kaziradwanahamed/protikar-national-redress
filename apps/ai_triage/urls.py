from django.urls import path

from apps.ai_triage.views import (
    MasterIncidentSubscribersView,
    ReleaseDependentSubTicketsView,
    SubTicketDependencyListView,
    TaxonomySummaryView,
    TriageRunListView,
    TriggerComplaintTriageView,
)

app_name = "ai_triage"

urlpatterns = [
    path("taxonomy/", TaxonomySummaryView.as_view(), name="taxonomy"),
    path("runs/", TriageRunListView.as_view(), name="triage-run-list"),
    path("<uuid:complaint_id>/run/", TriggerComplaintTriageView.as_view(), name="run-triage"),
    path(
        "<uuid:complaint_id>/dependencies/",
        SubTicketDependencyListView.as_view(),
        name="subticket-dependencies",
    ),
    path(
        "<uuid:complaint_id>/release-dependents/",
        ReleaseDependentSubTicketsView.as_view(),
        name="release-dependents",
    ),
    path(
        "<uuid:complaint_id>/subscribers/",
        MasterIncidentSubscribersView.as_view(),
        name="master-subscribers",
    ),
]
