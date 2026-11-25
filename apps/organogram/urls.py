from django.urls import path

from apps.organogram.views import (
    DoptorOfficeListView,
    DoptorSeatListView,
    DoptorSSOLoginView,
    DoptorVacancyAlertListView,
    DynamicSeatRouteView,
)

app_name = "organogram"

urlpatterns = [
    path("sso/doptor/login/", DoptorSSOLoginView.as_view(), name="doptor-sso-login"),
    path("offices/", DoptorOfficeListView.as_view(), name="office-list"),
    path("seats/", DoptorSeatListView.as_view(), name="seat-list"),
    path("route-seat/", DynamicSeatRouteView.as_view(), name="route-seat"),
    path("vacancy-alerts/", DoptorVacancyAlertListView.as_view(), name="vacancy-alert-list"),
]
