"""Отчёты преподавателя в CSV (задача E).

    GET /api/teacher/reports/<kind>?offering_id=<id>            -> файл CSV
    GET /api/teacher/reports/<kind>?offering_id=<id>&format=json -> {columns, rows} для предпросмотра

kind: course-performance | attendance-summary | gradebook | student-risk

Отчёт строится только по курсу, который преподаватель ведёт (админ видит все).
Файл в UTF-8 с BOM, чтобы Excel правильно открыл кириллицу.
"""
import csv
import io

from flask import Blueprint, Response, jsonify, request

from .access import conn, login_required, me, teaches
from .common import latest_week, lang_col
from .db import rows, one
from .scoring import active_model_id

bp = Blueprint('reports', __name__, url_prefix='/api/teacher')
ROLES = ('teacher', 'admin')
KINDS = ('course-performance', 'attendance-summary', 'gradebook', 'student-risk')


def _f(v, nd=1):
    return None if v is None else round(float(v), nd)


def _students(c, oid):
    return rows(c, '''
        SELECT st.user_id, u.login_id, st.last_name, st.first_name, sg.code AS group_code
        FROM enrollments e JOIN students st ON st.user_id = e.student_id
        JOIN users u ON u.id = st.user_id LEFT JOIN student_groups sg ON sg.id = st.group_id
        WHERE e.offering_id = %(o)s AND e.status = 'enrolled'
        ORDER BY st.last_name, st.first_name''', {'o': oid})


def _percent(c, oid):
    """Текущий процент по опубликованным оценкам: {student_id: (percent, вес оценённых работ)}."""
    out = {}
    for r in rows(c, '''
            SELECT g.student_id, SUM(g.score / a.max_score * a.weight_pct) AS earned, SUM(a.weight_pct) AS done,
                   COUNT(*) AS items
            FROM grades g JOIN assessments a ON a.id = g.assessment_id
            WHERE a.offering_id = %(o)s AND g.status = 'published' AND g.score IS NOT NULL
            GROUP BY g.student_id''', {'o': oid}):
        done = float(r['done'] or 0)
        out[r['student_id']] = (round(float(r['earned']) / done * 100, 1) if done else None, round(done, 1), int(r['items']))
    return out


def _letters(c, oid):
    lv = rows(c, '''SELECT l.letter, l.min_percent FROM course_offerings o
                    JOIN grade_scale_levels l ON l.scale_id = o.grade_scale_id
                    WHERE o.id = %(o)s ORDER BY l.min_percent DESC''', {'o': oid})
    def letter(p):
        if p is None:
            return None
        return next((x['letter'] for x in lv if float(x['min_percent']) <= p), None)
    return letter


def _attendance(c, oid):
    return {r['student_id']: r for r in rows(c, '''
        SELECT a.student_id,
               COUNT(*) FILTER (WHERE a.status = 'present') AS present,
               COUNT(*) FILTER (WHERE a.status = 'late')    AS late,
               COUNT(*) FILTER (WHERE a.status = 'absent')  AS absent,
               COUNT(*) FILTER (WHERE a.status = 'excused') AS excused,
               COUNT(*) AS marked
        FROM attendance a JOIN class_meetings m ON m.id = a.meeting_id
        WHERE m.offering_id = %(o)s AND m.meeting_date <= CURRENT_DATE
        GROUP BY a.student_id''', {'o': oid})}


def _risk(c, oid, week):
    mid = active_model_id(c)
    return {r['student_id']: r for r in rows(c, '''
        SELECT p.id, p.student_id, p.risk_probability, p.risk_level, p.predicted_score_low, p.predicted_score_high,
               pp.risk_probability AS prev_risk,
               (SELECT MAX(i.created_at) FROM interventions i
                 WHERE i.student_id = p.student_id AND i.offering_id = p.offering_id) AS last_contact
        FROM risk_predictions p
        LEFT JOIN risk_predictions pp ON pp.student_id = p.student_id AND pp.offering_id = p.offering_id
             AND pp.model_id = p.model_id AND pp.week_no = p.week_no - 1
        WHERE p.offering_id = %(o)s AND p.model_id = %(m)s AND p.week_no = %(w)s''', {'o': oid, 'm': mid, 'w': week})}


def course_performance(c, oid, week, lang):
    pct, att, risk, letter = _percent(c, oid), _attendance(c, oid), _risk(c, oid, week), _letters(c, oid)
    cols = ['student_id', 'last_name', 'first_name', 'group', 'current_percent', 'letter', 'graded_weight_pct',
            'graded_items', 'absence_pct', 'risk_level', 'risk_probability']
    out = []
    for s in _students(c, oid):
        p, done, items = pct.get(s['user_id'], (None, 0, 0))
        a = att.get(s['user_id'])
        r = risk.get(s['user_id'])
        marked = int(a['marked']) if a else 0
        out.append([s['login_id'], s['last_name'], s['first_name'], s['group_code'], p, letter(p), done, items,
                    round(int(a['absent']) / marked * 100, 1) if marked else None,
                    r['risk_level'] if r else None, _f(r['risk_probability'], 3) if r else None])
    return cols, out


def attendance_summary(c, oid, week, lang):
    limit = one(c, 'SELECT max_absence_pct FROM course_offerings WHERE id = %(o)s', {'o': oid})['max_absence_pct']
    limit = float(limit)
    att = _attendance(c, oid)
    cols = ['student_id', 'last_name', 'first_name', 'group', 'present', 'late', 'absent', 'excused',
            'marked_lessons', 'absence_pct', 'absence_limit_pct', 'over_limit']
    out = []
    for s in _students(c, oid):
        a = att.get(s['user_id'])
        n = lambda k: int(a[k]) if a else 0
        pct = round(n('absent') / n('marked') * 100, 1) if n('marked') else 0.0
        out.append([s['login_id'], s['last_name'], s['first_name'], s['group_code'], n('present'), n('late'),
                    n('absent'), n('excused'), n('marked'), pct, limit, 'yes' if pct > limit else 'no'])
    return cols, out


def gradebook(c, oid, week, lang):
    asm = rows(c, '''SELECT id, title, max_score, weight_pct, status FROM assessments
                     WHERE offering_id = %(o)s ORDER BY due_at, id''', {'o': oid})
    gr = {}
    for g in rows(c, '''SELECT g.assessment_id, g.student_id, g.score, g.status FROM grades g
                        JOIN assessments a ON a.id = g.assessment_id WHERE a.offering_id = %(o)s''', {'o': oid}):
        gr[(g['student_id'], g['assessment_id'])] = g
    pct, letter = _percent(c, oid), _letters(c, oid)
    cols = ['student_id', 'last_name', 'first_name', 'group'] + \
           [f"{a['title']} (max {float(a['max_score']):g}, {float(a['weight_pct']):g}%)" for a in asm] + \
           ['current_percent', 'letter', 'unpublished_grades']
    out = []
    for s in _students(c, oid):
        row = [s['login_id'], s['last_name'], s['first_name'], s['group_code']]
        drafts = 0
        for a in asm:
            g = gr.get((s['user_id'], a['id']))
            row.append(_f(g['score'], 2) if g and g['score'] is not None else None)
            if g and g['score'] is not None and g['status'] != 'published':
                drafts += 1
        p = pct.get(s['user_id'], (None, 0, 0))[0]
        out.append(row + [p, letter(p), drafts])
    return cols, out


def student_risk(c, oid, week, lang):
    risk = _risk(c, oid, week)
    ids = [r['id'] for r in risk.values()]
    factors = {}
    if ids:
        col = lang_col(lang)
        for r in rows(c, f'''SELECT prediction_id, {col} AS text FROM prediction_explanations
                             WHERE prediction_id = ANY(%(ids)s) AND impact > 0
                             ORDER BY prediction_id, impact DESC''', {'ids': ids}):
            factors.setdefault(r['prediction_id'], []).append(r['text'])
    cols = ['student_id', 'last_name', 'first_name', 'group', 'week', 'risk_level', 'risk_probability',
            'change_vs_last_week', 'predicted_score_low', 'predicted_score_high', 'main_factors', 'last_contact']
    out = []
    for s in _students(c, oid):
        r = risk.get(s['user_id'])
        if not r:
            out.append([s['login_id'], s['last_name'], s['first_name'], s['group_code'], week] + [None] * 7)
            continue
        change = None if r['prev_risk'] is None else round(float(r['risk_probability']) - float(r['prev_risk']), 3)
        lc = r['last_contact']
        out.append([s['login_id'], s['last_name'], s['first_name'], s['group_code'], week, r['risk_level'],
                    _f(r['risk_probability'], 3), change, _f(r['predicted_score_low']), _f(r['predicted_score_high']),
                    '; '.join(t for t in factors.get(r['id'], [])[:3] if t), str(lc)[:10] if lc else None])
    order = {'high': 0, 'medium': 1, 'low': 2, None: 3}
    out.sort(key=lambda x: (order.get(x[5], 3), -(x[6] or 0)))
    return cols, out


BUILDERS = {'course-performance': course_performance, 'attendance-summary': attendance_summary,
            'gradebook': gradebook, 'student-risk': student_risk}


@bp.get('/reports/<kind>')
@login_required(*ROLES)
def report(kind):
    if kind not in BUILDERS:
        return jsonify(error='unknown_report', kinds=list(KINDS)), 404
    try:
        oid = int(request.args.get('offering_id', ''))
    except ValueError:
        return jsonify(error='offering_id_required'), 400
    c = conn(); u = me()
    info = one(c, '''SELECT co.code, co.name FROM course_offerings o JOIN courses co ON co.id = o.course_id
                     WHERE o.id = %(o)s''', {'o': oid})
    if not info:
        return jsonify(error='no_course'), 404
    if not teaches(c, u['id'], oid, u['role']):
        return jsonify(error='forbidden'), 403
    _, week = latest_week(c)
    cols, data = BUILDERS[kind](c, oid, week, request.args.get('lang', 'en'))
    if request.args.get('format') == 'json':
        return jsonify(kind=kind, course=info, week=week, columns=cols, rows=data, total=len(data))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(cols)
    for r in data:
        w.writerow(['' if v is None else v for v in r])
    name = f"{kind}_{info['code']}_week{week}.csv".replace(' ', '_')
    return Response('﻿' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})
