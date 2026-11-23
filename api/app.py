"""
The website's API. Master control only.

    flask --app api.app run --port 5000        (development)
    gunicorn "api.app:create_app()"            (production)

It shares `core/` (models, services, access rules) with the Telegram bot and
talks to the same PostgreSQL database; the two never call each other. A
decision made here (approve, revoke) is delivered to the person by the bot's
poller within about 30 seconds.
"""

import os

from flask import Flask, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from core import config
from core import db as dbmod


class ApiError(Exception):
    """An error with an HTTP status and a message safe to show the user."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def create_app(database_url=None, init_db=True):
    app = Flask(__name__)
    secret = (os.environ.get('SECRET_KEY') or '').strip()
    if not secret:
        raise RuntimeError('SECRET_KEY is not set. It signs website logins; use a long random value.')
    app.config['SECRET_KEY'] = secret
    app.config['JWT_HOURS'] = int(os.environ.get('JWT_HOURS', '12'))
    app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024        # CSV uploads

    if init_db:      # tests bind the session to their own transaction and skip this
        dbmod.init_engine(database_url or config.database_url())

    origins = [o.strip() for o in (os.environ.get('CORS_ORIGINS') or '').split(',') if o.strip()]
    if origins:
        CORS(app, origins=origins, supports_credentials=True)

    from api import routes
    routes.register(app)

    @app.teardown_appcontext
    def _close_session(exc=None):
        # Fresh session per request, exactly like the bot's run_db().
        if exc is not None:
            dbmod.Session.rollback()
        dbmod.Session.remove()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify({'error': err.message}), err.status

    @app.errorhandler(HTTPException)
    def _http_error(err):
        return jsonify({'error': err.description}), err.code

    @app.errorhandler(Exception)
    def _unexpected(err):
        app.logger.exception('Unhandled error')
        return jsonify({'error': 'Something went wrong on the server.'}), 500

    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')))
