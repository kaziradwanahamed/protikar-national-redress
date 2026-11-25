from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsDoptorOfficer, IsGROOrOversight
from apps.complaints.models import Complaint
from apps.esb.models import OmnichannelIntakeRecord
from apps.esb.serializers import (
    Compact2GIntakeSerializer,
    SocialBotWebhookSerializer,
    Tier1OutboundDispatchSerializer,
    Tier3RuralUpdateSerializer,
)
from apps.esb.services.omnichannel import CompactSMSParseError, OmnichannelIntakeService
from apps.esb.services.tier1_webhooks import Tier1WebhookService, WebhookSignatureError
from apps.esb.services.tier3_workspace import Tier3ZeroITWorkspaceService


class Tier1OutboundWebhookView(APIView):
    permission_classes = [IsAuthenticated, IsGROOrOversight]

    def post(self, request):
        serializer = Tier1OutboundDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        complaint = get_object_or_404(Complaint, complaint_id=serializer.validated_data["complaint_id"])
        log = Tier1WebhookService.dispatch_outbound(
            agency_code=serializer.validated_data["agency_code"],
            event_type=serializer.validated_data["event_type"],
            complaint=complaint,
        )
        return Response(
            {"delivery_id": str(log.delivery_id), "status": log.status, "http_status": log.http_status},
            status=status.HTTP_201_CREATED,
        )


class Tier1InboundWebhookView(APIView):
    """Receives HMAC-SHA256 signed canonical webhooks from GRS, D-Nothi, 999, DESCO, WASA, BRTA, DNCC/DSCC."""

    permission_classes = [AllowAny]

    def post(self, request, agency_code: str):
        signature = request.headers.get("X-BD-ESB-Signature", "")
        try:
            log = Tier1WebhookService.receive_inbound(
                agency_code=agency_code.upper(),
                raw_bytes=request.body,
                signature=signature,
                payload=request.data if isinstance(request.data, dict) else {},
            )
        except WebhookSignatureError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response({"delivery_id": str(log.delivery_id), "status": log.status})


class Tier3RuralWorkspaceInboxView(APIView):
    """Zero-IT built-in workspace for Union Parishads and rural field seats."""

    permission_classes = [IsAuthenticated, IsDoptorOfficer]

    def get(self, request):
        items = Tier3ZeroITWorkspaceService.list_seat_inbox(request.user.doptor_seat_id)
        return Response({"doptor_seat_id": request.user.doptor_seat_id, "tickets": items})

    def post(self, request):
        serializer = Tier3RuralUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        complaint = get_object_or_404(Complaint, complaint_id=serializer.validated_data["complaint_id"])
        result = Tier3ZeroITWorkspaceService.post_rural_field_update(
            complaint=complaint,
            seat_id=request.user.doptor_seat_id,
            actor_id=str(request.user.id),
            update_note=serializer.validated_data["update_note"],
        )
        return Response(result, status=status.HTTP_200_OK)


class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge", "")
        if token == getattr(settings, "WHATSAPP_VERIFY_TOKEN", ""):
            return HttpResponse(challenge, content_type="text/plain")
        return Response({"detail": "Invalid verify token."}, status=status.HTTP_403_FORBIDDEN)

    def post(self, request):
        serializer = SocialBotWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = OmnichannelIntakeService.ingest_social_bot(
            channel=OmnichannelIntakeRecord.Channel.WHATSAPP, **serializer.validated_data
        )
        return Response(res, status=status.HTTP_201_CREATED)


class MessengerWebhookView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge", "")
        if token == getattr(settings, "MESSENGER_VERIFY_TOKEN", ""):
            return HttpResponse(challenge, content_type="text/plain")
        return Response({"detail": "Invalid verify token."}, status=status.HTTP_403_FORBIDDEN)

    def post(self, request):
        serializer = SocialBotWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        res = OmnichannelIntakeService.ingest_social_bot(
            channel=OmnichannelIntakeRecord.Channel.MESSENGER, **serializer.validated_data
        )
        return Response(res, status=status.HTTP_201_CREATED)


class Compact2GSMSUSSDIntakeView(APIView):
    """<140-byte SMS / USSD degraded-mode intake endpoint for 2G disaster fallback."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = Compact2GIntakeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            res = OmnichannelIntakeService.ingest_compact_2g(**serializer.validated_data)
        except CompactSMSParseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(res, status=status.HTTP_201_CREATED)
