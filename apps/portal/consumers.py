"""Django Channels WebSocket consumers for Live Disaster H3 Command Map & Case Timelines."""

from __future__ import annotations

import json
from channels.generic.websocket import AsyncWebsocketConsumer


class DisasterCommandConsumer(AsyncWebsocketConsumer):
    """Streams live H3 Res-8 surge cells, Crisis Mode toggles, and P1 Rescue dispatches."""

    GROUP_NAME = "national_disaster_command"

    async def connect(self):
        await self.channel_layer.group_add(self.GROUP_NAME, self.channel_name)
        await self.accept()
        await self.send(
            text_data=json.dumps(
                {
                    "type": "connection.ready",
                    "channel": self.GROUP_NAME,
                    "h3_resolution": 8,
                }
            )
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.GROUP_NAME, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            payload = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if payload.get("action") == "ping":
            await self.send(text_data=json.dumps({"type": "pong"}))

    async def disaster_event(self, event):
        await self.send(text_data=json.dumps(event.get("data", {})))


class ComplaintTimelineConsumer(AsyncWebsocketConsumer):
    """Streams live Parent/Child, e-GP Capital Milestone, and Master Incident updates."""

    async def connect(self):
        self.tracking_code = self.scope["url_route"]["kwargs"]["tracking_code"]
        self.group_name = f"complaint_{self.tracking_code}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def timeline_update(self, event):
        await self.send(text_data=json.dumps(event.get("data", {})))
