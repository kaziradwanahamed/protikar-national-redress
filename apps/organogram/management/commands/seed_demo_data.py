"""
Idempotent Demo Data Seeder (`python manage.py seed_demo_data`).
Populates demo role accounts (Demo@2026) and 25+ realistic Bangladesh complaints
across Citizen, UDC, Officer, Field Worker, Arbitration, e-GP Hold, and Sylhet Disaster dashboards.
"""

from apps.organogram.management.commands.seed_demo_scenarios import Command as BaseDemoCommand


class Command(BaseDemoCommand):
    help = (
        "Idempotently populates realistic Bangladesh demo data (accounts, 200m hotspot cluster, "
        "multi-department Parent/Child case, Pending Citizen Verification, Arbitration Locked, "
        "e-GP Procurement Hold, and Sylhet Flood H3 Disaster Zone)."
    )
