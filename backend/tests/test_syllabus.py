"""Проверка схемы оценивания и силлабуса. Меняет данные и в конце возвращает их как было.
Запуск в песочнице: PGDATABASE=portal_new python backend/tests/test_syllabus.py"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
try:
    import psycopg  # noqa
except ImportError:
    import psycopg_shim; psycopg_shim.install()
import warnings; warnings.filterwarnings('ignore')
from backend.app import create_app
from backend.db import connect, one, rows, run

app = create_app(); app.testing = True
c = connect()
t = one(c, '''SELECT o.id AS oid, o.teacher_id AS tid FROM course_offerings o JOIN enrollments e ON e.offering_id=o.id
              GROUP BY o.id, o.teacher_id ORDER BY COUNT(*) DESC, o.id LIMIT 1''')
OID, TID = t['oid'], t['tid']
STUDENT = one(c, 'SELECT student_id FROM enrollments WHERE offering_id=%(o)s LIMIT 1', {'o': OID})['student_id']
OTHER_T = one(c, 'SELECT user_id FROM teachers WHERE user_id<>%(t)s LIMIT 1', {'t': TID})['user_id']
snap_cat = rows(c, 'SELECT id, weight_pct FROM assessment_categories WHERE offering_id=%(o)s', {'o': OID})
snap_asm = rows(c, 'SELECT id, weight_pct FROM assessments WHERE offering_id=%(o)s', {'o': OID})
c.rollback()
fails = []


def user(uid, role):
    cl = app.test_client()
    with cl.session_transaction() as s:
        s['uid'], s['role'] = uid, role
    return cl


def ok(name, cond, extra=''):
    print(('ok   ' if cond else 'FAIL ') + name, extra if not cond else '')
    if not cond: fails.append(name)


T, S, O = user(TID, 'teacher'), user(STUDENT, 'student'), user(OTHER_T, 'teacher')
created_cat = created_asm = None
try:
    r = T.get(f'/api/courses/{OID}/scheme'); j = r.get_json()
    ok('teacher scheme', r.status_code == 200 and j['valid'] and abs(j['categories_total'] - 100) < 0.06, r.data[:300])
    print('   categories', [(k['name'], float(k['weight_pct'])) for k in j['categories']], 'assessments', len(j['assessments']))
    r = S.get(f'/api/courses/{OID}/scheme'); j2 = r.get_json()
    ok('student scheme: published only, no problems field', r.status_code == 200 and 'problems' not in j2 and 'grades_count' not in j2['assessments'][0] and all(a['status'] == 'published' for a in j2['assessments']), r.data[:200])
    ok('other teacher -> 403', O.get(f'/api/courses/{OID}/scheme').status_code == 403)
    ok('other teacher cannot add category', O.post(f'/api/teacher/courses/{OID}/categories', json={'name': 'X', 'weight_pct': 5}).status_code == 403)
    ok('student cannot add category', S.post(f'/api/teacher/courses/{OID}/categories', json={'name': 'X', 'weight_pct': 5}).status_code == 403)

    X = j['categories'][0]
    r = T.post(f'/api/teacher/courses/{OID}/categories', json={'name': 'ZZ Quizzes', 'weight_pct': 0}); ok('weight 0 rejected', r.status_code == 400)
    r = T.post(f'/api/teacher/courses/{OID}/categories', json={'name': 'ZZ Quizzes', 'weight_pct': 10}); jj = r.get_json()
    ok('add category -> sum invalid', r.status_code == 201 and not jj['valid'], r.data[:300]); created_cat = jj.get('id')
    r = T.post(f'/api/teacher/courses/{OID}/categories', json={'name': 'ZZ Quizzes', 'weight_pct': 5}); ok('duplicate name -> 409', r.status_code == 409)

    r = T.post(f'/api/teacher/courses/{OID}/assessments', json={'category_id': created_cat, 'title': 'ZZ Quiz 1', 'kind': 'quiz',
                                                              'due_at': '2026-09-20T10:00:00+05:00', 'max_score': 20})
    ok('add assessment', r.status_code == 201, r.data[:300]); created_asm = r.get_json().get('id')
    r = T.post(f'/api/teacher/courses/{OID}/assessments', json={'category_id': created_cat, 'title': 'ZZ Quiz 2', 'kind': 'quiz',
                                                              'due_at': '2026-09-27T10:00:00+05:00', 'max_score': 20})
    a2 = r.get_json().get('id')
    sch = T.get(f'/api/courses/{OID}/scheme').get_json()
    ws = [float(a['weight_pct']) for a in sch['assessments'] if a['category_id'] == created_cat]
    ok('equal split 5+5', sorted(ws) == [5.0, 5.0], ws)
    r = T.post(f'/api/teacher/courses/{OID}/assessments', json={'category_id': created_cat, 'title': '', 'kind': 'quiz', 'due_at': '2026-09-27', 'max_score': 5})
    ok('empty title rejected', r.status_code == 400)
    r = T.post(f'/api/teacher/courses/{OID}/assessments', json={'category_id': created_cat, 'title': 'k', 'kind': 'exam', 'due_at': '2026-09-27', 'max_score': 5})
    ok('bad kind rejected', r.status_code == 400)

    r = T.put(f'/api/teacher/assessments/{created_asm}', json={'status': 'published'})
    ok('publish blocked while sum != 100', r.status_code == 409 and r.get_json()['error'] == 'scheme_invalid', r.data[:300])
    xw = float(X['weight_pct'])
    r = T.put(f'/api/teacher/categories/{X["id"]}', json={'weight_pct': xw - 10}); jj = r.get_json()
    ok('rescale existing category', r.status_code == 200 and jj['valid'], r.data[:400])
    r = T.put(f'/api/teacher/assessments/{created_asm}', json={'status': 'published'}); ok('publish when valid', r.status_code == 200, r.data[:300])
    r = T.put(f'/api/teacher/assessments/{a2}', json={'status': 'published'}); ok('publish second', r.status_code == 200)
    time.sleep(1)
    r = T.get(f'/api/teacher/courses/{OID}/gradebook'); ok('gradebook sees new work', any(a['title'] == 'ZZ Quiz 1' for a in r.get_json()['assessments']))
    r = S.get(f'/api/student/courses/{OID}/grades'); ok('student sees published new work', any(a['title'] == 'ZZ Quiz 1' for a in r.get_json()['assessments']))
    r = T.put('/api/teacher/grades', json={'assessment_id': created_asm, 'student_id': STUDENT, 'score': 15, 'status': 'published'}); ok('grade the new work', r.status_code == 200, r.data[:200])
    r = T.delete(f'/api/teacher/assessments/{created_asm}'); ok('cannot delete graded work', r.status_code == 409)
    r = T.put(f'/api/teacher/assessments/{created_asm}', json={'max_score': 40}); ok('cannot change max after grading', r.status_code == 409)
    r = T.delete(f'/api/teacher/categories/{created_cat}'); ok('cannot delete non-empty category', r.status_code == 409)

    r = T.put(f'/api/teacher/courses/{OID}/syllabus', json={'weeks': [{'week_no': 1, 'topic': 'Intro'}, {'week_no': 2, 'topic': 'SQL', 'description': 'joins'}]})
    ok('put syllabus', r.status_code == 200 and r.get_json()['saved'] == 2, r.data[:200])
    r = T.put(f'/api/teacher/courses/{OID}/syllabus', json={'weeks': [{'week_no': 1, 'topic': 'a'}, {'week_no': 1, 'topic': 'b'}]}); ok('duplicate week rejected', r.status_code == 400)
    r = S.get(f'/api/courses/{OID}/syllabus'); ok('student reads syllabus', r.status_code == 200 and len(r.get_json()['weeks']) == 2)
    r = S.put(f'/api/teacher/courses/{OID}/syllabus', json={'weeks': []}); ok('student cannot write syllabus', r.status_code == 403)
    r = T.post(f'/api/teacher/courses/{OID}/materials', json={'title': 'Slides 1', 'url': 'javascript:alert(1)', 'material_type': 'pdf'}); ok('js url rejected', r.status_code == 400)
    r = T.post(f'/api/teacher/courses/{OID}/materials', json={'title': 'Slides 1', 'url': 'https://example.com/a.pdf', 'material_type': 'pdf', 'week_no': 1}); ok('add material', r.status_code == 201, r.data[:200]); mid = r.get_json().get('id')
    r = S.get(f'/api/courses/{OID}/materials'); ok('student sees material', any(m['id'] == mid for m in r.get_json()['items']))
    r = T.delete(f'/api/teacher/materials/{mid}'); ok('delete material', r.status_code == 200)
finally:
    time.sleep(2)
    c = connect()
    run(c, "SET session_replication_role = replica")
    run(c, 'DELETE FROM grade_audit_log WHERE grade_id IN (SELECT id FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE title LIKE %(p)s))', {'p': 'ZZ %'})
    run(c, 'DELETE FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE title LIKE %(p)s)', {'p': 'ZZ %'})
    run(c, 'DELETE FROM assessments WHERE title LIKE %(p)s', {'p': 'ZZ %'})
    run(c, 'DELETE FROM assessment_categories WHERE name LIKE %(p)s', {'p': 'ZZ %'})
    for k in snap_cat: run(c, 'UPDATE assessment_categories SET weight_pct=%(w)s WHERE id=%(i)s', {'w': k['weight_pct'], 'i': k['id']})
    for a in snap_asm: run(c, 'UPDATE assessments SET weight_pct=%(w)s WHERE id=%(i)s', {'w': a['weight_pct'], 'i': a['id']})
    run(c, 'DELETE FROM syllabus_weeks WHERE offering_id=%(o)s', {'o': OID})
    c.commit()
print('\nFAILED:' if fails else '\nALL PASSED', fails or '')
