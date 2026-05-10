"""
Django settings for RecruitDataVsible project.

The original project targeted Django 2.x and a local MySQL instance. These
defaults keep that path available through environment variables, but use SQLite
by default so the project can run on a fresh machine without extra setup.
"""

import importlib.util
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def package_available(package_name):
    return importlib.util.find_spec(package_name) is not None


def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "2mh#x9r2c@ie81w==+&n2v4hbd2s_4f5@)!%=a$io-adm6b6jq",
)

DEBUG = env_flag("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dataView",
]

if package_available("rest_framework"):
    INSTALLED_APPS.append("rest_framework")

if package_available("dwebsocket"):
    INSTALLED_APPS.append("dwebsocket")

if DEBUG and package_available("debug_toolbar"):
    INSTALLED_APPS.append("debug_toolbar")


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

if "debug_toolbar" in INSTALLED_APPS:
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")


ROOT_URLCONF = "RecruitDataVsible.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "RecruitDataVsible.wsgi.application"


USE_MYSQL = env_flag("DJANGO_USE_MYSQL", False)

if USE_MYSQL:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DJANGO_MYSQL_NAME", "zhaopin_test"),
            "USER": os.environ.get("DJANGO_MYSQL_USER", "root"),
            "PASSWORD": os.environ.get("DJANGO_MYSQL_PASSWORD", "root"),
            "HOST": os.environ.get("DJANGO_MYSQL_HOST", "localhost"),
            "PORT": int(os.environ.get("DJANGO_MYSQL_PORT", 3306)),
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = True


STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

WEBSOCKET_ACCEPT_ALL = True
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
INTERNAL_IPS = ["127.0.0.1", "localhost"]
X_FRAME_OPTIONS = "SAMEORIGIN"
