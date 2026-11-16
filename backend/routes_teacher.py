from flask import Blueprint, jsonify, request

from .access import conn, login_required, me, teaches, can_see_student, advises
from .common import risk_history, explanations, latest_week, lang_col
from .db import rows, one, run
from .scoring import active_model_id, bundle

bp = Blueprint('teacher', __name__, url_prefix='/api/teacher')
ROLES = ('teacher', 'admin')
MIN_ANON = 5         # меньше пяти ответов отзыв показывать нельзя: автора можно угадать
FOLLOWUP_DAYS = 14   # высокий риск без контакта дольше этого срока попадает в очередь куратора


def _audit_by_trigger(c) -> bool:
    """True, если триггер grades сам пишет причину (патч docs/patch_audit_trigger.sql применён)."""
    return bool(one(c, "SELECT 1 FROM pg_proc WHERE proname = 'log_grade_change' "
                       "AND position('app.reason' in prosrc) > 0"))


def _audit_ctx(c, user_id, reason):
    """Передать в триггер, кто и почему меняет оценку (действует до конца транзакции)."""
    run(c, "SELECT set_config('app.reason', %(r)s, true), set_config('app.user_id', %(u)s, true)",
        {'r': reason or '', 'u': str(user_id)})


def _audit_manual(c, gid, user_id, old_score, new_score, old_status, new_status, reason):
    """Запись аудита вручную, если триггер без патча: он пишет строку без причины,
    поэтому это вторая строка. Применение патча убирает дубль."""
    run(c, '''INSERT INTO grade_audit_log (grade_id, changed_by, old_score, new_score, old_status, new_status, reason)
              VALUES (%(g)s,%(u)s,%(os)s,%(ns)s,%(ost)s,%(nst)s,%(r)s)''',
        {'g': gid, 'u': user_id, 'os': old_score, 'ns': new_score, 'ost': old_status, 'nst': new_status, 'r': reason})


def _guard(oid):
    u = me()
    return teaches(conn(), u['id'], oid, u['role'])


@bp.get('/courses')
@login_required(*ROLES)
def courses():
    c = conn(); u = me()
    sem, week = latest_week(c)
    mid = active_model_id(c)
    data = rows(c, '''
        SELECT o.id AS offering_id, co.code, co.name, co.credits, o.color,
               (SELECT COUNT(*) FROM enrollments e WHERE e.offering_id = o.id AND e.status = 'enrolled') AS students,
               s.low_count, s.medium_count, s.high_count, s.avg_risk, s.week_no
        FROM course_offerings o
        JOIN courses co ON co.id = o.course_id
        LEFT JOIN course_risk_snapshots s ON s.offering_id = o.id AND s.week_no = %(w)s
        WHERE o.semester_id = %(sem)s
          AND (%(adm)s OR o.teacher_id = %(u)s OR EXISTS
               (SELECT 1 FROM offering_staff f WHERE f.offering_id = o.id AND f.teacher_id = %(u)s))
        ORDER BY co.code''', {'sem': sem['id'], 'w': week, 'u': u['id'], 'adm': u['role'] == 'admin'})
    return jsonify(week=week, courses=data)


@bp.get('/courses/<int:oid>/insights')
@login_required(*ROLES)
def insights(oid):
    """Class Insights: динамика курса, студенты по убыванию риска, что изменилось за неделю."""
    if not _guard(oid):
        return jsonify(error='forbidden'), 403
    c = conn()
    lang = request.args.get('lang', 'ru')
    sem, cur_week = latest_week(c)
    week = int(request.args.get('week', cur_week))
    mid = active_model_id(c)
    trend = rows(c, '''SELECT week_no, low_count, medium_count, high_count, avg_risk
                       FROM course_risk_snapshots WHERE offering_id=%(o)s AND week_no >= 4 ORDER BY week_no''', {'o': oid})
    students = rows(c, '''
        SELECT p.id AS prediction_id, p.student_id, st.first_name, st.last_name, st.group_id,
               p.risk_probability, p.risk_level, p.predicted_score_low, p.predicted_score_high,
               pp.risk_probability AS prev_risk, pp.risk_level AS prev_level,
               (SELECT MAX(i.created_at) FROM interventions i
                 WHERE i.student_id = p.student_id AND i.offering_id = p.offering_id) AS last_contact
        FROM risk_predictions p
        JOIN students st ON st.user_id = p.student_id
        LEFT JOIN risk_predictions pp ON pp.student_id = p.student_id AND pp.offering_id = p.offering_id
             AND pp.model_id = p.model_id AND pp.week_no = p.week_no - 1
        WHERE p.offering_id = %(o)s AND p.model_id = %(m)s AND p.week_no = %(w)s
        ORDER BY p.risk_probability DESC''', {'o': oid, 'm': mid, 'w': week})
    ex = explanations(c, [s['prediction_id'] for s in students], lang)
    order = {'low': 0, 'medium': 1, 'high': 2}
    moved_up = 0
    for s in students:
        s['factors'] = ex.get(s['prediction_id'], [])
        pr = s['prev_risk']
        s['change'] = round(float(s['risk_probability']) - float(pr), 4) if pr is not None else None
        if s['prev_level'] and order[s['risk_level']] > order[s['prev_level']]:
            moved_up += 1
    b = bundle()
    return jsonify(week=week, first_week=4, threshold=b['threshold'], trend=trend,
                   moved_up=moved_up, students=students)


@bp.get('/students/<int:sid>')
@login_required(*ROLES)
def student_profile(sid):
    c = conn(); u = me()
    if not can_see_student(c, u['id'], sid, u['role']):
        return jsonify(error='forbidden'), 403
    lang = request.args.get('lang', 'ru')
    sem, week = latest_week(c)
    mid = active_model_id(c)
    prof = one(c, '''SELECT user_id AS id, first_name, last_name, email, group_id, program_id, admission_year, status
                     FROM students WHERE user_id=%(s)s''', {'s': sid})
    # преподаватель видит риск только по тем курсам, которые ведёт; эдвайзер и админ по всем
    full = u['role'] == 'admin' or advises(c, u['id'], sid)
    cs = rows(c, '''
        SELECT o.id AS offering_id, co.code, co.name FROM enrollments e
        JOIN course_offerings o ON o.id = e.offering_id AND o.semester_id = %(sem)s
        JOIN courses co ON co.id = o.course_id
        WHERE e.student_id = %(s)s AND e.status = 'enrolled' ORDER BY co.code''', {'s': sid, 'sem': sem['id']})
    if not full:
        cs = [x for x in cs if teaches(c, u['id'], x['offering_id'], u['role'])]
    hist = risk_history(c, sid)
    last = {r['offering_id']: r['id'] for r in rows(c, '''
        SELECT DISTINCT ON (offering_id) id, offering_id FROM risk_predictions
        WHERE student_id=%(s)s AND model_id=%(m)s ORDER BY offering_id, week_no DESC''', {'s': sid, 'm': mid})}
    ex = explanations(c, last.values(), lang)
    for x in cs:
        h = [r for r in hist if r['offering_id'] == x['offering_id']]
        x['history'] = h
        x['latest'] = h[-1] if h else None
        x['factors'] = ex.get(last.get(x['offering_id']), [])
        x['attendance'] = one(c, '''
            SELECT COUNT(*) FILTER (WHERE a.status='absent') AS absent, COUNT(*) AS marked
            FROM class_meetings m LEFT JOIN attendance a ON a.meeting_id = m.id AND a.student_id = %(s)s
            WHERE m.offering_id = %(o)s AND m.meeting_date <= CURRENT_DATE AND a.id IS NOT NULL''',
                              {'s': sid, 'o': x['offering_id']})
    ivs = rows(c, '''SELECT i.id, i.offering_id, i.kind, i.scope, i.summary, i.outcome, i.recheck_on, i.created_at,
                            t.first_name || ' ' || t.last_name AS author
                     FROM interventions i JOIN teachers t ON t.user_id = i.author_id
                     WHERE i.student_id = %(s)s AND (%(full)s OR i.scope = 'course')
                     ORDER BY i.created_at DESC LIMIT 50''', {'s': sid, 'full': full})
    overall = rows(c, 'SELECT week_no, risk_probability, risk_level FROM student_risk_overall '
                      'WHERE student_id=%(s)s ORDER BY week_no', {'s': sid}) if full else None
    return jsonify(student=prof, courses=cs, interventions=ivs, overall=overall, is_advisor=full)


# ------------------------------------------------------------------ оценки

@bp.get('/courses/<int:oid>/gradebook')
@login_required(*ROLES)
def gradebook(oid):
    if not _guard(oid):
        return jsonify(error='forbidden'), 403
    c = conn()
    asm = rows(c, '''SELECT id, title, kind, due_at, max_score, weight_pct, status FROM assessments
                     WHERE offering_id=%(o)s ORDER BY due_at''', {'o': oid})
    stu = rows(c, '''SELECT st.user_id AS student_id, st.first_name, st.last_name FROM enrollments e
                     JOIN students st ON st.user_id = e.student_id
                     WHERE e.offering_id=%(o)s AND e.status='enrolled' ORDER BY st.last_name, st.first_name''', {'o': oid})
    gr = rows(c, '''SELECT g.id AS grade_id, g.assessment_id, g.student_id, g.score, g.status, g.is_excused,
                           g.late_penalty, g.comment, s.status AS submission_status
                    FROM grades g JOIN assessments a ON a.id = g.assessment_id
                    LEFT JOIN submissions s ON s.id = g.submission_id
                    WHERE a.offering_id=%(o)s''', {'o': oid})
    return jsonify(assessments=asm, students=stu, grades=gr)


@bp.put('/grades')
@login_required(*ROLES)
def put_grade():
    """Выставить или изменить оценку. Любое изменение попадает в grade_audit_log."""
    c = conn(); u = me()
    d = request.get_json(force=True)
    a = one(c, 'SELECT id, offering_id, max_score, title FROM assessments WHERE id=%(a)s', {'a': d.get('assessment_id')})
    if not a:
        return jsonify(error='no_assessment'), 404
    if not teaches(c, u['id'], a['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    sid = d.get('student_id')
    if not one(c, 'SELECT 1 FROM enrollments WHERE student_id=%(s)s AND offering_id=%(o)s',
               {'s': sid, 'o': a['offering_id']}):
        return jsonify(error='not_enrolled'), 400
    status = d.get('status', 'draft')
    if status not in ('draft', 'published'):
        return jsonify(error='bad_status'), 400
    try:
        score = None if d.get('score') is None else float(d['score'])
    except (TypeError, ValueError):
        return jsonify(error='bad_score'), 400
    if score is not None and not (0 <= score <= float(a['max_score'])):
        return jsonify(error='score_out_of_range'), 400
    old = one(c, 'SELECT id, score, status FROM grades WHERE assessment_id=%(a)s AND student_id=%(s)s',
              {'a': a['id'], 's': sid})
    via_trigger = _audit_by_trigger(c)
    _audit_ctx(c, u['id'], d.get('reason'))
    if old and (float(old['score']) if old['score'] is not None else None) != score and not d.get('reason'):
        return jsonify(error='reason_required'), 400          # изменение оценки без причины не допускается
    if old:
        run(c, '''UPDATE grades SET score=%(sc)s, status=%(st)s::text, comment=%(cm)s, graded_by=%(u)s, graded_at=now(),
                  published_at = CASE WHEN %(st)s::text='published' THEN COALESCE(published_at, now()) ELSE NULL END
                  WHERE id=%(id)s''',
            {'sc': score, 'st': status, 'cm': d.get('comment'), 'u': u['id'], 'id': old['id']})
        gid = old['id']
    else:
        gid = run(c, '''INSERT INTO grades (assessment_id, student_id, score, late_penalty, is_excused, status,
                                            comment, graded_by, graded_at, published_at)
                        VALUES (%(a)s,%(s)s,%(sc)s,0,false,%(st)s::text,%(cm)s,%(u)s,now(),
                                CASE WHEN %(st)s::text='published' THEN now() END) RETURNING id''',
                  {'a': a['id'], 's': sid, 'sc': score, 'st': status, 'cm': d.get('comment'), 'u': u['id']})[0]['id']
    if not via_trigger:
        _audit_manual(c, gid, u['id'], old['score'] if old else None, score,
                      old['status'] if old else None, status, d.get('reason'))
    if status == 'published' and not (old and old['status'] == 'published'):
        run(c, '''INSERT INTO notifications (user_id, type, title, link) VALUES (%(s)s,'new_grade',%(t)s,%(l)s)''',
            {'s': sid, 't': f"Новая оценка: {a['title']}", 'l': f"/student/courses/{a['offering_id']}/grades"})
    c.commit()
    return jsonify(ok=True, grade_id=gid)


@bp.post('/assessments/<int:aid>/publish')
@login_required(*ROLES)
def publish(aid):
    """Опубликовать все черновики оценок за работу разом."""
    c = conn(); u = me()
    a = one(c, 'SELECT id, offering_id, title FROM assessments WHERE id=%(a)s', {'a': aid})
    if not a or not teaches(c, u['id'], a['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    via_trigger = _audit_by_trigger(c)
    _audit_ctx(c, u['id'], 'publish')
    done = run(c, '''UPDATE grades SET status='published', published_at=now()
                     WHERE assessment_id=%(a)s AND status='draft' AND score IS NOT NULL
                     RETURNING id, student_id, score''', {'a': aid})
    for g in done:
        if not via_trigger:
            _audit_manual(c, g['id'], u['id'], g['score'], g['score'], 'draft', 'published', 'publish')
        run(c, '''INSERT INTO notifications (user_id, type, title, link) VALUES (%(s)s,'new_grade',%(t)s,%(l)s)''',
            {'s': g['student_id'], 't': f"Новая оценка: {a['title']}", 'l': f"/student/courses/{a['offering_id']}/grades"})
    c.commit()
    return jsonify(published=len(done))


# ------------------------------------------------------------------ посещаемость

@bp.get('/courses/<int:oid>/meetings')
@login_required(*ROLES)
def meetings(oid):
    if not _guard(oid):
        return jsonify(error='forbidden'), 403
    return jsonify(items=rows(conn(), '''
        SELECT m.id, m.meeting_date, m.start_time, m.end_time, m.lesson_type, m.topic, m.week_no,
               COUNT(a.id) AS marked
        FROM class_meetings m LEFT JOIN attendance a ON a.meeting_id = m.id
        WHERE m.offering_id=%(o)s GROUP BY m.id ORDER BY m.meeting_date''', {'o': oid}))


@bp.get('/meetings/<int:mid>/attendance')
@login_required(*ROLES)
def meeting_attendance(mid):
    c = conn(); u = me()
    m = one(c, 'SELECT id, offering_id FROM class_meetings WHERE id=%(m)s', {'m': mid})
    if not m or not teaches(c, u['id'], m['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    return jsonify(items=rows(c, '''
        SELECT st.user_id AS student_id, st.first_name, st.last_name, a.status, a.excuse_document_id,
               d.status AS excuse_status, d.file_url AS excuse_file
        FROM enrollments e JOIN students st ON st.user_id = e.student_id
        LEFT JOIN attendance a ON a.meeting_id = %(m)s AND a.student_id = e.student_id
        LEFT JOIN excuse_documents d ON d.meeting_id = %(m)s AND d.student_id = e.student_id
        WHERE e.offering_id = %(o)s AND e.status = 'enrolled' ORDER BY st.last_name''', {'m': mid, 'o': m['offering_id']}))


@bp.put('/meetings/<int:mid>/attendance')
@login_required(*ROLES)
def mark_attendance(mid):
    c = conn(); u = me()
    m = one(c, 'SELECT id, offering_id FROM class_meetings WHERE id=%(m)s', {'m': mid})
    if not m or not teaches(c, u['id'], m['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    recs = request.get_json(force=True).get('records', [])
    ok = {'present', 'absent', 'late', 'excused'}
    enrolled = {r['student_id'] for r in rows(c, 'SELECT student_id FROM enrollments WHERE offering_id=%(o)s',
                                              {'o': m['offering_id']})}
    n = 0
    for r in recs:
        if r.get('status') not in ok or r.get('student_id') not in enrolled:
            continue
        run(c, '''INSERT INTO attendance (meeting_id, student_id, status, marked_by, marked_at)
                  VALUES (%(m)s,%(s)s,%(st)s,%(u)s,now())
                  ON CONFLICT (meeting_id, student_id) DO UPDATE SET status=EXCLUDED.status,
                       marked_by=EXCLUDED.marked_by, marked_at=now()''',
            {'m': mid, 's': r['student_id'], 'st': r['status'], 'u': u['id']})
        n += 1
    c.commit()
    return jsonify(saved=n)


@bp.post('/excuses/<int:eid>/review')
@login_required(*ROLES)
def review_excuse(eid):
    c = conn(); u = me()
    d = request.get_json(force=True)
    e = one(c, '''SELECT x.id, x.student_id, x.meeting_id, m.offering_id FROM excuse_documents x
                  JOIN class_meetings m ON m.id = x.meeting_id WHERE x.id=%(e)s''', {'e': eid})
    if not e or not teaches(c, u['id'], e['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    st = d.get('status')
    if st not in ('approved', 'rejected'):
        return jsonify(error='bad_status'), 400
    run(c, '''UPDATE excuse_documents SET status=%(s)s, reviewed_by=%(u)s, review_comment=%(c)s, reviewed_at=now()
              WHERE id=%(e)s''', {'s': st, 'u': u['id'], 'c': d.get('comment'), 'e': eid})
    if st == 'approved':
        run(c, '''UPDATE attendance SET status='excused', excuse_document_id=%(e)s, marked_by=%(u)s, marked_at=now()
                  WHERE meeting_id=%(m)s AND student_id=%(s)s''',
            {'e': eid, 'u': u['id'], 'm': e['meeting_id'], 's': e['student_id']})
    c.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ эдвайзинг и вмешательства

@bp.get('/advisees')
@login_required(*ROLES)
def advisees():
    """Очередь куратора: подопечные по убыванию риска и что с ними делать.

    needs_attention = высокий риск и нет контакта за последние FOLLOWUP_DAYS дней,
    либо подошла дата повторной проверки (recheck_on) из прошлого вмешательства."""
    c = conn(); u = me()
    sem, week = latest_week(c)
    items = rows(c, '''
        SELECT st.user_id AS student_id, us.login_id, st.first_name, st.last_name, st.group_id, sg.code AS group_code,
               r.risk_probability, r.risk_level, pr.risk_probability AS prev_risk,
               (SELECT COUNT(*) FROM risk_predictions p JOIN course_offerings o ON o.id = p.offering_id
                 WHERE p.student_id = st.user_id AND p.week_no = %(w)s AND p.risk_level = 'high'
                   AND p.model_id = (SELECT id FROM model_versions WHERE version = %(v)s)) AS courses_at_risk,
               (SELECT MAX(created_at) FROM interventions i WHERE i.student_id = st.user_id) AS last_contact,
               (SELECT COUNT(*) FROM interventions i WHERE i.student_id = st.user_id) AS contacts,
               (SELECT MIN(recheck_on) FROM interventions i WHERE i.student_id = st.user_id
                 AND i.recheck_on IS NOT NULL AND i.outcome IS NULL) AS recheck_on,
               (SELECT (CURRENT_DATE - MAX(created_at)::date) FROM interventions i
                 WHERE i.student_id = st.user_id) AS days_since_contact
        FROM advisor_assignments aa
        JOIN students st ON st.user_id = aa.student_id
        JOIN users us ON us.id = st.user_id
        LEFT JOIN student_groups sg ON sg.id = st.group_id
        LEFT JOIN student_risk_overall r ON r.student_id = st.user_id AND r.week_no = %(w)s AND r.semester_id = %(sem)s
        LEFT JOIN student_risk_overall pr ON pr.student_id = st.user_id AND pr.week_no = %(w)s - 1 AND pr.semester_id = %(sem)s
        WHERE aa.advisor_id = %(u)s AND aa.starts_on <= CURRENT_DATE AND (aa.ends_on IS NULL OR aa.ends_on >= CURRENT_DATE)
        ORDER BY r.risk_probability DESC NULLS LAST''',
                 {'u': u['id'], 'w': week, 'sem': sem['id'], 'v': bundle()['version']})
    today = str(one(c, 'SELECT CURRENT_DATE AS d')['d'])[:10]
    for x in items:
        days = x['days_since_contact']
        due = x['recheck_on'] is not None and str(x['recheck_on'])[:10] <= today
        stale = days is None or int(days) > FOLLOWUP_DAYS
        x['recheck_due'] = due
        x['needs_attention'] = bool(due or (x['risk_level'] == 'high' and stale))
        x['change'] = (round(float(x['risk_probability']) - float(x['prev_risk']), 4)
                       if x['risk_probability'] is not None and x['prev_risk'] is not None else None)
    items.sort(key=lambda x: (not x['needs_attention'], -(float(x['risk_probability']) if x['risk_probability'] is not None else -1)))
    stats = {'total': len(items),
             'needs_attention': sum(1 for x in items if x['needs_attention']),
             'high': sum(1 for x in items if x['risk_level'] == 'high'),
             'medium': sum(1 for x in items if x['risk_level'] == 'medium'),
             'contacted': sum(1 for x in items if x['last_contact'] is not None)}
    return jsonify(week=week, followup_days=FOLLOWUP_DAYS, stats=stats, items=items)


@bp.post('/interventions')
@login_required(*ROLES)
def add_intervention():
    c = conn(); u = me()
    d = request.get_json(force=True)
    sid, oid = d.get('student_id'), d.get('offering_id')
    scope = d.get('scope', 'course')
    if d.get('kind') not in ('message', 'meeting', 'referral', 'other') or scope not in ('course', 'advising') \
            or not (d.get('summary') or '').strip():
        return jsonify(error='bad_request'), 400
    if scope == 'course':
        if not oid or not teaches(c, u['id'], oid, u['role']):
            return jsonify(error='forbidden'), 403
    elif not (u['role'] == 'admin' or advises(c, u['id'], sid)):
        return jsonify(error='forbidden'), 403
    if not can_see_student(c, u['id'], sid, u['role']):
        return jsonify(error='forbidden'), 403
    pred = one(c, '''SELECT id FROM risk_predictions WHERE student_id=%(s)s AND offering_id=%(o)s
                     AND model_id=%(m)s ORDER BY week_no DESC LIMIT 1''',
               {'s': sid, 'o': oid, 'm': active_model_id(c)}) if oid else None
    new = run(c, '''INSERT INTO interventions (student_id, offering_id, author_id, kind, scope, summary, outcome,
                                               recheck_on, prediction_id)
                    VALUES (%(s)s,%(o)s,%(u)s,%(k)s,%(sc)s,%(sm)s,%(oc)s,%(rc)s,%(p)s) RETURNING id''',
              {'s': sid, 'o': oid, 'u': u['id'], 'k': d['kind'], 'sc': scope, 'sm': d['summary'].strip(),
               'oc': d.get('outcome'), 'rc': d.get('recheck_on'), 'p': pred['id'] if pred else None})
    c.commit()
    return jsonify(id=new[0]['id']), 201


@bp.get('/interventions')
@login_required(*ROLES)
def list_interventions():
    '''Журнал вмешательств. ?student_id= — по одному студенту, иначе всё, что доступно пользователю.
    Преподаватель видит записи по своим курсам и свои собственные, куратор ещё и по подопечным.'''
    c = conn(); u = me()
    sid = request.args.get('student_id', type=int)
    if sid is not None and not can_see_student(c, u['id'], sid, u['role']):
        return jsonify(error='forbidden'), 403
    items = rows(c, '''
        SELECT i.id, i.student_id, st.first_name || ' ' || st.last_name AS student, i.offering_id, co.code AS course_code,
               i.kind, i.scope, i.summary, i.outcome, i.recheck_on, i.created_at, i.author_id,
               t.first_name || ' ' || t.last_name AS author
        FROM interventions i
        JOIN students st ON st.user_id = i.student_id
        JOIN teachers t ON t.user_id = i.author_id
        LEFT JOIN course_offerings o ON o.id = i.offering_id
        LEFT JOIN courses co ON co.id = o.course_id
        WHERE (%(s)s::int IS NULL OR i.student_id = %(s)s::int)
          AND (%(admin)s OR i.author_id = %(u)s
               OR EXISTS (SELECT 1 FROM advisor_assignments aa WHERE aa.advisor_id = %(u)s AND aa.student_id = i.student_id
                          AND aa.starts_on <= CURRENT_DATE AND (aa.ends_on IS NULL OR aa.ends_on >= CURRENT_DATE))
               OR (i.scope = 'course' AND (o.teacher_id = %(u)s OR EXISTS
                   (SELECT 1 FROM offering_staff f WHERE f.offering_id = o.id AND f.teacher_id = %(u)s))))
        ORDER BY i.created_at DESC, i.id DESC LIMIT 200''', {'s': sid, 'u': u['id'], 'admin': u['role'] == 'admin'})
    for x in items:
        x['mine'] = x['author_id'] == u['id']
    return jsonify(items=items)


@bp.put('/interventions/<int:iid>')
@login_required(*ROLES)
def update_intervention(iid):
    '''Записать результат вмешательства или перенести повторную проверку. Только автор записи (или админ).'''
    c = conn(); u = me()
    d = request.get_json(force=True)
    cur = one(c, 'SELECT id, author_id FROM interventions WHERE id = %(i)s', {'i': iid})
    if not cur:
        return jsonify(error='not_found'), 404
    if u['role'] != 'admin' and cur['author_id'] != u['id']:
        return jsonify(error='forbidden'), 403
    if 'outcome' not in d and 'recheck_on' not in d:
        return jsonify(error='bad_request'), 400
    outcome = d.get('outcome')
    if outcome is not None:
        outcome = str(outcome).strip() or None
    run(c, '''UPDATE interventions SET
                outcome    = CASE WHEN %(ho)s THEN %(oc)s ELSE outcome END,
                recheck_on = CASE WHEN %(hr)s THEN %(rc)s::date ELSE recheck_on END
              WHERE id = %(i)s''',
        {'ho': 'outcome' in d, 'oc': outcome, 'hr': 'recheck_on' in d, 'rc': d.get('recheck_on') or None, 'i': iid})
    c.commit()
    return jsonify(ok=True)


# ------------------------------------------------------------------ отзывы о курсе

@bp.get('/courses/<int:oid>/feedback')
@login_required(*ROLES)
def course_feedback(oid):
    """Агрегат. Пока ответов меньше MIN_ANON, цифры и комментарии не отдаются."""
    if not _guard(oid):
        return jsonify(error='forbidden'), 403
    c = conn()
    s = one(c, 'SELECT id FROM feedback_surveys WHERE offering_id=%(o)s', {'o': oid})
    if not s:
        return jsonify(available=False, reason='no_survey')
    n = one(c, 'SELECT COUNT(*) AS n FROM feedback_responses WHERE survey_id=%(s)s', {'s': s['id']})['n']
    if int(n) < MIN_ANON:
        return jsonify(available=False, reason='too_few_responses', responses=int(n), minimum=MIN_ANON)
    agg = one(c, '''SELECT ROUND(AVG(rating_content),2) AS content, ROUND(AVG(rating_teaching),2) AS teaching,
                           ROUND(AVG(rating_materials),2) AS materials, ROUND(AVG(rating_assessment),2) AS assessment,
                           ROUND(AVG(rating_availability),2) AS availability
                    FROM feedback_responses WHERE survey_id=%(s)s''', {'s': s['id']})
    comments = [r['comment'] for r in rows(c, '''SELECT comment FROM feedback_responses
                    WHERE survey_id=%(s)s AND comment IS NOT NULL AND comment <> '' ORDER BY id''', {'s': s['id']})]
    return jsonify(available=True, responses=int(n), averages=agg, comments=comments)


@bp.get('/assessments/<int:aid>/submissions')
@login_required(*ROLES)
def submissions(aid):
    c = conn(); u = me()
    a = one(c, 'SELECT id, offering_id, title, due_at FROM assessments WHERE id=%(a)s', {'a': aid})
    if not a or not teaches(c, u['id'], a['offering_id'], u['role']):
        return jsonify(error='forbidden'), 403
    return jsonify(assessment=a, items=rows(c, '''
        SELECT st.user_id AS student_id, st.first_name, st.last_name, s.status, s.submitted_at, s.file_url,
               s.text_answer, g.score, g.status AS grade_status
        FROM enrollments e JOIN students st ON st.user_id = e.student_id
        LEFT JOIN submissions s ON s.assessment_id = %(a)s AND s.student_id = e.student_id AND s.attempt_no = 1
        LEFT JOIN grades g ON g.assessment_id = %(a)s AND g.student_id = e.student_id
        WHERE e.offering_id = %(o)s AND e.status = 'enrolled' ORDER BY st.last_name''', {'a': aid, 'o': a['offering_id']}))
