#!/usr/bin/env bash
set -euo pipefail

# Render.com build script for the Protikar National Redress Platform.
# Runs dependency installation, static collection, migrations, demo seeding,
# and ensures the default admin account exists.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"

echo "[1/6] Installing Python dependencies..."
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "[2/6] Collecting static files..."
python manage.py collectstatic --no-input

echo "[3/6] Ensuring PostGIS extension..."
python manage.py ensure_postgis

echo "[4/6] Applying database migrations..."
python manage.py migrate --no-input

echo "[5/6] Seeding demo data..."
python manage.py seed_demo_data

echo "[6/6] Ensuring default superuser (admin)..."
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
user = User.objects.filter(username='admin').first()
if user is None:
    user = User(
        username='admin',
        email='admin@protikar.gov.bd',
        account_type=User.AccountType.SYSTEM,
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
    user.set_password('Admin@2026')
    user.save()
    print('Created default superuser: admin / Admin@2026')
else:
    changed_fields = []
    for field in ('is_staff', 'is_superuser', 'is_active'):
        if not getattr(user, field):
            setattr(user, field, True)
            changed_fields.append(field)
    if changed_fields:
        user.save(update_fields=changed_fields)
    print('Default superuser admin already exists.')
"

echo "Build complete."
