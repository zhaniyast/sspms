"""Подключение к базе портала.

Адрес берётся так:
  1) переменная DATABASE_URL, если задана;
  2) иначе PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD (их можно положить в файл .env
     в корне проекта: тот же формат, что у бэкенда Мадины). Так пароль со спецсимволами
     (@ : / #) не ломает адрес.
"""
import os
import psycopg
from psycopg.rows import dict_row

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:          # python-dotenv не обязателен
    pass


def _dsn():
    url = os.environ.get('DATABASE_URL')
    if url:
        return url
    from psycopg.conninfo import make_conninfo
    parts = dict(host=os.getenv('PGHOST', 'localhost'), port=os.getenv('PGPORT', '5432'),
                 dbname=os.getenv('PGDATABASE', 'portal'), user=os.getenv('PGUSER', 'postgres'),
                 password=os.getenv('PGPASSWORD'))
    return make_conninfo(**{k: v for k, v in parts.items() if v is not None})


def connect():
    return psycopg.connect(_dsn(), row_factory=dict_row)


def rows(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall() if cur.description else []


def one(conn, sql, params=None):
    r = rows(conn, sql, params)
    return r[0] if r else None


def run(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall() if cur.description else []
