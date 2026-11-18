from pathlib import Path

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.engine import make_url

db = SQLAlchemy()


def create_app(test_config=None):
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(project_root / "frontend" / "templates"),
        static_folder=str(project_root / "frontend" / "static"),
        instance_path=str(project_root / "backend" / "instance"),
    )
    app.config.from_object("backend.config.Config")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        UPLOAD_FOLDER=str(project_root / "backend" / "uploads"),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    if app.config.get("USE_LOCAL_DATABASE") and not (
        test_config and "SQLALCHEMY_DATABASE_URI" in test_config
    ):
        local_database_directory = Path.home() / ".cj_barbershop"
        local_database_directory.mkdir(parents=True, exist_ok=True)
        local_database = local_database_directory / "barbershop-local.sqlite"
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{local_database.as_posix()}"

    database_uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it in the project-root .env, "
            "backend/.env, or the process environment."
        )
    if database_uri and make_url(database_uri).get_backend_name() == "postgresql":
        engine_options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}))
        connect_args = dict(engine_options.get("connect_args", {}))
        connect_args.setdefault("connect_timeout", 2)
        engine_options["connect_args"] = connect_args
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_options

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    from backend.admin import register_admin_commands
    from backend.errors import register_error_handlers
    from backend.routes import api, pages

    app.register_blueprint(pages)
    app.register_blueprint(api, url_prefix="/api")
    register_error_handlers(app)
    register_admin_commands(app)
    return app
