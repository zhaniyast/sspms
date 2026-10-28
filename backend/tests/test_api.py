"""
Проверка API на реальных данных из дампа. Запуск (в песочнице):  python backend/tests/test_api.py
На машине с настоящим psycopg запускать без строки install().
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    import psycopg  # noqa
except ImportError:
    import psycopg_shim; psycopg_shim.install()
import warnings; warnings.filterwarnings('ignore')
from backend.app import create_app

app = create_app(); app.testing = True
from backend.db import connect as _connect, one as _one, rows as _rows
_c = _connect()
_t = _one(_c, '''SELECT o.id AS oid, o.teacher_id AS tid FROM course_offerings o
                 JOIN enrollments e ON e.offering_id = o.id GROUP BY o.id, o.teacher_id
                 ORDER BY COUNT(*) DESC, o.id LIMIT 1''')
TEACHER, TOID = _t['tid'], _t['oid']
STUDENT = _one(_c, 'SELECT student_id FROM enrollments WHERE offering_id=%(o)s ORDER BY student_id LIMIT 1', {'o': TOID})['student_id']
ADMIN = _one(_c, "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1")['id']
N_OFFERINGS = int(_one(_c, 'SELECT COUNT(*) AS n FROM course_offerings')['n'])
OTHER_STUDENT = _one(_c, 'SELECT user_id FROM students WHERE user_id <> %(s)s ORDER BY user_id LIMIT 1', {'s': STUDENT})['user_id']
_c.rollback(); _c.close()
fails = []
import time
REASON = 'тест ' + str(time.time())


def as_user(uid, role):
    cl = app.test_client()
    with cl.session_transaction() as s:
        s['uid'], s['role'] = uid, role
    return cl


def check(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name, extra if not cond else '')
    if not cond: fails.append(name)


anon = app.test_client()
check('anon /api/me -> 401', anon.get('/api/me').status_code == 401)
check('anon student route -> 401', anon.get('/api/student/courses').status_code == 401)

S = as_user(STUDENT, 'student')
r = S.get('/api/me'); j = r.get_json(); check('me', r.status_code == 200 and j['role'] == 'student', r.data)
r = S.get('/api/student/courses'); j = r.get_json(); check('student courses', r.status_code == 200 and len(j['courses']) >= 3, r.data[:300])
oid = j['courses'][0]['offering_id']; print('   week', j['week'], 'course0', j['courses'][0]['code'], j['courses'][0]['current_percent'], j['courses'][0]['risk'])
r = S.get(f'/api/student/courses/{oid}/grades'); j = r.get_json(); check('student grades', r.status_code == 200 and len(j['assessments']) > 0, r.data[:300])
unpub = [a for a in j['assessments'] if a['score'] is not None]
print('   assessments', len(j['assessments']), 'with score', len(unpub))
r = S.get('/api/student/courses/9999/grades'); check('student foreign course -> 403', r.status_code == 403)
r = S.get('/api/student/risk'); j = r.get_json(); check('student risk', r.status_code == 200 and j['courses'][0]['latest'] is not None, r.data[:300])
print('   latest', j['courses'][0]['latest'], j['courses'][0]['factors'][:2])
check('risk history starts at week 4', min(h['week_no'] for h in j['courses'][0]['history']) == 4)
r = S.get('/api/student/risk?lang=kk'); check('kk text', 'орташасы' in json.dumps(r.get_json(), ensure_ascii=False) or r.get_json()['courses'][0]['factors'] == [])
r = S.get('/api/student/overall-risk'); check('overall risk', r.status_code == 200 and len(r.get_json()['items']) > 0)
r = S.get('/api/student/deadlines'); check('deadlines', r.status_code == 200, r.data[:200])
r = S.get('/api/student/attendance'); check('attendance', r.status_code == 200 and len(r.get_json()['items']) > 0, r.data[:200])
r = S.get(f'/api/student/attendance/{oid}'); check('attendance detail', r.status_code == 200)
r = S.get('/api/notifications'); check('notifications', r.status_code == 200)
r = S.post('/api/predict', json={'offering_id': oid, 'overrides': {'mean_score': 95, 'submitted_share': 1}})
j = r.get_json(); check('predict what-if', r.status_code == 200 and 'risk' in j, r.data[:300]); print('   ', j.get('base_risk'), '->', j.get('risk'))
r = S.post('/api/predict', json={'offering_id': oid, 'overrides': {'gender': 1}}); check('predict rejects unknown feature', r.status_code == 400)
r = S.get('/api/teacher/courses'); check('student blocked from teacher api', r.status_code == 403)
r = S.get(f'/api/teacher/students/{OTHER_STUDENT}'); check('student blocked from profile', r.status_code == 403)

T = as_user(TEACHER, 'teacher')
r = T.get('/api/teacher/courses'); j = r.get_json(); check('teacher courses', r.status_code == 200 and len(j['courses']) >= 1, r.data[:300])
toid = j['courses'][0]['offering_id']; print('   teacher offering', toid, j['courses'][0])
r = T.get(f'/api/teacher/courses/{toid}/insights'); j = r.get_json(); check('insights', r.status_code == 200 and len(j['students']) > 0, r.data[:300])
check('insights sorted desc', all(j['students'][i]['risk_probability'] >= j['students'][i+1]['risk_probability'] for i in range(len(j['students'])-1)))
print('   moved_up', j['moved_up'], 'trend weeks', [t['week_no'] for t in j['trend']], 'top', j['students'][0]['risk_probability'], j['students'][0]['factors'][:1])
sid = j['students'][0]['student_id']
other = [o for o in range(1, N_OFFERINGS + 1) if o != toid]
foreign = None
for o in other:
    if T.get(f'/api/teacher/courses/{o}/insights').status_code == 403: foreign = o; break
check('teacher foreign course -> 403', foreign is not None)
r = T.get(f'/api/teacher/students/{sid}'); j = r.get_json(); check('student profile', r.status_code == 200 and j['courses'], r.data[:300])
r = T.get(f'/api/teacher/courses/{toid}/gradebook'); j = r.get_json(); check('gradebook', r.status_code == 200 and j['grades'], r.data[:200])
gb = j
# оценка
a = next(x for x in gb['assessments'] if x['status'] == 'published')
gr = next(g for g in gb['grades'] if g['assessment_id'] == a['id'])
r = T.put('/api/teacher/grades', json={'assessment_id': a['id'], 'student_id': gr['student_id'], 'score': 50, 'status': 'published'})
check('grade change without reason rejected', r.status_code == 400 and (float(gr['score']) == 50 or r.get_json()['error'] == 'reason_required'), r.data)
r = T.put('/api/teacher/grades', json={'assessment_id': a['id'], 'student_id': gr['student_id'], 'score': 150, 'status': 'published', 'reason': 'x'})
check('score above max rejected', r.status_code == 400)
r = T.put('/api/teacher/grades', json={'assessment_id': a['id'], 'student_id': gr['student_id'], 'score': 77, 'status': 'published', 'reason': REASON})
check('grade changed', r.status_code == 200, r.data)
from backend.db import connect, one
c = connect()
au = one(c, 'SELECT COUNT(*) AS n FROM grade_audit_log WHERE grade_id=%(g)s AND reason=%(r)s', {'g': gr['grade_id'], 'r': REASON})
check('audit row written', au and int(au['n']) == 1)
# вернуть как было
T.put('/api/teacher/grades', json={'assessment_id': a['id'], 'student_id': gr['student_id'], 'score': float(gr['score']), 'status': gr['status'], 'reason': 'откат теста'})
# черновики: студент не должен их видеть
draft = next((g for g in gb['grades'] if g['status'] == 'draft'), None)
if draft:
    st = as_user(draft['student_id'], 'student')
    j = st.get(f"/api/student/courses/{toid}/grades").get_json()
    row = next(x for x in j['assessments'] if x['assessment_id'] == draft['assessment_id'])
    check('student does not see draft score', row['score'] is None, row)
else:
    print('   (нет черновиков в этом курсе)')
# посещаемость
r = T.get(f'/api/teacher/courses/{toid}/meetings'); j = r.get_json(); check('meetings', r.status_code == 200 and j['items'])
mid = next(m['id'] for m in j['items'] if m['marked'] > 0)
r = T.get(f'/api/teacher/meetings/{mid}/attendance'); j = r.get_json(); check('meeting attendance', r.status_code == 200 and j['items'])
first = j['items'][0]
r = T.put(f'/api/teacher/meetings/{mid}/attendance', json={'records': [{'student_id': first['student_id'], 'status': first['status'] or 'present'}, {'student_id': 99999, 'status': 'present'}, {'student_id': first['student_id'], 'status': 'bogus'}]})
check('attendance save skips bad rows', r.status_code == 200 and r.get_json()['saved'] == 1, r.data)
# вмешательство
r = T.post('/api/teacher/interventions', json={'student_id': sid, 'offering_id': toid, 'kind': 'message', 'summary': 'тест'}); check('intervention', r.status_code == 201, r.data)
r = T.post('/api/teacher/interventions', json={'student_id': sid, 'offering_id': foreign, 'kind': 'message', 'summary': 'x'}); check('intervention foreign course -> 403', r.status_code == 403)
r = T.get('/api/teacher/advisees'); check('advisees', r.status_code == 200, r.data[:200])
r = T.get(f'/api/teacher/courses/{toid}/feedback'); check('feedback gated', r.status_code == 200 and r.get_json()['available'] is False, r.data)
# студент анонимный отзыв: чужой опрос / вне периода
r = S.get('/api/student/feedback'); check('feedback list', r.status_code == 200)
# сообщения
r = S.get('/api/messages/conversations'); check('conversations', r.status_code == 200, r.data[:200])
r = S.post('/api/messages/direct', json={'to': ADMIN, 'body': 'hi'}); check('student cannot DM admin', r.status_code == 403)
A = as_user(ADMIN, 'admin')
r = A.get('/api/teacher/courses'); check('admin sees all courses', r.status_code == 200 and len(r.get_json()['courses']) == N_OFFERINGS, r.data[:100])
r = S.post('/api/admin/recompute'); check('recompute admin only', r.status_code == 403)
r = anon.post('/api/auth/login', json={'login_id': 'A001', 'password': 'wrong'}); print('   login ->', r.status_code, r.get_json())
c.rollback(); c.close()
print('\nFAILED:', fails if fails else 'нет')
