"""Кто что видит. Права проверяются здесь, а не в интерфейсе."""
from functools import wraps
from flask import session, jsonify, g

from .db import one, rows, connect


def conn():
    """Одно соединение на запрос."""
    if 'conn' not in g:
        g.conn = connect()
    return g.conn


def close_conn(_exc=None):
    c = g.pop('conn', None)
    if c is not None:
        try:
            c.rollback()
        except Exception:
            pass
        c.close()


def me():
    uid = session.get('uid')
    return {'id': uid, 'role': session.get('role')} if uid else None


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            u = me()
            if not u:
                return jsonify(error='not_logged_in'), 401
            if roles and u['role'] not in roles:
                return jsonify(error='forbidden'), 403
            return fn(*a, **kw)
        return inner
    return deco


def teaches(c, uid, offering_id, role='teacher') -> bool:
    if role == 'admin':
        return True
    return bool(one(c, '''
        SELECT 1 FROM course_offerings o WHERE o.id = %(o)s AND o.teacher_id = %(u)s
        UNION SELECT 1 FROM offering_staff s WHERE s.offering_id = %(o)s AND s.teacher_id = %(u)s
    ''', {'o': offering_id, 'u': uid}))


def advises(c, uid, student_id) -> bool:
    return bool(one(c, '''
        SELECT 1 FROM advisor_assignments
        WHERE advisor_id = %(u)s AND student_id = %(s)s
          AND starts_on <= CURRENT_DATE AND (ends_on IS NULL OR ends_on >= CURRENT_DATE)
    ''', {'u': uid, 's': student_id}))


def can_see_student(c, uid, student_id, role='teacher') -> bool:
    if role == 'admin' or advises(c, uid, student_id):
        return True
    return bool(one(c, '''
        SELECT 1 FROM enrollments e
        JOIN course_offerings o ON o.id = e.offering_id
        WHERE e.student_id = %(s)s AND (o.teacher_id = %(u)s OR EXISTS
              (SELECT 1 FROM offering_staff f WHERE f.offering_id = o.id AND f.teacher_id = %(u)s))
        LIMIT 1
    ''', {'s': student_id, 'u': uid}))
