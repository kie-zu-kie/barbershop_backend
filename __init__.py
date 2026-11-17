from pathlib import Path

from flask import Flask, redirect
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def create_app(test_config=None):
    backend_directory = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        static_folder=None,
        instance_path=str(backend_directory / "instance"),
    )
    app.config.from_object("backend.config.Config")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        UPLOAD_FOLDER=str(backend_directory / "uploads"),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    if app.config.get("SECRET_KEY") in {
        None,
        "",
        "cj-barbershop-dev-secret",
        "replace-with-a-unique-random-value",
    }:
        raise RuntimeError(
            "Set a unique, random SECRET_KEY in the backend environment before starting the API."
        )
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("Set DATABASE_URL in the backend environment before starting the API.")

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    CORS(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=True,
    )

    from backend.admin import register_admin_commands
    from backend.errors import register_error_handlers
    from backend.routes import api

    app.register_blueprint(api, url_prefix="/api")
    register_error_handlers(app)
    register_admin_commands(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    @app.get("/api")
    def open_frontend():
        frontend_origins = app.config["CORS_ORIGINS"]
        if not frontend_origins:
            return {"error": "No frontend origin is configured."}, 503
        return redirect(f"{frontend_origins[0].rstrip('/')}/")

    return app
