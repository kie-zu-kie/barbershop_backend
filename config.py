import os
from pathlib import Path

from dotenv import load_dotenv

ENVIRONMENT_KEYS = (
    "DATABASE_URL",
    "SECRET_KEY",
    "FRONTEND_ORIGINS",
    "PUBLIC_API_URL",
    "SESSION_COOKIE_SAMESITE",
    "SESSION_COOKIE_SECURE",
)
for environment_key in ENVIRONMENT_KEYS:
    if not os.getenv(environment_key, "").strip():
        os.environ.pop(environment_key, None)

load_dotenv(Path(__file__).with_name(".env"))


def normalize_database_url(database_url):
    if database_url and database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url and database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL"))
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if origin.strip()
    ]
    PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://127.0.0.1:5000").rstrip("/")
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    SQLALCHEMY_TRACK_MODIFICATIONS = False
