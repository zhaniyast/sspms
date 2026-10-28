import datetime as dt

import numpy as np
import pandas as pd
from flask import Blueprint, jsonify, request, session

from .access import conn, login_required, me, teaches, can_see_student
from .common import latest_week, person_name, lang_col
from .db import rows, one, run
from .features import FEATURES, LABELS, fetch_features
from .scoring import bundle, level, recompute, active_model_id

bp = Blueprint('common', __name__, url_prefix='/api')

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError
    _ph = PasswordHasher()
except ImportError:          # без argon2-cffi войти нельзя, и это лучше, чем пускать без проверки
    _ph = None


# ------------------------------------------------------------------ вход

@bp.post('/auth/login')
def login():
    if _ph is None:
        return jsonify(error='argon2_not_installed', hint='pip install argon2-cffi'), 500
    d = request.get_json(force=True, silent=True) or {}
    c = conn()
    u = one(c, 'SELECT id, password_hash, role, is_active FROM users WHERE login_id=%(l)s',
            {'l': (d.get('login_id') or '').strip()})
    ok = False
    if u and u['is_active']:
        try:
            ok = _ph.verify(u['password_hash'], d.get('password') or '')
        except (VerifyMismatchError, InvalidHashError):
            ok = False
    if not ok:
        return jsonify(error='bad_credentials'), 401
    run(c, 'UPDATE users SET last_login = now() WHERE id=%(i)s', {'i': u['id']})
    c.commit()
    session.clear()
    session['uid'], session['role'] = u['id'], u['role']
    session.permanent = True
    return jsonify(id=u['id'], role=u['role'], name=person_name(c, u['id']))


@bp.post('/auth/logout')
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get('/me')
@login_required()
def whoami():
    c = conn(); u = me()
    sem, week = latest_week(c)
    unread = one(c, 'SELECT COUNT(*) AS n FROM notifications WHERE user_id=%(u)s AND NOT is_read', {'u': u['id']})['n']
    return jsonify(id=u['id'], role=u['role'], name=person_name(c, u['id']),
                   semester_id=sem['id'], week=week, unread=int(unread))


# ------------------------------------------------------------------ уведомления

@bp.get('/notifications')
@login_required()
def notifications():
    return jsonify(items=rows(conn(), '''SELECT id, type, title, link, is_read, created_at FROM notifications
                                         WHERE user_id=%(u)s ORDER BY created_at DESC LIMIT 50''', {'u': me()['id']}))


@bp.post('/notifications/<int:nid>/read')
@login_required()
def read_one(nid):
    c = conn()
    run(c, 'UPDATE notifications SET is_read=true WHERE id=%(i)s AND user_id=%(u)s', {'i': nid, 'u': me()['id']})
    c.commit()
    return jsonify(ok=True)


@bp.post('/notifications/read-all')
@login_required()
def read_all():
    c = conn()
    run(c, 'UPDATE notifications SET is_read=true WHERE user_id=%(u)s AND NOT is_read', {'u': me()['id']})
    c.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ сообщения

@bp.get('/messages/conversations')
@login_required()
def conversations():
    return jsonify(items=rows(conn(), '''
        SELECT cv.id, cv.kind, cv.title, cv.offering_id,
               (SELECT m.body FROM messages m WHERE m.conversation_id = cv.id ORDER BY m.sent_at DESC LIMIT 1) AS last_body,
               (SELECT MAX(m.sent_at) FROM messages m WHERE m.conversation_id = cv.id) AS last_at,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = cv.id AND m.sender_id <> %(u)s
                  AND (p.last_read_at IS NULL OR m.sent_at > p.last_read_at)) AS unread
        FROM conversation_participants p JOIN conversations cv ON cv.id = p.conversation_id
        WHERE p.user_id = %(u)s ORDER BY last_at DESC NULLS LAST''', {'u': me()['id']}))


def _member(c, cid, uid):
    return one(c, 'SELECT 1 FROM conversation_participants WHERE conversation_id=%(c)s AND user_id=%(u)s',
               {'c': cid, 'u': uid})


@bp.get('/messages/conversations/<int:cid>')
@login_required()
def conversation(cid):
    c = conn(); u = me()
    if not _member(c, cid, u['id']):
        return jsonify(error='forbidden'), 403
    msgs = rows(c, 'SELECT id, sender_id, body, attachment_url, sent_at FROM messages '
                   'WHERE conversation_id=%(c)s ORDER BY sent_at', {'c': cid})
    run(c, 'UPDATE conversation_participants SET last_read_at = now() WHERE conversation_id=%(c)s AND user_id=%(u)s',
        {'c': cid, 'u': u['id']})
    c.commit()
    return jsonify(messages=msgs)


@bp.post('/messages/conversations/<int:cid>')
@login_required()
def send(cid):
    c = conn(); u = me()
    body = ((request.get_json(force=True, silent=True) or {}).get('body') or '').strip()
    if not _member(c, cid, u['id']) or not body:
        return jsonify(error='forbidden_or_empty'), 403
    r = run(c, 'INSERT INTO messages (conversation_id, sender_id, body, sent_at) VALUES (%(c)s,%(u)s,%(b)s,now()) RETURNING id',
            {'c': cid, 'u': u['id'], 'b': body})
    for p in rows(c, 'SELECT user_id FROM conversation_participants WHERE conversation_id=%(c)s AND user_id <> %(u)s',
                  {'c': cid, 'u': u['id']}):
        run(c, "INSERT INTO notifications (user_id, type, title, link) VALUES (%(p)s,'message','Новое сообщение',%(l)s)",
            {'p': p['user_id'], 'l': f'/messages/{cid}'})
    run(c, 'UPDATE conversation_participants SET last_read_at = now() WHERE conversation_id=%(c)s AND user_id=%(u)s',
        {'c': cid, 'u': u['id']})
    c.commit()
    return jsonify(id=r[0]['id']), 201


@bp.post('/messages/direct')
@login_required()
def start_direct():
    """Личный диалог. Студент может писать только своим преподавателям и эдвайзеру,
    преподаватель только студентам, которых видит."""
    c = conn(); u = me()
    d = request.get_json(force=True, silent=True) or {}
    to, body = d.get('to'), (d.get('body') or '').strip()
    if not to or not body or to == u['id']:
        return jsonify(error='bad_request'), 400
    target = one(c, 'SELECT role FROM users WHERE id=%(i)s AND is_active', {'i': to})
    if not target:
        return jsonify(error='no_user'), 404
    if u['role'] == 'student':
        allowed = target['role'] == 'teacher' and (one(c, '''
            SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id
            WHERE e.student_id = %(s)s AND (o.teacher_id = %(t)s OR EXISTS
                  (SELECT 1 FROM offering_staff f WHERE f.offering_id = o.id AND f.teacher_id = %(t)s)) LIMIT 1''',
                                                    {'s': u['id'], 't': to}) or one(c, '''
            SELECT 1 FROM advisor_assignments WHERE advisor_id=%(t)s AND student_id=%(s)s''', {'t': to, 's': u['id']}))
    elif target['role'] == 'student':
        allowed = can_see_student(c, u['id'], to, u['role'])
    else:
        allowed = True
    if not allowed:
        return jsonify(error='forbidden'), 403
    cid = one(c, '''SELECT cv.id FROM conversations cv
                    JOIN conversation_participants a ON a.conversation_id = cv.id AND a.user_id = %(a)s
                    JOIN conversation_participants b ON b.conversation_id = cv.id AND b.user_id = %(b)s
                    WHERE cv.kind = 'direct' LIMIT 1''', {'a': u['id'], 'b': to})
    if cid:
        cid = cid['id']
    else:
        cid = run(c, "INSERT INTO conversations (kind, created_at) VALUES ('direct', now()) RETURNING id")[0]['id']
        for x in (u['id'], to):
            run(c, 'INSERT INTO conversation_participants (conversation_id, user_id) VALUES (%(c)s,%(u)s)', {'c': cid, 'u': x})
    run(c, 'INSERT INTO messages (conversation_id, sender_id, body, sent_at) VALUES (%(c)s,%(u)s,%(b)s,now())',
        {'c': cid, 'u': u['id'], 'b': body})
    run(c, "INSERT INTO notifications (user_id, type, title, link) VALUES (%(p)s,'message','Новое сообщение',%(l)s)",
        {'p': to, 'l': f'/messages/{cid}'})
    c.commit()
    return jsonify(conversation_id=cid), 201


@bp.get('/announcements')
@login_required()
def announcements():
    c = conn(); u = me()
    return jsonify(items=rows(c, '''
        SELECT a.id, a.title, a.body, a.published_at, a.offering_id FROM announcements a
        WHERE a.published_at <= now() AND (a.offering_id IS NULL
              OR EXISTS (SELECT 1 FROM enrollments e WHERE e.offering_id = a.offering_id AND e.student_id = %(u)s)
              OR EXISTS (SELECT 1 FROM course_offerings o WHERE o.id = a.offering_id AND o.teacher_id = %(u)s))
        ORDER BY a.published_at DESC LIMIT 30''', {'u': u['id']}))


# ------------------------------------------------------------------ "что если"

@bp.get('/model')
def model_info():
    b = bundle()
    return jsonify(model=b['version'], threshold=b['threshold'], features=FEATURES,
                   labels={k: dict(zip(('kk', 'ru', 'en'), v)) for k, v in LABELS.items()},
                   level_medium_from=b['level_medium_from'], level_high_from=b['level_high_from'],
                   prediction_week=b['prediction_week'], metrics=b.get('metrics'))


@bp.post('/predict')
@login_required()
def predict():
    """Сценарий: взять текущие признаки студента по курсу, заменить часть своими значениями
    и вернуть риск. В базу ничего не пишется."""
    c = conn(); u = me()
    d = request.get_json(force=True, silent=True) or {}
    sid = d.get('student_id') if u['role'] != 'student' else u['id']
    oid = d.get('offering_id')
    if not sid or not oid:
        return jsonify(error='student_and_offering_required'), 400
    if u['role'] != 'student' and not teaches(c, u['id'], oid, u['role']):
        return jsonify(error='forbidden'), 403
    sem, week = latest_week(c)
    week = int(d.get('week', week))
    keys, M = fetch_features(c, sem['id'], week, oid)
    X = np.array(M, dtype=float)
    idx = [i for i, k in enumerate(keys) if k[0] == sid]
    if not idx:
        return jsonify(error='not_enrolled'), 404
    base = X[idx[0]].copy()
    over = d.get('overrides') or {}
    bad = [k for k in over if k not in FEATURES]
    if bad:
        return jsonify(error='unknown_features', features=bad), 400
    sc = base.copy()
    for k, v in over.items():
        sc[FEATURES.index(k)] = float(v)
    b = bundle()
    model = b['model']
    p0 = float(model.predict_proba(pd.DataFrame([base], columns=FEATURES))[0, 1])
    p1 = float(model.predict_proba(pd.DataFrame([sc], columns=FEATURES))[0, 1])
    return jsonify(base_risk=round(p0, 4), risk=round(p1, 4), level=level(p1, b), flagged=p1 >= b['threshold'],
                   features=dict(zip(FEATURES, map(float, sc))))


# ------------------------------------------------------------------ служебное

@bp.post('/admin/recompute')
@login_required('admin')
def admin_recompute():
    c = conn()
    return jsonify(recompute(c))
