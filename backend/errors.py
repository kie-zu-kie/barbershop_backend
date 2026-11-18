from flask import jsonify, render_template, request
from sqlalchemy.exc import SQLAlchemyError


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found"), 404
        return render_template("404.html"), 404

    @app.errorhandler(SQLAlchemyError)
    def database_unavailable(error):
        app.logger.exception("Database request failed", exc_info=error)
        if request.path.startswith("/api/"):
            return jsonify(error="Database is temporarily unavailable."), 503
        return render_template("500.html"), 503

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled server error", exc_info=error)
        if request.path.startswith("/api/"):
            return jsonify(error="Internal server error"), 500
        return render_template("500.html"), 500

    @app.errorhandler(413)
    def request_too_large(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Upload is too large. Maximum request size is 6 MB."), 413
        return "Upload is too large.", 413
