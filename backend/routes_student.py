from flask import Blueprint, jsonify, request

from .access import conn, login_required, me
from .common import (risk_history, explanations, latest_week, weighted_grade, letter, lang_col)
from .db import rows, one, run
from .scoring import active_model_id, bundle

bp = Blueprint('student', __name__, url_prefix='/api/student')


def _courses(c, uid, sem_id):
    return rows(c, '''
        SELECT o.id AS offering_id, c.code, c.name, c.credits, o.color,
               t.first_name || ' ' || t.last_name AS teacher
        FROM enrollments e
        JOIN course_offerings o ON o.id = e.offering_id
        JOIN courses c          ON c.id = o.course_id
        LEFT JOIN teachers t    ON t.user_id = o.teacher_id
        WHERE e.student_id = %(u)s AND o.semester_id = %(s)s AND e.status = 'enrolled'
        ORDER BY c.code''', {'u': uid, 's': sem_id})


@bp.get('/courses')
@login_required('student')
def courses():
    c = conn(); uid = me()['id']
    sem, week = latest_week(c)
    mid = active_model_id(c)
    out = []
    for r in _courses(c, uid, sem['id']):
        g = weighted_grade(c, uid, r['offering_id'])
        done = float(g['weight_done'])
        pct = round(float(g['earned']) / done * 100, 1) if done else None
        risk = one(c, '''SELECT risk_probability, risk_level, week_no FROM risk_predictions
                         WHERE student_id=%(u)s AND offering_id=%(o)s AND model_id=%(m)s
                         ORDER BY week_no DESC LIMIT 1''', {'u': uid, 'o': r['offering_id'], 'm': mid})
        out.append({**r, 'current_percent': pct,
                    'points_earned': round(float(g['earned']), 2), 'weight_done': done,
                    'letter': (letter(c, r['offering_id'], pct) or {}).get('letter') if pct is not None else None,
                    'risk': risk})
    return jsonify(week=week, courses=out)


@bp.get('/curriculum')
@login_required('student')
def curriculum():
    """Return the full SDU course catalog, annotated with this student's record.

    A catalog course is returned even when it has never been offered or the
    student has never enrolled in it. Syllabus data is attached to an offering,
    so offering_id is null when no offering exists yet.
    """
    c = conn(); uid = me()['id']
    catalog = rows(c, """
        SELECT co.id AS course_id, co.code, co.name, co.credits,
               o.offering_id, o.color, o.semester, o.teacher,
               e.enrollment_status
        FROM courses co
        LEFT JOIN LATERAL (
            SELECT off.id AS offering_id, off.color, sem.name AS semester,
                   sem.start_date,
                   teach.first_name || ' ' || teach.last_name AS teacher
            FROM course_offerings off
            JOIN semesters sem ON sem.id = off.semester_id
            LEFT JOIN teachers teach ON teach.user_id = off.teacher_id
            WHERE off.course_id = co.id
            ORDER BY EXISTS (
                SELECT 1 FROM enrollments mine
                WHERE mine.offering_id = off.id AND mine.student_id = %(u)s
            ) DESC, sem.start_date DESC, off.id DESC
            LIMIT 1
        ) o ON TRUE
        LEFT JOIN LATERAL (
            SELECT en.status AS enrollment_status
            FROM enrollments en
            WHERE en.student_id = %(u)s AND en.offering_id = o.offering_id
            LIMIT 1
        ) e ON TRUE
        ORDER BY co.code
    """, {'u': uid})

    out = []
    for item in catalog:
        offering_id = item['offering_id']
        enrollment_status = item['enrollment_status']
        if enrollment_status and offering_id:
            g = weighted_grade(c, uid, offering_id)
            done = float(g['weight_done'])
            pct = round(float(g['earned']) / done * 100, 1) if done else None
            status = {
                'failed': 'Failed', 'completed': 'Passed',
                'enrolled': 'Taken', 'dropped': 'Not Taken'
            }.get(enrollment_status, 'Not Taken')
            grade_letter = (letter(c, offering_id, pct) or {}).get('letter') if pct is not None else None
            points_earned = round(float(g['earned']), 2)
            weight_done = done
        else:
            pct = grade_letter = None
            points_earned = weight_done = 0
            status = 'Not Taken'

        out.append({**item, 'status': status, 'current_percent': pct,
                    'letter': grade_letter, 'points_earned': points_earned,
                    'weight_done': weight_done,
                    'syllabus_available': offering_id is not None})
    return jsonify(courses=out, total=len(out))


@bp.get('/courses/<int:oid>/grades')
@login_required('student')
def course_grades(oid):
    c = conn(); uid = me()['id']
    if not one(c, 'SELECT 1 FROM enrollments WHERE student_id=%(u)s AND offering_id=%(o)s', {'u': uid, 'o': oid}):
        return jsonify(error='forbidden'), 403
    # студент видит только опубликованные оценки и опубликованные работы
    data = rows(c, '''
        SELECT a.id AS assessment_id, a.title, a.kind, a.due_at, a.max_score, a.weight_pct,
               cat.name AS category,
               s.status AS submission_status, s.submitted_at,
               CASE WHEN g.status = 'published' THEN g.score END       AS score,
               CASE WHEN g.status = 'published' THEN g.late_penalty END AS late_penalty,
               CASE WHEN g.status = 'published' THEN g.comment END      AS comment,
               CASE WHEN g.status = 'published' THEN g.is_excused END   AS is_excused
        FROM assessments a
        LEFT JOIN assessment_categories cat ON cat.id = a.category_id
        LEFT JOIN submissions s ON s.assessment_id = a.id AND s.student_id = %(u)s
        LEFT JOIN grades g      ON g.assessment_id = a.id AND g.student_id = %(u)s
        WHERE a.offering_id = %(o)s AND a.status = 'published'
          AND (a.visible_from IS NULL OR a.visible_from <= now())
        ORDER BY a.due_at''', {'u': uid, 'o': oid})
    g = weighted_grade(c, uid, oid)
    return jsonify(assessments=data, points_earned=float(g['earned']), weight_done=float(g['weight_done']))


@bp.get('/deadlines')
@login_required('student')
def deadlines():
    c = conn(); uid = me()['id']
    sem, _ = latest_week(c)
    return jsonify(items=rows(c, '''
        SELECT a.id AS assessment_id, o.id AS offering_id, co.code, co.name AS course, a.title, a.kind,
               a.due_at, a.weight_pct, COALESCE(s.status, 'not_submitted') AS submission_status
        FROM enrollments e
        JOIN course_offerings o ON o.id = e.offering_id AND o.semester_id = %(sem)s
        JOIN courses co ON co.id = o.course_id
        JOIN assessments a ON a.offering_id = o.id AND a.status = 'published' AND a.due_at >= now()
        LEFT JOIN submissions s ON s.assessment_id = a.id AND s.student_id = e.student_id
        WHERE e.student_id = %(u)s AND e.status = 'enrolled'
        ORDER BY a.due_at LIMIT 30''', {'u': uid, 'sem': sem['id']}))


@bp.get('/risk')
@login_required('student')
def risk():
    """Риск по каждому курсу: история по неделям, три главных фактора, диапазон баллов."""
    c = conn(); uid = me()['id']
    lang = request.args.get('lang', 'ru')
    sem, week = latest_week(c)
    mid = active_model_id(c)
    hist = risk_history(c, uid)
    by_off = {}
    for h in hist:
        by_off.setdefault(h['offering_id'], []).append(h)
    pred_ids = {(r['offering_id']): r['id'] for r in rows(c, '''
        SELECT DISTINCT ON (offering_id) id, offering_id FROM risk_predictions
        WHERE student_id=%(u)s AND model_id=%(m)s ORDER BY offering_id, week_no DESC''', {'u': uid, 'm': mid})}
    ex = explanations(c, pred_ids.values(), lang)
    out = []
    for r in _courses(c, uid, sem['id']):
        h = by_off.get(r['offering_id'], [])
        out.append({'offering_id': r['offering_id'], 'code': r['code'], 'name': r['name'],
                    'latest': h[-1] if h else None,
                    'history': h,
                    'factors': ex.get(pred_ids.get(r['offering_id']), [])})
    b = bundle()
    return jsonify(week=week, first_week=4, threshold=b['threshold'],
                   level_medium_from=b['level_medium_from'], level_high_from=b['level_high_from'],
                   courses=out)


@bp.get('/overall-risk')
@login_required('student')
def overall_risk():
    c = conn(); uid = me()['id']
    return jsonify(items=rows(c, '''SELECT week_no, risk_probability, risk_level, method
                                    FROM student_risk_overall WHERE student_id=%(u)s ORDER BY week_no''', {'u': uid}))


@bp.get('/attendance')
@login_required('student')
def attendance():
    c = conn(); uid = me()['id']
    sem, _ = latest_week(c)
    summary = rows(c, '''
        SELECT o.id AS offering_id, co.code, co.name, o.max_absence_pct,
               COUNT(*) FILTER (WHERE a.status = 'present')  AS present,
               COUNT(*) FILTER (WHERE a.status = 'late')     AS late,
               COUNT(*) FILTER (WHERE a.status = 'absent')   AS absent,
               COUNT(*) FILTER (WHERE a.status = 'excused')  AS excused,
               COUNT(*)                                       AS marked
        FROM enrollments e
        JOIN course_offerings o ON o.id = e.offering_id AND o.semester_id = %(sem)s
        JOIN courses co ON co.id = o.course_id
        LEFT JOIN class_meetings m ON m.offering_id = o.id AND m.meeting_date <= CURRENT_DATE
        LEFT JOIN attendance a ON a.meeting_id = m.id AND a.student_id = e.student_id
        WHERE e.student_id = %(u)s AND e.status = 'enrolled'
        GROUP BY o.id, co.code, co.name, o.max_absence_pct ORDER BY co.code''', {'u': uid, 'sem': sem['id']})
    for s in summary:
        marked = int(s['marked'])
        s['absence_pct'] = round(int(s['absent']) / marked * 100, 1) if marked else 0
    return jsonify(items=summary)


@bp.get('/attendance/<int:oid>')
@login_required('student')
def attendance_detail(oid):
    c = conn(); uid = me()['id']
    return jsonify(items=rows(c, '''
        SELECT m.id AS meeting_id, m.meeting_date, m.start_time, m.lesson_type, m.topic,
               a.status, a.excuse_document_id, d.status AS excuse_status
        FROM class_meetings m
        LEFT JOIN attendance a ON a.meeting_id = m.id AND a.student_id = %(u)s
        LEFT JOIN excuse_documents d ON d.meeting_id = m.id AND d.student_id = %(u)s
        WHERE m.offering_id = %(o)s AND m.meeting_date <= CURRENT_DATE
          AND EXISTS (SELECT 1 FROM enrollments e WHERE e.student_id = %(u)s AND e.offering_id = %(o)s)
        ORDER BY m.meeting_date DESC''', {'u': uid, 'o': oid}))


@bp.post('/excuse')
@login_required('student')
def excuse():
    c = conn(); uid = me()['id']
    d = request.get_json(force=True)
    m = one(c, '''SELECT m.id, m.offering_id FROM class_meetings m
                  JOIN enrollments e ON e.offering_id = m.offering_id AND e.student_id = %(u)s
                  WHERE m.id = %(m)s''', {'u': uid, 'm': d.get('meeting_id')})
    if not m or not d.get('file_url'):
        return jsonify(error='bad_request'), 400
    run(c, '''INSERT INTO excuse_documents (student_id, meeting_id, file_url, status, uploaded_at)
              VALUES (%(u)s, %(m)s, %(f)s, 'pending', now())
              ON CONFLICT (student_id, meeting_id) DO UPDATE SET file_url=EXCLUDED.file_url,
                   status='pending', uploaded_at=now(), reviewed_by=NULL, reviewed_at=NULL''',
        {'u': uid, 'm': m['id'], 'f': d['file_url']})
    t = one(c, 'SELECT teacher_id FROM course_offerings WHERE id=%(o)s', {'o': m['offering_id']})
    if t and t['teacher_id']:
        run(c, '''INSERT INTO notifications (user_id, type, title, link) VALUES (%(t)s,'excuse_pending',
                  'Новая справка на проверку', %(l)s)''',
            {'t': t['teacher_id'], 'l': f"/teacher/courses/{m['offering_id']}/attendance"})
    c.commit()
    return jsonify(ok=True)


@bp.get('/feedback')
@login_required('student')
def feedback_open():
    c = conn(); uid = me()['id']
    return jsonify(items=rows(c, '''
        SELECT f.id AS survey_id, o.id AS offering_id, co.code, co.name, f.closes_at,
               EXISTS (SELECT 1 FROM feedback_participation p WHERE p.survey_id = f.id AND p.student_id = e.student_id) AS answered
        FROM enrollments e
        JOIN feedback_surveys f ON f.offering_id = e.offering_id AND f.opens_at <= now() AND f.closes_at >= now()
        JOIN course_offerings o ON o.id = e.offering_id
        JOIN courses co ON co.id = o.course_id
        WHERE e.student_id = %(u)s AND e.status = 'enrolled' ''', {'u': uid}))


@bp.post('/feedback/<int:survey_id>')
@login_required('student')
def feedback_submit(survey_id):
    """Анонимно: ответ пишется без student_id, а факт участия в отдельную таблицу.
    Связи между ними нет, поэтому ответ нельзя вернуть студенту."""
    c = conn(); uid = me()['id']
    d = request.get_json(force=True)
    s = one(c, '''SELECT f.id FROM feedback_surveys f
                  JOIN enrollments e ON e.offering_id = f.offering_id AND e.student_id = %(u)s
                  WHERE f.id = %(s)s AND f.opens_at <= now() AND f.closes_at >= now()''',
            {'u': uid, 's': survey_id})
    if not s:
        return jsonify(error='survey_closed_or_forbidden'), 403
    keys = ['rating_content', 'rating_teaching', 'rating_materials', 'rating_assessment', 'rating_availability']
    try:
        vals = [int(d[k]) for k in keys]
    except (KeyError, TypeError, ValueError):
        return jsonify(error='ratings_required'), 400
    if any(v < 1 or v > 5 for v in vals):
        return jsonify(error='ratings_1_5'), 400
    if one(c, 'SELECT 1 FROM feedback_participation WHERE survey_id=%(s)s AND student_id=%(u)s', {'s': survey_id, 'u': uid}):
        return jsonify(error='already_answered'), 409
    run(c, '''INSERT INTO feedback_participation (survey_id, student_id) VALUES (%(s)s, %(u)s)''', {'s': survey_id, 'u': uid})
    run(c, f'''INSERT INTO feedback_responses (survey_id, {', '.join(keys)}, comment, answered_on)
               VALUES (%(s)s, {', '.join('%(' + k + ')s' for k in keys)}, %(cm)s, CURRENT_DATE)''',
        {'s': survey_id, **dict(zip(keys, vals)), 'cm': (d.get('comment') or '')[:2000] or None})
    c.commit()
    return jsonify(ok=True)


@bp.post('/submissions')
@login_required('student')
def submit_work():
    """Сдать работу. Сроки проверяет сервер: после due_at статус становится late."""
    c = conn(); uid = me()['id']
    d = request.get_json(force=True, silent=True) or {}
    a = one(c, '''SELECT a.id, a.offering_id, a.due_at, a.title, o.teacher_id FROM assessments a
                  JOIN course_offerings o ON o.id = a.offering_id
                  JOIN enrollments e ON e.offering_id = a.offering_id AND e.student_id = %(u)s
                  WHERE a.id = %(a)s AND a.status = 'published'
                    AND (a.visible_from IS NULL OR a.visible_from <= now())''',
            {'u': uid, 'a': d.get('assessment_id')})
    if not a:
        return jsonify(error='not_found_or_forbidden'), 403
    if not (d.get('file_url') or (d.get('text_answer') or '').strip()):
        return jsonify(error='empty_submission'), 400
    cur = one(c, 'SELECT id, status FROM submissions WHERE assessment_id=%(a)s AND student_id=%(u)s AND attempt_no=1',
              {'a': a['id'], 'u': uid})
    if cur and cur['status'] == 'graded':
        return jsonify(error='already_graded'), 409
    late = one(c, 'SELECT now() > %(d)s::timestamptz AS late', {'d': a['due_at']})['late']
    status = 'late' if late else 'submitted'
    params = {'a': a['id'], 'u': uid, 's': status, 'f': d.get('file_url'), 't': d.get('text_answer')}
    if cur:
        run(c, '''UPDATE submissions SET status=%(s)s, file_url=%(f)s, text_answer=%(t)s, submitted_at=now()
                  WHERE id=%(i)s''', {**params, 'i': cur['id']})
    else:
        run(c, '''INSERT INTO submissions (assessment_id, student_id, status, file_url, text_answer, attempt_no, submitted_at)
                  VALUES (%(a)s,%(u)s,%(s)s,%(f)s,%(t)s,1,now())''', params)
    if a['teacher_id']:
        run(c, "INSERT INTO notifications (user_id, type, title, link) VALUES (%(t)s,'submission_new',%(ti)s,%(l)s)",
            {'t': a['teacher_id'], 'ti': f"Новая работа: {a['title']}", 'l': f"/teacher/assessments/{a['id']}"})
    c.commit()
    return jsonify(status=status), 201
