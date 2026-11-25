"""Canonical 8-role demo catalog for the 1-Click Demo Role Switcher (DEBUG / DEMO_MODE only)."""

from __future__ import annotations

DEMO_PASSWORD = "Demo@2026"

DEMO_ROLES: list[dict[str, str]] = [
    {
        "username": "citizen_demo",
        "label": "Citizen",
        "subtitle": "myGov / Porichoy verified",
        "redirect_url": "/",
    },
    {
        "username": "whistleblower_demo",
        "label": "Whistleblower",
        "subtitle": "Vault-encrypted anonymous",
        "redirect_url": "/",
    },
    {
        "username": "udc_operator",
        "label": "UDC Operator",
        "subtitle": "Savar UDC walk-in desk",
        "redirect_url": "/udc/",
    },
    {
        "username": "gro_dncc",
        "label": "GRO (অনিক)",
        "subtitle": "DNCC Zone-2 seat",
        "redirect_url": "/officer/?seat_id=SEAT-DNCC-Z2-GRO",
    },
    {
        "username": "supervisor_dpdc",
        "label": "Unit Supervisor",
        "subtitle": "Exec Eng, DPDC Mirpur",
        "redirect_url": "/officer/?seat_id=SEAT-DPDC-MIRPUR-SUP",
    },
    {
        "username": "field_worker_1",
        "label": "Field Worker",
        "subtitle": "Mirpur Sub-Division PWA",
        "redirect_url": "/officer/field/",
    },
    {
        "username": "dc_dhaka_arbitrator",
        "label": "DC Arbitrator",
        "subtitle": "DC Dhaka appellate",
        "redirect_url": "/command/",
    },
    {
        "username": "command_admin",
        "label": "Command Admin",
        "subtitle": "National Command & Cabinet",
        "redirect_url": "/command/",
    },
]

DEMO_ROLE_REDIRECTS: dict[str, str] = {r["username"]: r["redirect_url"] for r in DEMO_ROLES}
