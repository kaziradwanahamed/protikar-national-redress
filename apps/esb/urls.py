from django.urls import path

from apps.esb.views import (
    Compact2GSMSUSSDIntakeView,
    MessengerWebhookView,
    Tier1InboundWebhookView,
    Tier1OutboundWebhookView,
    Tier3RuralWorkspaceInboxView,
    WhatsAppWebhookView,
)

app_name = "esb"

urlpatterns = [
    path("tier1/dispatch/", Tier1OutboundWebhookView.as_view(), name="tier1-dispatch"),
    path("tier1/webhooks/<str:agency_code>/", Tier1InboundWebhookView.as_view(), name="tier1-inbound"),
    path("tier3/workspace/", Tier3RuralWorkspaceInboxView.as_view(), name="tier3-workspace"),
    path("webhooks/whatsapp/", WhatsAppWebhookView.as_view(), name="webhook-whatsapp"),
    path("webhooks/messenger/", MessengerWebhookView.as_view(), name="webhook-messenger"),
    path("webhooks/sms-ussd/", Compact2GSMSUSSDIntakeView.as_view(), name="webhook-sms-ussd"),
]
