# Government of Bangladesh — One-Stop AI Citizen Grievance & Redress Platform

Production-grade, national-scale civic grievance redress, AI triage, Doptor organogram routing, disaster surge command, and 3-tier ESB platform built for deployment on the **Bangladesh National Data Center (NDC)**.

## Platform Architecture (Parts 1–8)
- **Core Stack:** Django 5.1+, GeoDjango (PostgreSQL 16 + PostGIS 3.4), Django REST Framework + DRF-GIS, Gunicorn (WSGI) + Daphne (ASGI/Channels WebSockets), Celery 5.4 + Beat, Redis 7.4, Apache Kafka 3.8 (KRaft), MinIO (SSE-S3 AES-256), HashiCorp Vault (Transit Engine), Tailwind CSS + HTMX + Alpine.js + Leaflet.js, Prometheus + Grafana.
- **`apps/accounts/`:** Citizen SSO (`myGov`/`Porichoy` OAuth 2.0/OIDC + Mobile OTP + NID/BDRIS), persistent `UCT` & `Pseudonymous Public Hash`, 3-strike manual pre-moderation, HashiCorp Vault AES-256-GCM whistleblower envelope encryption, and seat/oversight RBAC.
- **`apps/organogram/`:** Doptor SSO (`Ministry -> Directorate -> Division -> District -> Upazila -> Office -> Seat`), Zero-Black-Hole 3-tier vacant seat fallback (`Primary -> Additional Charge -> Immediate Supervisor + HR Alert`), PostGIS `ServiceAreaPolygon`, bulk KML/GeoJSON importer, and seat hygiene auditor.
- **`apps/complaints/`:** `Complaint` (`PointField(geography=True)`, `transfer_count <= 2` DB constraint), `TicketAssignment`, `ResolutionReport`, and tamper-evident SHA-256 hash-chained `AuditLog`.
- **`apps/workflow/`:** Statutory lifecycle state machine, P1–P4 tiered SLAs (4h / 48h / 7–15d / 30d), 70% field-worker sub-deadlines, Two-Key 100m PostGIS verification gate + 72h citizen verdict, 15% transfer window & max-2 arbitration lock, `ON_HOLD_PROCUREMENT` e-GP/D-Nothi Capital Milestone Tracker, 48h `CONTESTED_BY_OFFICER` Right of Reply, `UNFOUNDED_CLEARED`, and 5-minute 4-tier Celery Beat escalation + Monthly DDCC daemon.
- **`apps/ai_triage/`:** Bangla/Banglish/dialect ASR + VLM/Bangla OCR, 58-Ministry / 350+-Agency hierarchical classifier (85%/60%/<60% gates), Compound Complaint Splitter with engineering dependency DAGs, Bangla Geo-NER + PostGIS jurisdiction resolver, 200m `ST_DWithin` spatial deduplication, and 5,000+ historical GRS Shadow-Routing Dry Run Simulator.
- **`apps/disaster/` & `apps/esb/`:** 5x rolling-velocity Circuit Breaker + MoDMR/DC toggle, Kafka + O(1) Uber H3 Res-8 Redis macro-incident heatmaps, P1 Life-Safety Fast-Lane (999/Fire/Armed Forces/CPP), automatic `P3/P4` `DISASTER_SLA_SUSPENDED`, 3-Tier ESB (Tier-1 signed webhooks, Tier-2 10m RPA bridge, Tier-3 Zero-IT Union Parishad workspace), WhatsApp/Messenger webhooks, and `<140-byte` 2G SMS/USSD fallback.
- **`apps/portal/`:** Bilingual (Bangla/English) Citizen Portal, UDC Assisted-Intake Desk (printable receipts), Doptor Officer & mobile Offline-First Field Worker PWA (`manifest.json`, `sw.js`, IndexedDB sync + `<140-byte` 2G SMS fallback), and National Command Center (WebSocket H3 map + DDCC CSV/PDF export).

## Quick Start (Local Development)
```bash
cp .env.example .env
docker compose up --build -d
docker compose exec web python manage.py seed_bangladesh_gis --with-sample-complaints
docker compose exec web python manage.py createsuperuser
```

## Bangladesh National Data Center (NDC) Production Deployment
1. Configure production secrets in `.env` (`DJANGO_DEBUG=False`, `VAULT_MODE=hashicorp`, `IDENTITY_PROVIDER_MODE=production`, `DOPTOR_PROVIDER_MODE=production`, `KAFKA_PROVIDER_MODE=production`, `ESB_PROVIDER_MODE=production`).
2. Place TLS certificates (`fullchain.pem`, `privkey.pem`) inside `deploy/nginx/certs/`.
3. Launch the hardened NDC stack:
```bash
docker compose -f deploy/docker-compose.prod.yml up --build -d
```
4. Initialize HashiCorp Vault Transit key for whistleblower PII envelope encryption:
```bash
docker compose -f deploy/docker-compose.prod.yml exec vault sh /vault/config/init-transit.sh
```
5. Verify health, readiness, and Prometheus metrics:
   - `GET /healthz/` (liveness)
   - `GET /readyz/` (PostgreSQL + PostGIS readiness)
   - `GET /metrics` (Prometheus scrape endpoint, restricted to internal VPC)
   - Grafana dashboard: `http://127.0.0.1:3000` (provisioned with `NDC-Prometheus`)

## Environment Variables Reference
| Variable | Purpose | Default / Example |
| :--- | :--- | :--- |
| `DJANGO_SETTINGS_MODULE` | Active settings module | `config.settings.prod` |
| `DJANGO_SECRET_KEY` | Cryptographic signing key | 64-char random secret |
| `POSTGRES_DB` / `USER` / `PASSWORD` | PostgreSQL 16 + PostGIS credentials | `bd_grievance` |
| `REDIS_URL` / `CELERY_BROKER_URL` | Redis cache, Channels & Celery broker | `redis://:pass@redis:6379/0` |
| `KAFKA_BOOTSTRAP_SERVERS` | Apache Kafka KRaft brokers | `kafka:9092` |
| `MINIO_ENDPOINT_URL` / `MINIO_KMS_SECRET_KEY` | Encrypted S3 media store (SSE-S3) | `http://minio:9000` |
| `VAULT_MODE` / `VAULT_ADDR` / `VAULT_TOKEN` | HashiCorp Vault Transit envelope encryption | `hashicorp` / `http://vault:8200` |
| `IDENTITY_PROVIDER_MODE` / `MYGOV_OIDC_*` | Citizen myGov/Porichoy SSO | `mock` (dev) / `production` |
| `DOPTOR_PROVIDER_MODE` / `DOPTOR_*` | Official Doptor SSO & organogram | `mock` (dev) / `production` |
| `AI_PROVIDER_MODE` / `AI_WORKER_BASE_URL` | Whisper/VLM/Classifier FastAPI worker | `mock` (dev) / `http://ai-worker:8001` |
| `ESB_WEBHOOK_SIGNING_SECRET` | HMAC-SHA256 Tier-1 webhook signing secret | 64-char random secret |

## Celery Worker & Scheduler Commands
```bash
# Dedicated multi-queue worker (default, ai_triage, esb, workflow)
celery -A config worker --loglevel=info --concurrency=8 --queues=default,ai_triage,esb,workflow

# Statutory SLA Escalation (5m), Tier-2 RPA Bridge (10m) & Doptor Sync (nightly) Beat scheduler
celery -A config beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

## Pre-Launch Audit & Verification Commands
```bash
# Bulk import KML / GeoJSON service-area polygons into PostGIS
python manage.py import_gis_polygons /path/to/wards.geojson --zone-type CITY_CORP_WARD

# Audit Doptor seats for uncovered vacancies & broken reporting chains
python manage.py audit_doptor_seats --output seat_audit.json --fail-on-error

# Replay historical GRS complaints in zero-write dry-run shadow mode
python manage.py run_shadow_routing --file sample_data/historical_grs_sample.json

# Run full automated Django & Pytest safeguard integration suite
pytest tests/ -v
python manage.py test apps.accounts apps.organogram apps.workflow apps.ai_triage apps.disaster apps.esb apps.portal
```

## Rich Demo Scenarios & 1-Click Role Switcher (Part 9)
After `docker compose up --build -d`, seed 8 demo accounts (password `Demo@2026`) and 27 statutory Bangladesh grievance scenarios idempotently:
```bash
docker compose exec web python manage.py seed_demo_data  # (alias: seed_demo_scenarios)
```

When `DEBUG=True` or `DEMO_MODE=True` (set in `.env.example`), the **Quick Demo Role Switcher** bar appears in the top navbar for 1-click session switching across:
- `citizen_demo` -> `/` (Citizen Portal)
- `whistleblower_demo` -> `/` (Vault-Encrypted Whistleblower)
- `udc_operator` -> `/udc/` (Savar UDC Assisted-Intake Desk)
- `gro_dncc` -> `/officer/?seat_id=SEAT-DNCC-Z2-GRO` (DNCC Zone-2 GRO / অনিক)
- `supervisor_dpdc` -> `/officer/?seat_id=SEAT-DPDC-MIRPUR-SUP` (DPDC Mirpur Unit Supervisor)
- `field_worker_1` -> `/officer/field/` (Offline-First Field Worker PWA)
- `dc_dhaka_arbitrator` -> `/command/` (DC Dhaka Appellate & Arbitration)
- `command_admin` -> `/command/` (National Command Center & Cabinet Cell)

### Verify Zero Pending Migrations
```bash
docker compose exec web python manage.py makemigrations --check --dry-run
```

## Standalone FastAPI AI Microservice (`ai_service/`, Part 10)
The `ai-service` container runs FastAPI + Uvicorn on port `8001` (internal `backend` network) with OpenAPI docs at `http://127.0.0.1:8001/docs`:
- `GET /health` — Service & backend healthcheck
- `POST /api/v1/triage/analyze` — End-to-end ASR + VLM/Bangla OCR + 58-Ministry/350+-Agency classifier (`>=85%` auto-route, `60%–84%` GRO review, `<60%` bilingual clarifying questions) + Compound Splitter (`step_order: 1 -> 2 -> 3`) + Bangla Geo-NER & P1 Life-Safety filter
- `POST /api/v1/triage/transcribe` — Bangla, Banglish & regional dialect (Sylheti, Chittagonian, Barishali) ASR
- `POST /api/v1/triage/ocr` — Vision-Language hazard validation & Bangla digit-normalized receipt/e-GP/utility OCR

Django's `apps/ai_triage/services/ai_client.py` calls `AI_SERVICE_URL` (`http://ai-service:8001`) with bounded timeouts/retries and automatically falls back to local deterministic triage if `ai-service` is unreachable.

```bash
# Run Part 10 AI microservice & Django integration tests
docker compose exec web pytest tests/test_ai_microservice.py -v
```

## Google Maps Live GPS Integration (Part 11)
Set `GOOGLE_MAPS_API_KEY` in `.env` (with **Maps JavaScript API**, **Places API**, and **Geocoding API** enabled) to activate:
- **Citizen Portal (`/`):** Google Maps click/drag picker, Bangladesh-restricted Places Autocomplete, and **"Use My Live Location"** high-accuracy GPS + reverse geocoding.
- **Field Worker Workspace (`/officer/field/`):** Compact Google Map with Incident Pin, **100m Geofence Circle**, and live `watchPosition` distance badge (`Within 100m Gate` / `Outside 100m Gate`).
- **Command Center (`/command/`):** Live Google Maps view with urgency color-coded complaint pins (`P1` Red, `P2` Orange, `P3` Blue, `P4` Gray) and active H3 disaster cluster overlays.

If `GOOGLE_MAPS_API_KEY` is blank or invalid, all maps gracefully fall back to CartoDB Voyager tiles with browser GPS still active.
