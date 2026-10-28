"""
Сервер портала.   Запуск из корня проекта:

    set DATABASE_URL=postgresql://postgres:ПАРОЛЬ@localhost:5432/portal
    python -m backend.app

Установить один раз:  pip install flask "psycopg[binary]" argon2-cffi joblib scikit-learn pandas numpy
"""
import datetime as dt
import decimal
import os
from pathlib import Path

from flask import Flask, jsonify, send_from_directory
from flask.json.provider import DefaultJSONProvider

from . import access, routes_common, routes_student, routes_teacher, routes_syllabus

ROOT = Path(__file__).resolve().parent.parent


class Provider(DefaultJSONProvider):
    @staticmethod
    def default(o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, (dt.datetime, dt.date, dt.time)):
            return o.isoformat()
        return DefaultJSONProvider.default(o)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.json = Provider(app)
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-me')
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
                      PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=12))
    if os.environ.get('BEHIND_PROXY') == '1':      # на хостинге HTTPS заканчивается на прокси
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.teardown_appcontext(access.close_conn)
    for m in (routes_common, routes_student, routes_teacher, routes_syllabus):
        app.register_blueprint(m.bp)

    @app.errorhandler(Exception)
    def boom(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return jsonify(error=e.name.lower().replace(' ', '_')), e.code
        app.logger.exception(e)
        return jsonify(error='server_error'), 500

    # React-интерфейс: после `npm run build` лежит в frontend/dist; без сборки - старая папка webapp
    web = ROOT / 'frontend' / 'dist'
    if not web.exists():
        web = ROOT / 'webapp'

    @app.get('/healthz')
    def healthz():
        return jsonify(ok=True)

    @app.get('/')
    def index():
        return send_from_directory(web, 'index.html')

    @app.get('/<path:p>')
    def static_files(p):
        if p.startswith('api/'):
            return jsonify(error='not_found'), 404
        f = web / p
        if f.is_file():
            return send_from_directory(web, p)
        return send_from_directory(web, 'index.html')

    return app


if __name__ == '__main__':
    create_app().run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', 8000)), debug=False)
