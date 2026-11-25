#!/usr/bin/env bash
set -euo pipefail

# Protikar National Redress Platform — One-Command Local Startup & Demo Reset
# Usage:
#   ./run_local.sh              # Migrate, seed demo data if empty, start runserver on :8000
#   ./run_local.sh --reset      # Flush/re-seed demo scenarios & start runserver
#   ./run_local.sh --port 8080  # Run on custom port

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RESET_DEMO=false
PORT="8000"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)
      RESET_DEMO=true
      shift
      ;;
    --port)
      PORT="${2:-8000}"
      shift 2
      ;;
    -h|--help)
      echo "Usage: ./run_local.sh [--reset] [--port 8000]"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [[ -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
else
  echo "[warn] No .venv found in $SCRIPT_DIR; using system python3."
fi

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.dev}"
mkdir -p "$SCRIPT_DIR/media" "$SCRIPT_DIR/staticfiles"

echo "[1/4] Checking Django configuration..."
python manage.py check

echo "[2/4] Applying database migrations..."
python manage.py migrate --noinput

if [[ "$RESET_DEMO" == "true" ]]; then
  echo "[3/4] Resetting and re-seeding demo dataset..."
  python manage.py flush --no-input
  python manage.py seed_demo_data
else
  NEEDS_SEED="$(python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()
from django.contrib.auth import get_user_model
from apps.complaints.models import Complaint
User = get_user_model()
has_data = Complaint.objects.exists() and User.objects.filter(username="citizen_demo").exists()
print("0" if has_data else "1")
PY
)"
  if [[ "$NEEDS_SEED" == "1" ]]; then
    echo "[3/4] Database empty — seeding Bangladesh GIS & demo scenarios..."
    python manage.py seed_demo_data
  else
    echo "[3/4] Demo dataset already present (use --reset to re-seed)."
  fi
fi

echo "[4/4] Starting Protikar National Redress Platform on http://127.0.0.1:${PORT}/"
echo "  Citizen Portal:    http://127.0.0.1:${PORT}/"
echo "  UDC Intake Desk:   http://127.0.0.1:${PORT}/udc/"
echo "  Officer Workspace: http://127.0.0.1:${PORT}/officer/"
echo "  Field Worker PWA:  http://127.0.0.1:${PORT}/officer/field/"
echo "  Command Center:    http://127.0.0.1:${PORT}/command/"
echo "  Public Analytics:  http://127.0.0.1:${PORT}/analytics/"
echo "  Django Admin:      http://127.0.0.1:${PORT}/admin/"

exec python manage.py runserver "0.0.0.0:${PORT}"
