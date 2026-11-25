from django.urls import path

from apps.disaster.views import (
    CrisisHeatmapView,
    CrisisZoneToggleView,
    EmergencyFastLaneListView,
    SurgeIngestView,
)

app_name = "disaster"

urlpatterns = [
    path("crisis-zones/toggle/", CrisisZoneToggleView.as_view(), name="crisis-toggle"),
    path("crisis-zones/<uuid:crisis_id>/heatmap/", CrisisHeatmapView.as_view(), name="crisis-heatmap"),
    path("surge/ingest/", SurgeIngestView.as_view(), name="surge-ingest"),
    path("fastlane/", EmergencyFastLaneListView.as_view(), name="fastlane-list"),
]
