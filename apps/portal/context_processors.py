from django.conf import settings

from apps.accounts.demo_roles import DEMO_ROLES
from apps.complaints.models import CitizenNotification
from apps.portal.i18n import STATUS_LABELS, URGENCY_LABELS, get_portal_strings

DEMO_ROLE_LABELS_BN: dict[str, str] = {
    "citizen_demo": "নাগরিক",
    "whistleblower_demo": "গোপন তথ্যদাতা",
    "udc_operator": "ইউডিসি উদ্যোক্তা",
    "gro_dncc": "অনিক (ডিএনসিসি)",
    "supervisor_dpdc": "সুপারভাইজার (ডিপিডিসি)",
    "field_worker_1": "মাঠকর্মী",
    "dc_dhaka_arbitrator": "জেলা প্রশাসক (সালিশি)",
    "command_admin": "কমান্ড অ্যাডমিন",
}


def portal_i18n(request):
    lang = request.session.get("portal_lang") or request.GET.get("lang") or "en"
    if lang not in ("en", "bn"):
        lang = "en"
    demo_enabled = bool(getattr(settings, "DEBUG", False) or getattr(settings, "DEMO_MODE", False))
    enriched_roles = []
    active_demo_role = None
    user = getattr(request, "user", None)
    current_username = user.username if user and user.is_authenticated else ""

    if demo_enabled:
        for r in DEMO_ROLES:
            item = {
                **r,
                "display_label": DEMO_ROLE_LABELS_BN.get(r["username"], r["label"]) if lang == "bn" else r["label"],
            }
            enriched_roles.append(item)
            if current_username and r["username"] == current_username:
                active_demo_role = item

    # FR09: Citizen Multi-Channel Notification Center
    try:
        if user and user.is_authenticated:
            notif_qs = CitizenNotification.objects.filter(user=user)
            if not notif_qs.exists():
                notif_qs = CitizenNotification.objects.all()
        else:
            notif_qs = CitizenNotification.objects.all()
        recent_notifications = list(notif_qs.select_related("complaint").order_by("-created_at")[:8])
        unread_notifications_count = notif_qs.filter(is_read=False).count()
    except Exception:
        recent_notifications = []
        unread_notifications_count = 0

    return {
        "portal_lang": lang,
        "t": get_portal_strings(lang),
        "urgency_labels": URGENCY_LABELS[lang],
        "status_labels": STATUS_LABELS[lang],
        "demo_mode": demo_enabled,
        "demo_roles": enriched_roles,
        "active_demo_role": active_demo_role,
        "recent_notifications": recent_notifications,
        "unread_notifications_count": unread_notifications_count,
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", ""),
    }
