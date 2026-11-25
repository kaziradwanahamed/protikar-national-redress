from django.urls import re_path

from apps.portal.consumers import ComplaintTimelineConsumer, DisasterCommandConsumer

websocket_urlpatterns = [
    re_path(r"^ws/disaster/command/$", DisasterCommandConsumer.as_asgi()),
    re_path(
        r"^ws/complaints/(?P<tracking_code>[A-Z0-9\-]+)/$",
        ComplaintTimelineConsumer.as_asgi(),
    ),
]
