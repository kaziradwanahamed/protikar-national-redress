"""Best-effort PostGIS extension bootstrap for managed PostgreSQL (e.g. Render)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Ensure the PostGIS extension exists before migrations run."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'postgis';")
            if cursor.fetchone():
                self.stdout.write(self.style.SUCCESS("PostGIS extension already enabled."))
                return

        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        except Exception as exc:
            self.stderr.write(
                "Could not create the PostGIS extension automatically: "
                f"{exc}\nDjango's PostGIS backend will retry "
                "'CREATE EXTENSION IF NOT EXISTS postgis' during migrate."
            )
        else:
            self.stdout.write(self.style.SUCCESS("PostGIS extension enabled."))
