"""Силлабус, настраиваемая схема оценивания и материалы курса.

Схема у каждого курса своя: преподаватель сам задаёт категории (Quizzes, Midterm, ...),
их вес, и работы внутри (сколько, сколько баллов, вес, дедлайн). Всё, что считает
риск (признаки, диапазон баллов, текущая оценка), берётся из этих таблиц, поэтому
после изменения схемы риск курса пересчитывается в фоне.
"""
import threading

from flask import Blueprint, jsonify, request

from .access import conn, login_required, me, teaches
from .db import rows, one, run, connect

bp = Blueprint('syllabus', __name__, url_prefix='/api')
ROLES = ('teacher', 'admin')
KINDS = ('assignment', 'quiz', 'midterm', 'final', 'project')
MATERIAL_TYPES = ('pdf', 'slides', 'video', 'link', 'other')
TOL = 0.05


# ------------------------------------------------------------------ вспомогательное

def _can_edit(oid):
    u = me()
    return teaches(conn(), u['id'], oid, u['role'])


def _can_view(oid):
    c = conn(); u = me()
    if u['role'] == 'student':
        return bool(one(c, 'SELECT 1 FROM enrollments WHERE student_id=%(u)s AND offering_id=%(o)s',
                        {'u': u['id'], 'o': oid}))
    return teaches(c, u['id'], oid, u['role'])


def _teacher_id(c, u):
    return u['id'] if one(c, 'SELECT 1 FROM teachers WHERE user_id=%(u)s', {'u': u['id']}) else None


def _scheme(c, oid, published_only=False):
    cats = rows(c, 'SELECT id, name, weight_pct FROM assessment_categories WHERE offering_id=%(o)s ORDER BY id',
                {'o': oid})
    asm = rows(c, f'''
        SELECT a.id, a.category_id, a.title, a.description, a.kind, a.due_at, a.max_score, a.weight_pct, a.status,
               (SELECT COUNT(*) FROM grades g WHERE g.assessment_id = a.id) AS grades_count,
               (SELECT COUNT(*) FROM submissions s WHERE s.assessment_id = a.id) AS submissions_count
        FROM assessments a WHERE a.offering_id=%(o)s {"AND a.status='published'" if published_only else ''}
        ORDER BY a.due_at, a.id''', {'o': oid})
    return cats, asm


def check(c, oid):
    """Что не так со схемой. problems мешают публикации, warnings только предупреждают."""
    cats, asm = _scheme(c, oid)
    problems, warnings = [], []
    total = sum(float(x['weight_pct']) for x in cats)
    if abs(total - 100) > TOL:
        problems.append({'code': 'categories_sum', 'total': round(total, 2),
                         'text': f'Weights of categories add up to {round(total, 2)}%, must be 100%'})
    for k in cats:
        s = sum(float(a['weight_pct']) for a in asm if a['category_id'] == k['id'])
        if not any(a['category_id'] == k['id'] for a in asm):
            warnings.append({'code': 'empty_category', 'category_id': k['id'],
                             'text': f'Category "{k["name"]}" has no assessments yet'})
        elif abs(s - float(k['weight_pct'])) > TOL:
            problems.append({'code': 'category_weights', 'category_id': k['id'], 'total': round(s, 2),
                             'text': f'"{k["name"]}": assessments add up to {round(s, 2)}%, category weight is {float(k["weight_pct"])}%'})
    n = len(asm)
    if n and (n < 3 or n > 15):
        warnings.append({'code': 'unusual_count',
                         'text': 'The risk model was trained on courses with roughly 4-12 graded items; '
                                 'with a very different number its estimates are less reliable'})
    return {'categories_total': round(total, 2), 'problems': problems, 'warnings': warnings, 'valid': not problems}


def _rescale(c, cat_id, old_w, new_w):
    """Вес категории изменился: веса её работ масштабируются пропорционально."""
    a = rows(c, 'SELECT id, weight_pct FROM assessments WHERE category_id=%(k)s ORDER BY id', {'k': cat_id})
    if not a:
        return
    s = sum(float(x['weight_pct']) for x in a)
    for x in a:
        w = float(x['weight_pct']) / s * new_w if s > 0 else new_w / len(a)
        run(c, 'UPDATE assessments SET weight_pct=%(w)s WHERE id=%(i)s', {'w': round(w, 2), 'i': x['id']})
    _fix_rounding(c, cat_id, new_w)


def _split(c, cat_id):
    """Поровну между всеми работами категории."""
    k = one(c, 'SELECT weight_pct FROM assessment_categories WHERE id=%(k)s', {'k': cat_id})
    a = rows(c, 'SELECT id FROM assessments WHERE category_id=%(k)s ORDER BY id', {'k': cat_id})
    if not a:
        return
    w = float(k['weight_pct']) / len(a)
    for x in a:
        run(c, 'UPDATE assessments SET weight_pct=%(w)s WHERE id=%(i)s', {'w': round(w, 2), 'i': x['id']})
    _fix_rounding(c, cat_id, float(k['weight_pct']))


def _fix_rounding(c, cat_id, target):
    a = rows(c, 'SELECT id, weight_pct FROM assessments WHERE category_id=%(k)s ORDER BY id', {'k': cat_id})
    diff = round(target - sum(float(x['weight_pct']) for x in a), 2)
    if a and diff:
        run(c, 'UPDATE assessments SET weight_pct = weight_pct + %(d)s WHERE id=%(i)s', {'d': diff, 'i': a[-1]['id']})


def _kick(oid):
    """Пересчитать риск курса в фоне. Собственное соединение, ответ не ждёт."""
    def job():
        try:
            from .scoring import recompute
            with connect() as cc:
                recompute(cc, notify=False, offering_id=oid)
        except Exception as e:          # не должно ронять запрос
            print('recompute failed:', e)
    threading.Thread(target=job, daemon=True).start()
    return 'started'


def _num(v, name, lo=None, hi=None, required=True):
    if v is None or v == '':
        if required:
            raise ValueError(name)
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(name)
    if (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(name)
    return x


def _bad(field):
    return jsonify(error='bad_request', field=field), 400


# ------------------------------------------------------------------ схема оценивания

@bp.get('/courses/<int:oid>/scheme')
@login_required()
def get_scheme(oid):
    if not _can_view(oid):
        return jsonify(error='forbidden'), 403
    c = conn(); u = me()
    cats, asm = _scheme(c, oid, published_only=(u['role'] == 'student'))
    if u['role'] == 'student':
        for x in asm:                   # студенту счётчики оценок и сдач не нужны
            x.pop('grades_count', None); x.pop('submissions_count', None)
    out = {'categories': cats, 'assessments': asm}
    if u['role'] != 'student':
        out.update(check(c, oid))
    return jsonify(**out)


@bp.post('/teacher/courses/<int:oid>/categories')
@login_required(*ROLES)
def add_category(oid):
    if not _can_edit(oid):
        return jsonify(error='forbidden'), 403
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name or len(name) > 60:
        return _bad('name')
    try:
        w = _num(d.get('weight_pct'), 'weight_pct', 0.01, 100)
    except ValueError as e:
        return _bad(str(e))
    c = conn()
    if one(c, 'SELECT 1 FROM assessment_categories WHERE offering_id=%(o)s AND name=%(n)s', {'o': oid, 'n': name}):
        return jsonify(error='duplicate_name'), 409
    r = run(c, 'INSERT INTO assessment_categories (offering_id, name, weight_pct) VALUES (%(o)s,%(n)s,%(w)s) RETURNING id',
            {'o': oid, 'n': name, 'w': w})
    c.commit()
    return jsonify(id=r[0]['id'], **check(c, oid)), 201


def _cat_guard(cid):
    c = conn()
    k = one(c, 'SELECT id, offering_id, name, weight_pct FROM assessment_categories WHERE id=%(i)s', {'i': cid})
    if not k:
        return None, (jsonify(error='not_found'), 404)
    if not _can_edit(k['offering_id']):
        return None, (jsonify(error='forbidden'), 403)
    return k, None


@bp.put('/teacher/categories/<int:cid>')
@login_required(*ROLES)
def edit_category(cid):
    k, err = _cat_guard(cid)
    if err:
        return err
    c = conn()
    d = request.get_json(force=True, silent=True) or {}
    name = (d.get('name') or k['name']).strip()
    try:
        w = _num(d.get('weight_pct', k['weight_pct']), 'weight_pct', 0.01, 100)
    except ValueError as e:
        return _bad(str(e))
    if name != k['name'] and one(c, 'SELECT 1 FROM assessment_categories WHERE offering_id=%(o)s AND name=%(n)s',
                                 {'o': k['offering_id'], 'n': name}):
        return jsonify(error='duplicate_name'), 409
    run(c, 'UPDATE assessment_categories SET name=%(n)s, weight_pct=%(w)s WHERE id=%(i)s', {'n': name, 'w': w, 'i': cid})
    if abs(w - float(k['weight_pct'])) > 1e-9:
        _rescale(c, cid, float(k['weight_pct']), w)
    c.commit()
    res = check(c, k['offering_id'])
    return jsonify(ok=True, recompute=_kick(k['offering_id']), **res)


@bp.delete('/teacher/categories/<int:cid>')
@login_required(*ROLES)
def del_category(cid):
    k, err = _cat_guard(cid)
    if err:
        return err
    c = conn()
    if one(c, 'SELECT 1 FROM assessments WHERE category_id=%(i)s', {'i': cid}):
        return jsonify(error='category_not_empty'), 409
    run(c, 'DELETE FROM assessment_categories WHERE id=%(i)s', {'i': cid})
    c.commit()
    return jsonify(ok=True, **check(c, k['offering_id']))


# ------------------------------------------------------------------ работы

def _parse_assessment(d, cur=None):
    cur = cur or {}
    title = (d.get('title', cur.get('title')) or '').strip()
    if not title or len(title) > 200:
        raise ValueError('title')
    kind = d.get('kind', cur.get('kind', 'assignment'))
    if kind not in KINDS:
        raise ValueError('kind')
    due = d.get('due_at', cur.get('due_at'))
    if not due:
        raise ValueError('due_at')
    mx = _num(d.get('max_score', cur.get('max_score')), 'max_score', 0.01, 10000)
    return title, kind, due, mx


@bp.post('/teacher/courses/<int:oid>/assessments')
@login_required(*ROLES)
def add_assessment(oid):
    if not _can_edit(oid):
        return jsonify(error='forbidden'), 403
    c = conn(); u = me()
    d = request.get_json(force=True, silent=True) or {}
    k = one(c, 'SELECT id, weight_pct FROM assessment_categories WHERE id=%(k)s AND offering_id=%(o)s',
            {'k': d.get('category_id'), 'o': oid})
    if not k:
        return _bad('category_id')
    try:
        title, kind, due, mx = _parse_assessment(d)
        w = _num(d.get('weight_pct'), 'weight_pct', 0, 100, required=False)
    except ValueError as e:
        return _bad(str(e))
    r = run(c, '''INSERT INTO assessments (offering_id, category_id, title, description, kind, due_at, max_score,
                                           weight_pct, status, created_by)
                  VALUES (%(o)s,%(k)s,%(t)s,%(ds)s,%(kd)s,%(d)s::timestamptz,%(m)s,%(w)s,'draft',%(u)s) RETURNING id''',
            {'o': oid, 'k': k['id'], 't': title, 'ds': d.get('description'), 'kd': kind, 'd': due, 'm': mx,
             'w': w if w is not None else 0, 'u': _teacher_id(c, u)})
    if w is None:
        _split(c, k['id'])               # вес не указан: делим вес категории поровну
    c.commit()
    return jsonify(id=r[0]['id'], **check(c, oid)), 201


def _asm_guard(aid):
    c = conn()
    a = one(c, '''SELECT a.*, (SELECT COUNT(*) FROM grades g WHERE g.assessment_id=a.id) AS gc,
                         (SELECT COUNT(*) FROM submissions s WHERE s.assessment_id=a.id) AS sc
                  FROM assessments a WHERE a.id=%(i)s''', {'i': aid})
    if not a:
        return None, (jsonify(error='not_found'), 404)
    if not _can_edit(a['offering_id']):
        return None, (jsonify(error='forbidden'), 403)
    return a, None


@bp.put('/teacher/assessments/<int:aid>')
@login_required(*ROLES)
def edit_assessment(aid):
    a, err = _asm_guard(aid)
    if err:
        return err
    c = conn()
    d = request.get_json(force=True, silent=True) or {}
    try:
        title, kind, due, mx = _parse_assessment(d, a)
        w = _num(d.get('weight_pct', a['weight_pct']), 'weight_pct', 0, 100)
    except ValueError as e:
        return _bad(str(e))
    cat = d.get('category_id', a['category_id'])
    if int(a['gc']) and (abs(mx - float(a['max_score'])) > 1e-9 or cat != a['category_id']):
        return jsonify(error='has_grades', hint='Max score and category cannot change after grading'), 409
    if not one(c, 'SELECT 1 FROM assessment_categories WHERE id=%(k)s AND offering_id=%(o)s',
               {'k': cat, 'o': a['offering_id']}):
        return _bad('category_id')
    status = d.get('status', a['status'])
    if status not in ('draft', 'published'):
        return _bad('status')
    run(c, '''UPDATE assessments SET title=%(t)s, description=%(ds)s, kind=%(kd)s, due_at=%(d)s::timestamptz,
                     max_score=%(m)s, weight_pct=%(w)s, category_id=%(k)s WHERE id=%(i)s''',
        {'t': title, 'ds': d.get('description', a['description']), 'kd': kind, 'd': due, 'm': mx, 'w': w,
         'k': cat, 'i': aid})
    res = check(c, a['offering_id'])
    if status == 'published' and a['status'] != 'published' and not res['valid']:
        c.rollback()
        return jsonify(error='scheme_invalid', **res), 409      # схема не сходится: публиковать нельзя
    run(c, 'UPDATE assessments SET status=%(s)s WHERE id=%(i)s', {'s': status, 'i': aid})
    c.commit()
    return jsonify(ok=True, recompute=_kick(a['offering_id']), **res)


@bp.delete('/teacher/assessments/<int:aid>')
@login_required(*ROLES)
def del_assessment(aid):
    a, err = _asm_guard(aid)
    if err:
        return err
    c = conn()
    if int(a['gc']) or int(a['sc']):
        return jsonify(error='has_grades', hint='Work with grades or submissions cannot be deleted; set it to draft'), 409
    run(c, 'DELETE FROM assessments WHERE id=%(i)s', {'i': aid})
    c.commit()
    return jsonify(ok=True, recompute=_kick(a['offering_id']), **check(c, a['offering_id']))


@bp.post('/teacher/courses/<int:oid>/recompute')
@login_required(*ROLES)
def recompute_course(oid):
    if not _can_edit(oid):
        return jsonify(error='forbidden'), 403
    return jsonify(recompute=_kick(oid))


# ------------------------------------------------------------------ темы по неделям

@bp.get('/courses/<int:oid>/syllabus')
@login_required()
def get_syllabus(oid):
    if not _can_view(oid):
        return jsonify(error='forbidden'), 403
    return jsonify(weeks=rows(conn(), '''SELECT week_no, topic, description FROM syllabus_weeks
                                          WHERE offering_id=%(o)s ORDER BY week_no''', {'o': oid}))


@bp.put('/teacher/courses/<int:oid>/syllabus')
@login_required(*ROLES)
def put_syllabus(oid):
    """Заменяет весь список недель."""
    if not _can_edit(oid):
        return jsonify(error='forbidden'), 403
    d = request.get_json(force=True, silent=True) or {}
    weeks = d.get('weeks')
    if not isinstance(weeks, list):
        return _bad('weeks')
    seen, clean = set(), []
    for w in weeks:
        try:
            n = int(w.get('week_no'))
        except (TypeError, ValueError):
            return _bad('week_no')
        t = (w.get('topic') or '').strip()
        if n < 1 or n > 52 or n in seen or not t or len(t) > 200:
            return _bad('weeks')
        seen.add(n)
        clean.append((n, t, w.get('description')))
    c = conn()
    run(c, 'DELETE FROM syllabus_weeks WHERE offering_id=%(o)s', {'o': oid})
    for n, t, ds in clean:
        run(c, 'INSERT INTO syllabus_weeks (offering_id, week_no, topic, description) VALUES (%(o)s,%(n)s,%(t)s,%(d)s)',
            {'o': oid, 'n': n, 't': t, 'd': ds})
    c.commit()
    return jsonify(ok=True, saved=len(clean))


# ------------------------------------------------------------------ материалы

@bp.get('/courses/<int:oid>/materials')
@login_required()
def get_materials(oid):
    if not _can_view(oid):
        return jsonify(error='forbidden'), 403
    u = me()
    vis = "AND (visibility='visible' OR (visibility='scheduled' AND visible_from <= now()))" if u['role'] == 'student' else ''
    return jsonify(items=rows(conn(), f'''SELECT id, week_no, title, material_type, url, visibility, visible_from, created_at
                                          FROM materials WHERE offering_id=%(o)s {vis} ORDER BY week_no NULLS LAST, id''',
                              {'o': oid}))


@bp.post('/teacher/courses/<int:oid>/materials')
@login_required(*ROLES)
def add_material(oid):
    if not _can_edit(oid):
        return jsonify(error='forbidden'), 403
    d = request.get_json(force=True, silent=True) or {}
    title = (d.get('title') or '').strip()
    url = (d.get('url') or '').strip()
    mt = d.get('material_type', 'link')
    if not title or not url or mt not in MATERIAL_TYPES or not url.lower().startswith(('http://', 'https://')):
        return _bad('title/url/material_type')
    c = conn(); u = me()
    wk = d.get('week_no')
    r = run(c, '''INSERT INTO materials (offering_id, week_no, title, material_type, url, uploaded_by)
                  VALUES (%(o)s,%(w)s::int,%(t)s,%(m)s,%(u)s,%(up)s) RETURNING id''',
            {'o': oid, 'w': wk, 't': title, 'm': mt, 'u': url, 'up': _teacher_id(c, u)})
    c.commit()
    return jsonify(id=r[0]['id']), 201


@bp.delete('/teacher/materials/<int:mid>')
@login_required(*ROLES)
def del_material(mid):
    c = conn()
    m = one(c, 'SELECT offering_id FROM materials WHERE id=%(i)s', {'i': mid})
    if not m:
        return jsonify(error='not_found'), 404
    if not _can_edit(m['offering_id']):
        return jsonify(error='forbidden'), 403
    run(c, 'DELETE FROM materials WHERE id=%(i)s', {'i': mid})
    c.commit()
    return jsonify(ok=True)
