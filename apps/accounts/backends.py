"""Custom Django authentication backends for myGov/Porichoy OIDC and Doptor Official SSO."""

from __future__ import annotations

from django.contrib.auth.backends import BaseBackend

from apps.accounts.models import User
from apps.accounts.services.oidc_providers import (
    CitizenIdentityService,
    IdentityVerificationError,
    get_identity_provider,
)


class MyGovOIDCBackend(BaseBackend):
    """Authenticates citizens via myGov OAuth 2.0 / OIDC authorization code."""

    def authenticate(self, request, mygov_code: str | None = None, **kwargs):
        if not mygov_code:
            return None
        provider = get_identity_provider()
        try:
            claims = provider.exchange_code_for_claims(mygov_code)
        except IdentityVerificationError:
            return None
        user, _profile = CitizenIdentityService.upsert_from_oidc_claims(claims)
        return user if user.is_active else None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class DoptorSSOBackend(BaseBackend):
    """Authenticates government officials via Doptor SSO token and syncs organogram seat."""

    def authenticate(self, request, doptor_token: str | None = None, **kwargs):
        if not doptor_token:
            return None
        from apps.organogram.services.doptor_sso import DoptorSSOError, DoptorSSOService

        try:
            result = DoptorSSOService().authenticate_and_sync(doptor_token)
        except DoptorSSOError:
            return None
        return result.user if result.user.is_active else None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
