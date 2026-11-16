"""Импорт оценок из CSV (задача G, ответ на риск R8).

Порядок работы преподавателя:
  1) скачать шаблон работы:     GET  /api/teacher/assessments/<id>/grades-template
  2) заполнить колонку score и загрузить файл на проверку (ничего не пишется):
                                 POST /api/teacher/assessments/<id>/grades-import   dry_run=1
  3) если ошибок нет, применить: POST /api/teacher/assessments/<id>/grades-import   dry_run=0

Правила:
- студент ищется по ID портала (users.login_id), а не по внутреннему номеру;
- неизвестный ID, студент не с этого курса, повтор в файле, пустой или нечисловой балл,
  балл вне диапазона 0..max_score считаются ошибками строки;
- если в файле есть хоть одна ошибка, не записывается НИЧЕГО (всё или ничего),
  пока преподаватель явно не выберет skip_invalid=1;
- новые оценки сохраняются черновиками; публикация остаётся отдельным действием;
- изменение уже выставленной оценки требует reason и попадает в grade_audit_log.
"""
import csv
import io
import math

from flask import Blueprint, Response, jsonify, request

from .access import conn, login_required, me, teaches
from .db import rows, one, run
from .routes_teacher import _audit_by_trigger, _audit_ctx, _audit_manual

bp = Blueprint('grade_import', __name__, url_prefix='/api/teacher')
ROLES = ('teacher', 'admin')
MAX_BYTES = 1_000_000
MAX_ROWS = 2000
ID_COLS = ('student_id', 'login_id', 'id', 'student id', 'student')
SCORE_COLS = ('score', 'points', 'grade', 'mark')
COMMENT_COLS = ('comment', 'feedback', 'note')


def _assessment(c, aid):
    return one(c, '''SELECT a.id, a.offering_id, a.title, a.max_score, co.code
                     FROM assessments a JOIN course_offerings o ON o.id = a.offering_id
                     JOIN courses co ON co.id = o.course_id WHERE a.id = %(a)s''', {'a': aid})


def _read_upload():
    """Текст CSV из multipart-файла (поле file) или из JSON {"csv": "..."}. Возвращает (text, error)."""
    f = request.files.get('file')
    if f is not None:
        raw = f.read(MAX_BYTES + 1)
    else:
        d = request.get_json(silent=True) or {}
        raw = (d.get('csv') or '').encode('utf-8')
    if not raw.strip():
        return None, 'empty_file'
    if len(raw) > MAX_BYTES:
        return None, 'file_too_large'
    for enc in ('utf-8-sig', 'cp1251'):          # Excel на русской Windows сохраняет в cp1251
        try:
            return raw.decode(enc), None
        except UnicodeDecodeError:
            continue
    return None, 'bad_encoding'


def _flag(name, default=False):
    d = request.get_json(silent=True) or {}
    v = request.form.get(name, request.args.get(name, d.get(name)))
    if v is None:
        return default
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


def _text_param(name):
    d = request.get_json(silent=True) or {}
    return (request.form.get(name) or request.args.get(name) or d.get(name) or '').strip()


def parse_csv(text):
    """Разобрать CSV. Возвращает (строки, error). Разделитель: запятая, точка с запятой или табуляция."""
    first = text.lstrip('﻿').splitlines()[0] if text.strip() else ''
    delim = max(',;\t', key=first.count) if first else ','
    data = list(csv.reader(io.StringIO(text.lstrip('﻿')), delimiter=delim))
    data = [r for r in data if any((x or '').strip() for x in r)]
    if not data:
        return None, {'error': 'empty_file'}
    head = [(h or '').strip().lower() for h in data[0]]
    id_i = next((head.index(h) for h in ID_COLS if h in head), None)
    sc_i = next((head.index(h) for h in SCORE_COLS if h in head), None)
    cm_i = next((head.index(h) for h in COMMENT_COLS if h in head), None)
    if id_i is None or sc_i is None:
        return None, {'error': 'bad_header', 'found': data[0],
                      'hint': 'The first line must contain the columns student_id and score'}
    if len(data) - 1 > MAX_ROWS:
        return None, {'error': 'too_many_rows', 'max': MAX_ROWS}
    out = []
    for n, r in enumerate(data[1:], start=2):       # n = номер строки в файле, заголовок = 1
        get = lambda i: (r[i].strip() if i is not None and i < len(r) and r[i] is not None else '')
        out.append({'line': n, 'student_id': get(id_i), 'raw_score': get(sc_i), 'comment': get(cm_i) or None})
    return out, None


def to_score(raw):
    """'17,5' -> 17.5. None, если это не обычное число."""
    try:
        v = float(str(raw).replace(',', '.').replace(' ', ''))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def check_rows(c, a, parsed):
    """Сверить строки файла с базой. Ничего не пишет."""
    enrolled = {str(r['login_id']): r for r in rows(c, '''
        SELECT u.login_id, st.user_id, st.first_name, st.last_name, e.status
        FROM enrollments e JOIN students st ON st.user_id = e.student_id
        JOIN users u ON u.id = st.user_id WHERE e.offering_id = %(o)s''', {'o': a['offering_id']})}
    known = {str(r['login_id']) for r in rows(c, "SELECT login_id FROM users WHERE role = 'student'")}
    current = {r['student_id']: r for r in rows(
        c, 'SELECT id, student_id, score, status FROM grades WHERE assessment_id = %(a)s', {'a': a['id']})}
    max_score = float(a['max_score'])
    seen, out = set(), []
    for p in parsed:
        row = {'line': p['line'], 'student_id': p['student_id'], 'name': None, 'score': None,
               'old_score': None, 'action': 'error', 'error': None, 'comment': p['comment']}
        sid = p['student_id']
        st = enrolled.get(sid)
        if st:
            row['name'] = f"{st['first_name']} {st['last_name']}"
        score = to_score(p['raw_score'])
        if not sid:
            row['error'] = 'missing_student_id'
        elif sid not in known:
            row['error'] = 'unknown_student'
        elif not st or st['status'] != 'enrolled':
            row['error'] = 'not_enrolled'
        elif sid in seen:
            row['error'] = 'duplicate_in_file'
        elif p['raw_score'] == '':
            row['error'] = 'missing_score'
        elif score is None:
            row['error'] = 'bad_score'
        elif not (0 <= score <= max_score):
            row['error'] = 'score_out_of_range'
        else:
            row['score'] = round(score, 2)
            old = current.get(st['user_id'])
            row['_user_id'] = st['user_id']
            if old is None:
                row['action'] = 'new'
            else:
                row['_grade'] = old
                row['old_score'] = float(old['score']) if old['score'] is not None else None
                row['action'] = 'unchanged' if row['old_score'] == row['score'] else 'update'
        if sid:
            seen.add(sid)
        out.append(row)
    return out


def summary(checked):
    k = lambda name: sum(1 for r in checked if r['action'] == name)
    return {'total': len(checked), 'new': k('new'), 'update': k('update'),
            'unchanged': k('unchanged'), 'errors': k('error')}


def public(checked):
    return [{k: v for k, v in r.items() if not k.startswith('_')} for r in checked]


@bp.get('/assessments/<int:aid>/grades-template')
@login_required(*ROLES)
def template(aid):
    """CSV со всеми студентами курса и текущими баллами: его можно заполнить и загрузить обратно."""
    c = conn(); u = me()
    a = _assessment(c, aid)
    if not a:
        return jsonify(error='no_assessment'), 404
    if not teaches(c, u['id'], a['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    data = rows(c, '''
        SELECT u.login_id, st.last_name, st.first_name, g.score
        FROM enrollments e JOIN students st ON st.user_id = e.student_id JOIN users u ON u.id = st.user_id
        LEFT JOIN grades g ON g.student_id = st.user_id AND g.assessment_id = %(a)s
        WHERE e.offering_id = %(o)s AND e.status = 'enrolled'
        ORDER BY st.last_name, st.first_name''', {'a': aid, 'o': a['offering_id']})
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['student_id', 'last_name', 'first_name', 'score', 'comment'])
    for r in data:
        w.writerow([r['login_id'], r['last_name'], r['first_name'], '' if r['score'] is None else float(r['score']), ''])
    name = f"grades_{a['code']}_{aid}.csv".replace(' ', '_')
    return Response('﻿' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})


@bp.post('/assessments/<int:aid>/grades-import')
@login_required(*ROLES)
def grades_import(aid):
    c = conn(); u = me()
    a = _assessment(c, aid)
    if not a:
        return jsonify(error='no_assessment'), 404
    if not teaches(c, u['id'], a['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    text, err = _read_upload()
    if err:
        return jsonify(error=err), 400
    parsed, err = parse_csv(text)
    if err:
        return jsonify(**err), 400
    dry_run = _flag('dry_run', True)
    skip_invalid = _flag('skip_invalid', False)
    reason = _text_param('reason')

    checked = check_rows(c, a, parsed)
    s = summary(checked)
    base = dict(assessment={'id': a['id'], 'title': a['title'], 'max_score': float(a['max_score'])},
                summary=s, rows=public(checked), needs_reason=s['update'] > 0)
    if dry_run:
        c.rollback()
        return jsonify(dry_run=True, applied=False, can_apply=s['errors'] == 0 and (s['new'] + s['update']) > 0, **base)
    if s['errors'] and not skip_invalid:
        c.rollback()
        return jsonify(error='has_errors', dry_run=False, applied=False, **base), 400
    if s['update'] and not reason:
        c.rollback()
        return jsonify(error='reason_required', dry_run=False, applied=False, **base), 400

    via_trigger = _audit_by_trigger(c)
    teacher_id = u['id'] if one(c, 'SELECT 1 FROM teachers WHERE user_id = %(u)s', {'u': u['id']}) else None
    written = 0
    try:
        for r in checked:
            if r['action'] == 'new':
                _audit_ctx(c, u['id'], 'csv import')
                gid = run(c, '''INSERT INTO grades (assessment_id, student_id, score, late_penalty, is_excused, status,
                                                    comment, graded_by, graded_at)
                                VALUES (%(a)s,%(s)s,%(sc)s,0,false,'draft',%(cm)s,%(t)s,now()) RETURNING id''',
                          {'a': a['id'], 's': r['_user_id'], 'sc': r['score'], 'cm': r['comment'], 't': teacher_id})[0]['id']
                if not via_trigger:
                    _audit_manual(c, gid, u['id'], None, r['score'], None, 'draft', 'csv import')
                written += 1
            elif r['action'] == 'update':
                g = r['_grade']
                why = f'csv import: {reason}'
                _audit_ctx(c, u['id'], why)
                run(c, '''UPDATE grades SET score = %(sc)s, comment = COALESCE(%(cm)s, comment),
                                            graded_by = COALESCE(%(t)s, graded_by), graded_at = now()
                          WHERE id = %(id)s''', {'sc': r['score'], 'cm': r['comment'], 't': teacher_id, 'id': g['id']})
                if not via_trigger:
                    _audit_manual(c, g['id'], u['id'], g['score'], r['score'], g['status'], g['status'], why)
                written += 1
        c.commit()
    except Exception:
        c.rollback()                                   # файл не должен оставить половину оценок
        raise
    return jsonify(dry_run=False, applied=True, written=written, skipped_errors=s['errors'], **base)
