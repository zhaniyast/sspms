"""Проверка новых функций: импорт оценок из CSV (G), отчёты (E), очередь куратора и журнал (D),
объявления (B), ежедневный пересчёт (F).

Меняет данные и в конце возвращает их как было (остаются только записи аудита).
Запуск:  python backend/tests/test_features.py      (на своей копии базы)
"""
import sys, os, io, csv
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    import psycopg  # noqa
except ImportError:
    import psycopg_shim; psycopg_shim.install()
import warnings; warnings.filterwarnings('ignore')
from backend.app import create_app
from backend.db import connect, one, rows, run
from backend import scheduler

app = create_app(); app.testing = True
c = connect()
t = one(c, '''SELECT o.id AS oid, o.teacher_id AS tid FROM course_offerings o JOIN enrollments e ON e.offering_id=o.id
              WHERE e.status='enrolled' GROUP BY o.id, o.teacher_id ORDER BY COUNT(*) DESC, o.id LIMIT 1''')
OID, TID = t['oid'], t['tid']
OTHER_T = one(c, '''SELECT user_id FROM teachers WHERE user_id<>%(t)s AND user_id NOT IN
                    (SELECT teacher_id FROM offering_staff WHERE offering_id=%(o)s) LIMIT 1''', {'t': TID, 'o': OID})['user_id']
ADMIN = one(c, "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id']
enrolled = rows(c, '''SELECT st.user_id, u.login_id FROM enrollments e JOIN students st ON st.user_id=e.student_id
                      JOIN users u ON u.id=st.user_id WHERE e.offering_id=%(o)s AND e.status='enrolled'
                      ORDER BY st.user_id''', {'o': OID})
S1, S2, S3, S4 = [str(x['login_id']) for x in enrolled[:4]]
STUDENT = enrolled[0]['user_id']
out = one(c, '''SELECT st.user_id, u.login_id FROM students st JOIN users u ON u.id=st.user_id
                WHERE st.user_id NOT IN (SELECT student_id FROM enrollments WHERE offering_id=%(o)s) LIMIT 1''', {'o': OID})
OUTSIDER, OUTSIDER_UID = str(out['login_id']), out['user_id']
cat = one(c, 'SELECT id FROM assessment_categories WHERE offering_id=%(o)s ORDER BY id LIMIT 1', {'o': OID})['id']
AID = run(c, '''INSERT INTO assessments (offering_id, category_id, title, kind, due_at, max_score, weight_pct, status)
                VALUES (%(o)s,%(k)s,'ZZ Import test','quiz', now(), 20, 0, 'draft') RETURNING id''',
          {'o': OID, 'k': cat})[0]['id']
adv = one(c, '''SELECT advisor_id, student_id FROM advisor_assignments
                WHERE starts_on <= CURRENT_DATE AND (ends_on IS NULL OR ends_on >= CURRENT_DATE) ORDER BY id LIMIT 1''')
ADVISOR, ADVISEE = adv['advisor_id'], adv['student_id']
# преподаватель, который не куратор этого студента и не ведёт у него ни одного курса
STRANGER = one(c, '''SELECT t.user_id FROM teachers t WHERE t.user_id <> %(a)s
                     AND NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id
                                     WHERE e.student_id = %(s)s AND (o.teacher_id = t.user_id OR EXISTS
                                       (SELECT 1 FROM offering_staff f WHERE f.offering_id = o.id AND f.teacher_id = t.user_id)))
                     AND NOT EXISTS (SELECT 1 FROM advisor_assignments aa WHERE aa.advisor_id = t.user_id AND aa.student_id = %(s)s)
                     ORDER BY t.user_id LIMIT 1''', {'a': ADVISOR, 's': ADVISEE})['user_id']
c.commit()
fails = []
made_ann, made_iv = [], []


def user(uid, role):
    cl = app.test_client()
    with cl.session_transaction() as s:
        s['uid'], s['role'] = uid, role
    return cl


def ok(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name, extra if not cond else '')
    if not cond: fails.append(name)


def n_grades():
    cc = connect()
    try:
        return int(one(cc, 'SELECT COUNT(*) AS n FROM grades WHERE assessment_id=%(a)s', {'a': AID})['n'])
    finally:
        cc.close()


def imp(client, text, **kw):
    return client.post(f'/api/teacher/assessments/{AID}/grades-import', json={'csv': text, **kw})


T, S, O, A, ADV = user(TID, 'teacher'), user(STUDENT, 'student'), user(OTHER_T, 'teacher'), user(ADMIN, 'admin'), user(ADVISOR, 'teacher')
X = user(STRANGER, 'teacher')
URL = f'/api/teacher/assessments/{AID}/grades-import'
try:
    # ------------------------------------------------------------ G: импорт оценок
    print('--- G: CSV grade import')
    r = T.get(f'/api/teacher/assessments/{AID}/grades-template')
    body = r.data.decode('utf-8-sig')
    tpl = list(csv.reader(io.StringIO(body)))
    ok('template: csv with all enrolled students', r.status_code == 200 and tpl[0][:4] == ['student_id', 'last_name', 'first_name', 'score']
       and len(tpl) - 1 == len(enrolled) and 'attachment' in r.headers.get('Content-Disposition', ''), r.data[:200])
    ok('template: other teacher -> 403', O.get(f'/api/teacher/assessments/{AID}/grades-template').status_code == 403)
    ok('import: other teacher -> 403', imp(O, 'student_id,score\n1,1').status_code == 403)
    ok('import: student -> 403', imp(S, 'student_id,score\n1,1').status_code == 403)
    ok('import: unknown assessment -> 404', T.post('/api/teacher/assessments/99999999/grades-import', json={'csv': 'student_id,score\n1,1'}).status_code == 404)
    r = imp(T, ''); ok('empty file rejected', r.status_code == 400 and r.get_json()['error'] == 'empty_file', r.data[:200])
    r = imp(T, 'name,points_total\nA,5'); ok('bad header rejected', r.status_code == 400 and r.get_json()['error'] == 'bad_header', r.data[:200])

    mixed = (f'student_id,score,comment\n{S1},15,good\n9999999,10,\n{OUTSIDER},10,\n{S1},12,\n'
             f'{S2},25,\n{S3},abc,\n{S4},,\n')
    r = imp(T, mixed); j = r.get_json()
    errs = {x['line']: x['error'] for x in j['rows']}
    ok('dry run is the default and writes nothing', r.status_code == 200 and j['dry_run'] and not j['applied'] and n_grades() == 0, r.data[:300])
    ok('dry run: one valid row, six errors', j['summary'] == {'total': 7, 'new': 1, 'update': 0, 'unchanged': 0, 'errors': 6}, j['summary'])
    ok('dry run: each error is named', errs == {2: None, 3: 'unknown_student', 4: 'not_enrolled', 5: 'duplicate_in_file',
                                                 6: 'score_out_of_range', 7: 'bad_score', 8: 'missing_score'}, errs)
    ok('dry run: cannot apply a file with errors', j['can_apply'] is False)
    r = imp(T, mixed, dry_run=False); ok('apply with errors -> 400, nothing written', r.status_code == 400 and r.get_json()['error'] == 'has_errors' and n_grades() == 0, r.data[:200])

    good = f'student_id;score;comment\n{S1};15,5;well done\n{S2};20;\n'           # Excel: точка с запятой и запятая в числе
    r = imp(T, good); j = r.get_json()
    ok('semicolon and decimal comma are understood', j['summary']['new'] == 2 and j['summary']['errors'] == 0 and j['can_apply']
       and [x['score'] for x in j['rows']] == [15.5, 20.0], r.data[:300])
    r = imp(T, good, dry_run=False); j = r.get_json()
    ok('apply clean file', r.status_code == 200 and j['applied'] and j['written'] == 2 and n_grades() == 2, r.data[:300])
    cc = connect()
    g = rows(cc, 'SELECT score, status, comment FROM grades WHERE assessment_id=%(a)s ORDER BY score', {'a': AID}); cc.close()
    ok('imported grades are drafts', [x['status'] for x in g] == ['draft', 'draft'] and float(g[0]['score']) == 15.5 and g[0]['comment'] == 'well done', g)
    r = imp(T, good); j = r.get_json()
    ok('re-import of the same file changes nothing', j['summary']['unchanged'] == 2 and j['can_apply'] is False, j['summary'])

    change = f'student_id,score\n{S1},18\n{S3},7\n'
    r = imp(T, change); j = r.get_json()
    ok('changed score is shown with the old value', j['summary'] == {'total': 2, 'new': 1, 'update': 1, 'unchanged': 0, 'errors': 0}
       and j['needs_reason'] and j['rows'][0]['old_score'] == 15.5, r.data[:300])
    r = imp(T, change, dry_run=False); ok('changing a grade without a reason -> 400', r.status_code == 400 and r.get_json()['error'] == 'reason_required' and n_grades() == 2, r.data[:200])
    r = imp(T, change, dry_run=False, reason='regrade after appeal'); j = r.get_json()
    ok('changing a grade with a reason', r.status_code == 200 and j['written'] == 2 and n_grades() == 3, r.data[:200])
    cc = connect()
    au = rows(cc, '''SELECT l.reason, l.old_score, l.new_score FROM grade_audit_log l JOIN grades g ON g.id=l.grade_id
                     WHERE g.assessment_id=%(a)s AND l.reason LIKE %(p)s''', {'a': AID, 'p': '%regrade after appeal%'}); cc.close()
    ok('audit log keeps the reason and both scores', len(au) >= 1 and float(au[0]['old_score']) == 15.5 and float(au[0]['new_score']) == 18, au)

    r = imp(T, f'student_id,score\n{S2},19\n9999999,5\n', dry_run=False, skip_invalid=True, reason='fix'); j = r.get_json()
    ok('skip_invalid writes valid rows only', r.status_code == 200 and j['written'] == 1 and j['skipped_errors'] == 1, r.data[:200])
    r = T.post(URL, data={'file': (io.BytesIO(f'student_id,score\n{S3},9\n'.encode('cp1251')), 'grades.csv'), 'dry_run': '1'},
               content_type='multipart/form-data'); j = r.get_json()
    ok('file upload (multipart) works', r.status_code == 200 and j['summary']['update'] == 1, r.data[:200])
    r = S.get(f'/api/student/courses/{OID}/grades')
    ok('student does not see the draft work', r.status_code == 200 and not any(a.get('title') == 'ZZ Import test' for a in r.get_json()['assessments']))

    # ------------------------------------------------------------ E: отчёты
    print('--- E: reports')
    for kind in ('course-performance', 'attendance-summary', 'gradebook', 'student-risk'):
        r = T.get(f'/api/teacher/reports/{kind}?offering_id={OID}')
        data = list(csv.reader(io.StringIO(r.data.decode('utf-8-sig'))))
        ok(f'report {kind}: csv, one row per student', r.status_code == 200 and r.data[:3] == b'\xef\xbb\xbf' and data[0][0] == 'student_id'
           and len(data) - 1 == len(enrolled) and all(len(x) == len(data[0]) for x in data)
           and 'attachment' in r.headers.get('Content-Disposition', ''), r.data[:200])
    r = T.get(f'/api/teacher/reports/gradebook?offering_id={OID}&format=json'); j = r.get_json()
    n_asm = one(connect(), 'SELECT COUNT(*) AS n FROM assessments WHERE offering_id=%(o)s', {'o': OID})['n']
    ok('gradebook: a column per assessment', r.status_code == 200 and len(j['columns']) == 4 + int(n_asm) + 3 and j['total'] == len(enrolled), len(j['columns']))
    r = T.get(f'/api/teacher/reports/student-risk?offering_id={OID}&format=json'); j = r.get_json()
    lv = [x[5] for x in j['rows'] if x[5]]
    ok('student-risk: high risk first', lv == sorted(lv, key=lambda v: {'high': 0, 'medium': 1, 'low': 2}[v]) and len(lv) > 0, lv[:5])
    r = T.get(f'/api/teacher/reports/attendance-summary?offering_id={OID}&format=json'); j = r.get_json()
    i = {k: n for n, k in enumerate(j['columns'])}
    ok('attendance: counts add up', all(x[i['present']] + x[i['late']] + x[i['absent']] + x[i['excused']] == x[i['marked_lessons']] for x in j['rows']))
    ok('report: other teacher -> 403', O.get(f'/api/teacher/reports/gradebook?offering_id={OID}').status_code == 403)
    ok('report: student -> 403', S.get(f'/api/teacher/reports/gradebook?offering_id={OID}').status_code == 403)
    ok('report: unknown kind -> 404', T.get(f'/api/teacher/reports/secret?offering_id={OID}').status_code == 404)
    ok('report: no offering_id -> 400', T.get('/api/teacher/reports/gradebook').status_code == 400)
    ok('report: admin can read any course', A.get(f'/api/teacher/reports/gradebook?offering_id={OID}').status_code == 200)

    # ------------------------------------------------------------ D: очередь куратора и журнал
    print('--- D: curator queue and log')
    r = ADV.get('/api/teacher/advisees'); j = r.get_json()
    flags = [x['needs_attention'] for x in j['items']]
    ok('queue: stats and items', r.status_code == 200 and j['stats']['total'] == len(j['items']) > 0
       and j['stats']['needs_attention'] == sum(flags) and 'login_id' in j['items'][0], r.data[:300])
    ok('queue: students who need attention come first', flags == sorted(flags, reverse=True), flags)
    r = ADV.post('/api/teacher/interventions', json={'student_id': ADVISEE, 'scope': 'advising', 'kind': 'meeting',
                                                     'summary': 'ZZ talked about workload', 'recheck_on': '2020-01-01'})
    ok('log: advisor adds an entry', r.status_code == 201, r.data[:200]); iv = r.get_json().get('id'); made_iv.append(iv)
    r = ADV.get(f'/api/teacher/interventions?student_id={ADVISEE}'); j = r.get_json()
    ok('log: entry is listed for the student', r.status_code == 200 and any(x['id'] == iv and x['mine'] for x in j['items']), r.data[:300])
    r = ADV.get('/api/teacher/advisees'); me_row = next(x for x in r.get_json()['items'] if x['student_id'] == ADVISEE)
    ok('queue: overdue re-check puts the student in the queue', me_row['recheck_due'] and me_row['needs_attention'], me_row)
    ok('log: other teacher cannot edit the entry', X.put(f'/api/teacher/interventions/{iv}', json={'outcome': 'x'}).status_code == 403)
    r = ADV.put(f'/api/teacher/interventions/{iv}', json={'outcome': 'ZZ agreed on a plan'})
    ok('log: author records the outcome', r.status_code == 200, r.data[:200])
    r = ADV.get('/api/teacher/advisees'); me_row = next(x for x in r.get_json()['items'] if x['student_id'] == ADVISEE)
    ok('queue: closed entry no longer counts as an overdue re-check', me_row['recheck_due'] is False, me_row)
    r = ADV.get('/api/teacher/interventions'); ok('log: full journal', r.status_code == 200 and any(x['id'] == iv for x in r.get_json()['items']))
    ok('log: teacher without access -> 403', X.get(f'/api/teacher/interventions?student_id={ADVISEE}').status_code == 403)
    ok('log: stranger does not see the entry in the full journal', not any(x['id'] == iv for x in X.get('/api/teacher/interventions').get_json()['items']))
    ok('log: student -> 403', S.get('/api/teacher/interventions').status_code == 403)
    ok('log: empty update rejected', ADV.put(f'/api/teacher/interventions/{iv}', json={}).status_code == 400)

    # ------------------------------------------------------------ B: объявления
    print('--- B: announcements')
    r = T.post('/api/announcements', json={'offering_id': OID, 'title': 'ZZ Quiz moved', 'body': 'Quiz 2 is on Friday.'})
    ok('teacher posts to own course', r.status_code == 201, r.data[:200]); an = r.get_json().get('id'); made_ann.append(an)
    r = S.get('/api/announcements'); mine = [x for x in r.get_json()['items'] if x['id'] == an]
    ok('enrolled student sees it, cannot delete', len(mine) == 1 and mine[0]['can_delete'] is False and mine[0]['course_code'], mine)
    r = user(OUTSIDER_UID, 'student').get('/api/announcements')
    ok('student of another course does not see it', r.status_code == 200 and not any(x['id'] == an for x in r.get_json()['items']))
    ok('teacher cannot post to a foreign course', O.post('/api/announcements', json={'offering_id': OID, 'title': 't', 'body': 'b'}).status_code == 403)
    ok('teacher cannot post university-wide', T.post('/api/announcements', json={'title': 't', 'body': 'b'}).status_code == 403)
    ok('student cannot post', S.post('/api/announcements', json={'offering_id': OID, 'title': 't', 'body': 'b'}).status_code == 403)
    ok('empty title rejected', T.post('/api/announcements', json={'offering_id': OID, 'title': ' ', 'body': 'b'}).status_code == 400)
    r = A.post('/api/announcements', json={'title': 'ZZ Campus closed', 'body': 'Holiday.'})
    ok('admin posts university-wide', r.status_code == 201, r.data[:200]); an2 = r.get_json().get('id'); made_ann.append(an2)
    ok('everyone sees the university-wide one', any(x['id'] == an2 for x in user(OUTSIDER_UID, 'student').get('/api/announcements').get_json()['items']))
    ok('non-author cannot delete', O.delete(f'/api/announcements/{an}').status_code == 403)
    ok('author deletes own announcement', T.delete(f'/api/announcements/{an}').status_code == 200)
    ok('deleted one is gone', not any(x['id'] == an for x in S.get('/api/announcements').get_json()['items']))

    # ------------------------------------------------------------ F: ежедневный пересчёт
    print('--- F: daily scoring')
    import datetime as dt
    ok('time parsing', scheduler.parse_hhmm('03:00') == (3, 0) and scheduler.parse_hhmm('25:00') is None and scheduler.parse_hhmm('x') is None)
    now = dt.datetime(2026, 11, 16, 10, 0)
    ok('next run is today if the time is still ahead', scheduler.next_run((22, 0), now) == dt.datetime(2026, 11, 16, 22, 0))
    ok('next run is tomorrow if the time has passed', scheduler.next_run((3, 0), now) == dt.datetime(2026, 11, 17, 3, 0))
    ok('schedule is off without SCORING_DAILY_AT', scheduler.STATE['enabled'] is False)
    lock = connect()
    one(lock, 'SELECT pg_advisory_lock(%(k)s) AS ok', {'k': scheduler.LOCK_KEY})
    res = scheduler.run_once()
    ok('second run is skipped while one is in progress', 'skipped' in res, res)
    one(lock, 'SELECT pg_advisory_unlock(%(k)s) AS ok', {'k': scheduler.LOCK_KEY}); lock.close()
    r = A.post('/api/admin/scoring-run'); j = r.get_json()
    ok('run recomputes predictions', r.status_code == 200 and j.get('predictions', 0) > 0, r.data[:200])
    r = A.get('/api/admin/scoring-status'); j = r.get_json()
    ok('status shows the last run', r.status_code == 200 and j['schedule']['last_run'] and j['predictions'] > 0, r.data[:300])
    r1, r2 = T.get('/healthz'), T.get('/readyz')
    ok('healthz answers without the database', r1.status_code == 200 and r1.get_json() == {'ok': True})
    ok('readyz checks the database', r2.status_code == 200 and r2.get_json() == {'ok': True, 'db': True}, r2.data[:200])
    ok('status is admin only', T.get('/api/admin/scoring-status').status_code == 403 and T.post('/api/admin/scoring-run').status_code == 403)
finally:
    c = connect()
    run(c, "SET session_replication_role = replica")
    run(c, 'DELETE FROM grade_audit_log WHERE grade_id IN (SELECT id FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE title LIKE %(p)s))', {'p': 'ZZ %'})
    run(c, 'DELETE FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE title LIKE %(p)s)', {'p': 'ZZ %'})
    run(c, 'DELETE FROM assessments WHERE title LIKE %(p)s', {'p': 'ZZ %'})
    run(c, 'DELETE FROM announcements WHERE title LIKE %(p)s', {'p': 'ZZ %'})
    run(c, 'DELETE FROM interventions WHERE summary LIKE %(p)s', {'p': 'ZZ %'})
    c.commit()
print('\nFAILED:' if fails else '\nALL PASSED', fails or '')
