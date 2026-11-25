import secrets

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CitizenProfile, WhistleblowerVaultRecord
from apps.accounts.permissions import IsGROOrOversight, IsOversightCellMember, IsVerifiedCitizen
from apps.accounts.serializers import (
    CitizenProfileSerializer,
    MyGovCallbackSerializer,
    OTPRequestSerializer,
    OTPVerifyIdentitySerializer,
    RecordFalseFilingStrikeSerializer,
    WhistleblowerSealSerializer,
    WhistleblowerUnsealSerializer,
)
from apps.accounts.services.oidc_providers import (
    CitizenIdentityService,
    IdentityVerificationError,
    MobileOTPService,
    get_identity_provider,
)
from apps.accounts.services.vault_envelope import (
    VaultAuthorizationError,
    VaultEnvelopeError,
    WhistleblowerPrivacyService,
)


class MyGovAuthorizeView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        request.session["mygov_oidc_state"] = state
        provider = get_identity_provider()
        return Response(
            {
                "authorization_url": provider.build_authorization_url(state=state, nonce=nonce),
                "state": state,
                "provider_mode": getattr(settings, "IDENTITY_PROVIDER_MODE", "mock"),
            }
        )


class MyGovCallbackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = MyGovCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, mygov_code=serializer.validated_data["code"])
        if user is None:
            return Response(
                {"detail": "myGov OIDC authentication failed."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user, backend="apps.accounts.backends.MyGovOIDCBackend")
        profile_data = CitizenProfileSerializer(user.citizen_profile).data
        return Response({"status": "authenticated", "profile": profile_data})


class MobileOTPRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        challenge, otp_code = MobileOTPService.issue_challenge(
            phone_number=serializer.validated_data["phone_number"],
            purpose=serializer.validated_data["purpose"],
        )
        response_data = {
            "challenge_id": str(challenge.challenge_id),
            "expires_at": challenge.expires_at,
        }
        if getattr(settings, "IDENTITY_PROVIDER_MODE", "mock") == "mock":
            response_data["dev_otp_code"] = otp_code
        return Response(response_data, status=status.HTTP_201_CREATED)


class MobileOTPVerifyIdentityView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OTPVerifyIdentitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user, profile = CitizenIdentityService.verify_otp_and_identity(
                **serializer.validated_data
            )
        except IdentityVerificationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(
            {"status": "verified", "profile": CitizenProfileSerializer(profile).data},
            status=status.HTTP_200_OK,
        )


class CitizenProfileView(APIView):
    permission_classes = [IsAuthenticated, IsVerifiedCitizen]

    def get(self, request):
        return Response(CitizenProfileSerializer(request.user.citizen_profile).data)

    def patch(self, request):
        serializer = CitizenProfileSerializer(
            request.user.citizen_profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RecordFalseFilingStrikeView(APIView):
    """GRO / Appellate / Oversight endpoint to record a verified false-filing strike."""

    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request):
        serializer = RecordFalseFilingStrikeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = get_object_or_404(
            CitizenProfile,
            pseudonymous_public_hash=serializer.validated_data["pseudonymous_public_hash"],
        )
        profile.record_verified_false_filing(
            reason=serializer.validated_data["reason"],
            penalty=serializer.validated_data["penalty"],
        )
        return Response(
            {
                "pseudonymous_public_hash": profile.pseudonymous_public_hash,
                "strike_count": profile.strike_count,
                "credibility_score": profile.credibility_score,
                "requires_manual_premoderation": profile.requires_manual_premoderation,
                "priority_routing_eligible": profile.priority_routing_eligible,
            }
        )


class WhistleblowerSealView(APIView):
    """Seals verified citizen identity into HashiCorp Vault envelope storage for anonymous cases."""

    permission_classes = [IsAuthenticated, IsVerifiedCitizen]

    def post(self, request):
        serializer = WhistleblowerSealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = WhistleblowerPrivacyService().seal_identity(
            complaint_id=serializer.validated_data["complaint_id"],
            citizen_profile=request.user.citizen_profile,
        )
        return Response(
            {
                "record_id": str(record.record_id),
                "complaint_id": str(record.complaint_id),
                "pseudonymous_public_hash": record.pseudonymous_public_hash,
                "vault_key_name": record.vault_key_name,
            },
            status=status.HTTP_201_CREATED,
        )


class WhistleblowerUnsealView(APIView):
    """Oversight Cell ONLY endpoint to decrypt a whistleblower identity with mandatory audit log."""

    permission_classes = [IsAuthenticated, IsOversightCellMember]

    def post(self, request, complaint_id):
        serializer = WhistleblowerUnsealSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            identity = WhistleblowerPrivacyService().unseal_identity(
                complaint_id=complaint_id,
                oversight_user=request.user,
                justification=serializer.validated_data["justification"],
            )
        except WhistleblowerVaultRecord.DoesNotExist:
            return Response({"detail": "Vault record not found."}, status=status.HTTP_404_NOT_FOUND)
        except (VaultAuthorizationError, VaultEnvelopeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response({"complaint_id": str(complaint_id), "unsealed_identity": identity})


class DemoRoleSwitchView(APIView):
    """
    1-Click Demo Role Switcher endpoint active ONLY when DEBUG=True or DEMO_MODE=True.
    Logs the session into the requested demo account and redirects to that role's workspace.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        if not (getattr(settings, "DEBUG", False) or getattr(settings, "DEMO_MODE", False)):
            return Response(
                {"detail": "Demo Role Switcher is disabled in hardened production mode."},
                status=status.HTTP_403_FORBIDDEN,
            )

        from django.contrib.auth import get_user_model
        from django.shortcuts import redirect
        from apps.accounts.demo_roles import DEMO_ROLE_REDIRECTS

        username = (request.data.get("username") or request.POST.get("username") or "").strip()
        if username not in DEMO_ROLE_REDIRECTS:
            return Response(
                {"detail": f"Unknown demo role '{username}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_model = get_user_model()
        user = user_model.objects.filter(username=username, is_active=True).first()
        if user is None:
            return Response(
                {"detail": "Demo account not seeded yet. Run: python manage.py seed_demo_scenarios"},
                status=status.HTTP_404_NOT_FOUND,
            )

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        target_url = DEMO_ROLE_REDIRECTS[username]
        if request.accepted_renderer.format == "json" and not request.POST:
            return Response(
                {"status": "switched", "username": user.username, "redirect_url": target_url}
            )
        return redirect(target_url)
