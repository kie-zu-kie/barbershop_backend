import os
from pathlib import Path

from dotenv import load_dotenv

CONFIG_DIRECTORY = Path(__file__).resolve().parent
PROJECT_DIRECTORY = CONFIG_DIRECTORY.parent

# Support the documented project-root .env and backend/.env used by existing
# checkouts. The project-root file takes precedence; process variables remain
# authoritative because load_dotenv does not override them by default.
load_dotenv(PROJECT_DIRECTORY / ".env")
load_dotenv(CONFIG_DIRECTORY / ".env")


def normalize_database_url(database_url):
    """Select the PostgreSQL driver installed by backend/requirements.txt."""
    if database_url and database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url and database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "cj-barbershop-dev-secret")
    USE_LOCAL_DATABASE = os.getenv("USE_LOCAL_DATABASE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.getenv("DATABASE_URL"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
