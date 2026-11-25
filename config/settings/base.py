from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default=env("SECRET_KEY", default="unsafe-dev-key-change-in-production"),
)
DEBUG = env.bool("DJANGO_DEBUG", default=env.bool("DEBUG", default=False))
DEMO_MODE = env.bool("DEMO_MODE", default=True)
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

DJANGO_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_gis",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "channels",
    "django_celery_beat",
    "django_celery_results",
    "django_htmx",
    "storages",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.organogram",
    "apps.complaints",
    "apps.workflow",
    "apps.ai_triage",
    "apps.disaster",
    "apps.esb",
    "apps.portal",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.portal.context_processors.portal_i18n",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": env("POSTGRES_DB", default="bd_grievance"),
        "USER": env("POSTGRES_USER", default="grievance_app"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="changeme_db_pass"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}

# Render / managed PostgreSQL connection string (takes precedence over POSTGRES_* vars)
DATABASE_URL = env("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {"default": env.db_url_config(DATABASE_URL)}
    DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
    DATABASES["default"]["CONN_MAX_AGE"] = 60
    DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("bn", "Bangla"),
    ("en", "English"),
]
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
USE_REMOTE_AI_SERVICE = env.bool("USE_REMOTE_AI_SERVICE", default=True)

# MinIO S3-Compatible Encrypted Media Storage (SSE-S3 AES-256) when configured,
# otherwise fall back to the local filesystem (Render single-service deployments).
MINIO_ENDPOINT_URL = env("MINIO_ENDPOINT_URL", default="")
USE_S3_STORAGE = env.bool("USE_S3_STORAGE", default=bool(MINIO_ENDPOINT_URL))

if USE_S3_STORAGE:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": env("MINIO_ROOT_USER", default="minioadmin"),
                "secret_key": env("MINIO_ROOT_PASSWORD", default="changeme_minio_pass"),
                "bucket_name": env("MINIO_BUCKET_MEDIA", default="grievance-media-encrypted"),
                "endpoint_url": MINIO_ENDPOINT_URL,
                "region_name": "ap-south-1",
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 900,
                "object_parameters": {"ServerSideEncryption": "AES256"},
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis Cache, Channels & Celery Broker (optional; falls back to in-memory when unset)
REDIS_URL = env("REDIS_URL", default="")

if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "bd-grievance-inmemory-cache",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

if not CELERY_BROKER_URL:
    # No broker available (e.g. Render free tier without Redis): execute tasks inline.
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = env.bool("CELERY_TASK_EAGER_PROPAGATES", default=False)

# Apache Kafka
KAFKA_BOOTSTRAP_SERVERS = env("KAFKA_BOOTSTRAP_SERVERS", default="kafka:9092")
KAFKA_TOPIC_PREFIX = env("KAFKA_TOPIC_PREFIX", default="bd.grievance")

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Government of Bangladesh — One-Stop AI Citizen Grievance & Redress API",
    "DESCRIPTION": "National-scale GeoDjango + AI Triage + Doptor Organogram Redress Platform.",
    "VERSION": "1.0.0",
}
# ---------------------------------------------------------------------------
# Part 2: Authentication Backends, Citizen SSO, Vault Envelope & Doptor SSO
# ---------------------------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.MyGovOIDCBackend",
    "apps.accounts.backends.DoptorSSOBackend",
    "django.contrib.auth.backends.ModelBackend",
]

IDENTITY_PROVIDER_MODE = env("IDENTITY_PROVIDER_MODE", default="mock")
UCT_HMAC_SECRET = env("UCT_HMAC_SECRET", default=SECRET_KEY)

MYGOV_OIDC_AUTHORIZE_URL = env("MYGOV_OIDC_AUTHORIZE_URL", default="https://idp.mygov.bd/oauth2/authorize")
MYGOV_OIDC_TOKEN_URL = env("MYGOV_OIDC_TOKEN_URL", default="https://idp.mygov.bd/oauth2/token")
MYGOV_OIDC_USERINFO_URL = env("MYGOV_OIDC_USERINFO_URL", default="https://idp.mygov.bd/oauth2/userinfo")
MYGOV_OIDC_CLIENT_ID = env("MYGOV_OIDC_CLIENT_ID", default="bd-grievance-platform")
MYGOV_OIDC_CLIENT_SECRET = env("MYGOV_OIDC_CLIENT_SECRET", default="dev-client-secret")
MYGOV_OIDC_REDIRECT_URI = env(
    "MYGOV_OIDC_REDIRECT_URI",
    default="http://localhost:8000/api/v1/accounts/sso/mygov/callback/",
)
PORICHOY_API_URL = env("PORICHOY_API_URL", default="https://api.porichoygov.com/api/v2/verifications/autofill")
PORICHOY_API_KEY = env("PORICHOY_API_KEY", default="dev-porichoy-key")

VAULT_MODE = env("VAULT_MODE", default="local_dev")
VAULT_ADDR = env("VAULT_ADDR", default="http://vault:8200")
VAULT_TOKEN = env("VAULT_TOKEN", default="dev-root-vault-token-change-in-prod")
VAULT_TRANSIT_KEY = env("VAULT_TRANSIT_KEY", default="whistleblower-transit-key")
VAULT_LOCAL_MASTER_KEY = env("VAULT_LOCAL_MASTER_KEY", default="local-dev-master-key-change-in-production-32b")

DOPTOR_PROVIDER_MODE = env("DOPTOR_PROVIDER_MODE", default="mock")
DOPTOR_SSO_TOKEN_URL = env("DOPTOR_SSO_TOKEN_URL", default="https://idp.doptor.gov.bd/oauth2/token")
DOPTOR_ORGANOGRAM_API_URL = env("DOPTOR_ORGANOGRAM_API_URL", default="https://api.doptor.gov.bd/v1/organogram")
DOPTOR_CLIENT_ID = env("DOPTOR_CLIENT_ID", default="bd-grievance-doptor")
DOPTOR_CLIENT_SECRET = env("DOPTOR_CLIENT_SECRET", default="dev-doptor-secret")
# ---------------------------------------------------------------------------
# Part 4: AI Triage Pipeline, Multimodal ASR/VLM & Spatial Deduplication
# ---------------------------------------------------------------------------
AI_PROVIDER_MODE = env("AI_PROVIDER_MODE", default="mock")
AI_WORKER_BASE_URL = env("AI_WORKER_BASE_URL", default="http://ai-worker:8001")
AI_WORKER_API_KEY = env("AI_WORKER_API_KEY", default="dev-ai-worker-key")
AI_AUTO_ROUTE_THRESHOLD = float(env("AI_AUTO_ROUTE_THRESHOLD", default="0.85"))
AI_GRO_FLAG_THRESHOLD = float(env("AI_GRO_FLAG_THRESHOLD", default="0.60"))
DEDUP_RADIUS_METERS = float(env("DEDUP_RADIUS_METERS", default="200"))
# ---------------------------------------------------------------------------
# Part 5: Disaster Surge Circuit Breaker, Kafka H3 & 3-Tier ESB / Omnichannel
# ---------------------------------------------------------------------------
DISASTER_SURGE_MULTIPLIER = float(env("DISASTER_SURGE_MULTIPLIER", default="5.0"))
DISASTER_H3_RESOLUTION = int(env("DISASTER_H3_RESOLUTION", default="8"))
KAFKA_PROVIDER_MODE = env("KAFKA_PROVIDER_MODE", default="mock")
ESB_PROVIDER_MODE = env("ESB_PROVIDER_MODE", default="mock")
ESB_WEBHOOK_SIGNING_SECRET = env("ESB_WEBHOOK_SIGNING_SECRET", default=SECRET_KEY)
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", default="dev-whatsapp-verify")
MESSENGER_VERIFY_TOKEN = env("MESSENGER_VERIFY_TOKEN", default="dev-messenger-verify")

AI_SERVICE_URL = env("AI_SERVICE_URL", default="http://ai-service:8001")
AI_SERVICE_TIMEOUT_SECONDS = float(env("AI_SERVICE_TIMEOUT_SECONDS", default="8.0"))

# Part 11: Google Maps Live GPS Integration
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", default="")
