from django.urls import path

from apps.accounts.views import (
    CitizenProfileView,
    DemoRoleSwitchView,
    MobileOTPRequestView,
    MobileOTPVerifyIdentityView,
    MyGovAuthorizeView,
    MyGovCallbackView,
    RecordFalseFilingStrikeView,
    WhistleblowerSealView,
    WhistleblowerUnsealView,
)

app_name = "accounts"

urlpatterns = [
    path("sso/mygov/authorize/", MyGovAuthorizeView.as_view(), name="mygov-authorize"),
    path("sso/mygov/callback/", MyGovCallbackView.as_view(), name="mygov-callback"),
    path("otp/request/", MobileOTPRequestView.as_view(), name="otp-request"),
    path("otp/verify/", MobileOTPVerifyIdentityView.as_view(), name="otp-verify"),
    path("profile/", CitizenProfileView.as_view(), name="citizen-profile"),
    path("demo-switch/", DemoRoleSwitchView.as_view(), name="demo-role-switch"),
    path("strikes/", RecordFalseFilingStrikeView.as_view(), name="record-strike"),
    path("whistleblower/seal/", WhistleblowerSealView.as_view(), name="whistleblower-seal"),
    path(
        "whistleblower/<uuid:complaint_id>/unseal/",
        WhistleblowerUnsealView.as_view(),
        name="whistleblower-unseal",
    ),
]
