from flask import jsonify


def register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(error):
        return jsonify(error="Not found"), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled server error", exc_info=error)
        return jsonify(error="Internal server error"), 500

    @app.errorhandler(413)
    def request_too_large(error):
        return jsonify(error="Upload is too large. Maximum request size is 6 MB."), 413
