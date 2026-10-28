"""
Пересчёт прогнозов. Заполняет четыре таблицы блока прогнозов:
risk_predictions, prediction_explanations, course_risk_snapshots,
student_risk_overall, плюс уведомления risk_up.

Всё в одной транзакции: интерфейс не должен застать снимки одной недели
и прогнозы другой.

Запуск вручную:   python -m backend.scoring
"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .db import rows, one, run
from .features import FEATURES, LABELS, fetch_features

MODEL_PATH = Path(os.environ.get('MODEL_PATH',
                  Path(__file__).resolve().parent.parent / 'models' / 'model_db10.joblib'))
MIN_WEEK = 4          # раньше четвёртой недели прогноз неустойчив

_bundle = None


def bundle():
    global _bundle
    if _bundle is None:
        b = joblib.load(MODEL_PATH)
        assert list(b['features']) == FEATURES, 'порядок признаков в модели и в features.py разошёлся'
        _bundle = b
    return _bundle


def level(p: float, b=None) -> str:
    b = b or bundle()
    return 'high' if p >= b['level_high_from'] else 'medium' if p >= b['level_medium_from'] else 'low'


# ---------------------------------------------------------------- версия модели

def ensure_model_row(conn) -> int:
    """Строка в model_versions. Признаки и пороги лежат в metrics (jsonb):
    схему базы менять не нужно."""
    b = bundle()
    r = one(conn, 'SELECT id FROM model_versions WHERE version = %(v)s', {'v': b['version']})
    meta = {
        'algorithm': 'RandomForestClassifier',
        'features': FEATURES,
        'threshold': b['threshold'],
        'level_medium_from': b['level_medium_from'],
        'level_high_from': b['level_high_from'],
        'prediction_week': b['prediction_week'],
        **{k: v for k, v in b.get('metrics', {}).items()},
    }
    if r:
        return r['id']
    r = run(conn, '''INSERT INTO model_versions (version, trained_at, metrics, description)
                     VALUES (%(v)s, now(), %(m)s::jsonb, %(d)s) RETURNING id''',
            {'v': b['version'], 'm': json.dumps(meta),
             'd': 'RandomForest, 10 признаков, прогноз с 4-й недели. Демографии нет.'})
    return r[0]['id']


def active_model_id(conn) -> int | None:
    r = one(conn, 'SELECT id FROM model_versions WHERE version = %(v)s', {'v': bundle()['version']})
    return r['id'] if r else None


# ---------------------------------------------------------------- семестр и неделя

def current_semester(conn):
    return one(conn, '''SELECT id, start_date, total_weeks FROM semesters
                        ORDER BY is_current DESC, start_date DESC LIMIT 1''')


def current_week(sem, today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    start = sem['start_date']
    if isinstance(start, str):
        start = dt.date.fromisoformat(start)
    w = (today - start).days // 7 + 1
    return max(1, min(int(w), int(sem['total_weeks'])))


# ---------------------------------------------------------------- объяснения

def explain(model, X: np.ndarray, base: np.ndarray, medians: np.ndarray, top=3):
    """Замена одного значения на медиану когорты. impact > 0: признак поднимает риск."""
    impacts = np.zeros_like(X)
    for j in range(X.shape[1]):
        Xs = X.copy()
        Xs[:, j] = medians[j]
        impacts[:, j] = base - model.predict_proba(pd.DataFrame(Xs, columns=FEATURES))[:, 1]
    out = []
    for i in range(X.shape[0]):
        order = np.argsort(-impacts[i])[:top]
        out.append([(FEATURES[j], float(impacts[i, j]), float(X[i, j]), float(medians[j]))
                    for j in order if impacts[i, j] > 0.005])
    return out


def _fmt(v: float) -> str:
    return f'{v:.0f}' if abs(v - round(v)) < 0.05 else f'{v:.1f}'


def texts(feature: str, value: float, avg: float):
    kk, ru, en = LABELS[feature]
    if feature == 'submitted_share':           # доля 0..1 показываем в процентах
        t, a = f'{value * 100:.0f}%', f'{avg * 100:.0f}%'
    else:
        t, a = _fmt(value), _fmt(avg)
    return (f'{kk}: {t} (курс орташасы {a})',
            f'{ru}: {t} (в среднем по курсу {a})',
            f'{en}: {t} (course average {a})')


# ---------------------------------------------------------------- проекция баллов

PROJ_SQL = """
SELECT a.offering_id,
       SUM(a.weight_pct) AS weight_due
FROM assessments a
JOIN course_offerings o ON o.id = a.offering_id
JOIN semesters s ON s.id = o.semester_id
WHERE a.status = 'published' AND o.semester_id = %(sem)s::int
  AND a.due_at <= (s.start_date + (%(week)s::int * 7) * INTERVAL '1 day')::timestamptz
GROUP BY a.offering_id
"""


def score_range(points_earned: float, weight_due: float, spread=0.15):
    """Арифметика по схеме оценивания, не машинное обучение: если остальное
    выполнить так же, как уже выполненное, ± spread."""
    if weight_due <= 0:
        return None, None
    pct = min(max(points_earned / weight_due, 0), 1)
    rem = max(100 - weight_due, 0)
    low = points_earned + rem * max(pct - spread, 0)
    high = points_earned + rem * min(pct + spread, 1)
    return round(low, 2), round(high, 2)


# ---------------------------------------------------------------- пересчёт

def _bulk(conn, head, tpl, data, tail='', chunk=500):
    for i in range(0, len(data), chunk):
        part = data[i:i + chunk]
        flat, vals = [], []
        for r in part:
            vals.append(tpl)
            flat.extend(r)
        run(conn, f'{head} VALUES ' + ','.join(vals) + f' {tail}', flat)


def recompute(conn, semester_id: int | None = None, upto_week: int | None = None,
              today: dt.date | None = None, notify=True, offering_id: int | None = None) -> dict:
    b = bundle()
    model = b['model']
    mid = ensure_model_row(conn)
    sem = current_semester(conn) if semester_id is None else one(
        conn, 'SELECT id, start_date, total_weeks FROM semesters WHERE id=%(i)s', {'i': semester_id})
    sid = sem['id']
    now_week = upto_week or current_week(sem, today)
    summary = {'model_id': mid, 'semester_id': sid, 'weeks': [], 'predictions': 0}

    prev_level: dict = {}           # (student, offering) -> уровень предыдущей недели
    new_levels: dict = {}
    for w in range(MIN_WEEK, now_week + 1):
        keys, M = fetch_features(conn, sid, w, offering_id)
        if not keys:
            continue
        X = np.array(M, dtype=float)
        p = model.predict_proba(pd.DataFrame(X, columns=FEATURES))[:, 1]
        med = np.median(X, axis=0)
        expl = explain(model, X, p, med)
        pw = {r['offering_id']: float(r['weight_due']) for r in
              rows(conn, PROJ_SQL, {'sem': sid, 'week': w})}
        pe = FEATURES.index('points_earned')

        pred_rows = []
        for (stu, off, wk), prob, x in zip(keys, p, X):
            lo, hi = score_range(float(x[pe]), pw.get(off, 0))
            pred_rows.append((stu, off, wk, mid, round(float(prob), 4), level(float(prob), b), lo, hi))
        _bulk(conn,
              'INSERT INTO risk_predictions (student_id, offering_id, week_no, model_id, '
              'risk_probability, risk_level, predicted_score_low, predicted_score_high)',
              '(%s,%s,%s,%s,%s,%s,%s,%s)', pred_rows,
              'ON CONFLICT (student_id, offering_id, week_no, model_id) DO UPDATE SET '
              'risk_probability = EXCLUDED.risk_probability, risk_level = EXCLUDED.risk_level, '
              'predicted_score_low = EXCLUDED.predicted_score_low, '
              'predicted_score_high = EXCLUDED.predicted_score_high, created_at = now()')

        ids = {(r['student_id'], r['offering_id']): r['id'] for r in rows(
            conn, 'SELECT id, student_id, offering_id FROM risk_predictions '
                  'WHERE model_id=%(m)s AND week_no=%(w)s AND (%(o)s::int IS NULL OR offering_id = %(o)s::int)',
            {'m': mid, 'w': w, 'o': offering_id})}
        run(conn, 'DELETE FROM prediction_explanations WHERE prediction_id IN '
                  '(SELECT id FROM risk_predictions WHERE model_id=%(m)s AND week_no=%(w)s '
                  'AND (%(o)s::int IS NULL OR offering_id = %(o)s::int))',
            {'m': mid, 'w': w, 'o': offering_id})
        ex_rows = []
        for (stu, off, _), items in zip(keys, expl):
            pid = ids[(stu, off)]
            for f, imp, val, avg in items:
                kk, ru, en = texts(f, val, avg)
                ex_rows.append((pid, f, round(imp, 4), kk, ru, en))
        _bulk(conn, 'INSERT INTO prediction_explanations (prediction_id, feature, impact, '
                    'text_kk, text_ru, text_en)', '(%s,%s,%s,%s,%s,%s)', ex_rows)

        # снимки курсов
        by_off: dict = {}
        for (stu, off, _), prob in zip(keys, p):
            by_off.setdefault(off, []).append(float(prob))
        snap = []
        for off, ps in by_off.items():
            lv = [level(x, b) for x in ps]
            snap.append((off, w, lv.count('low'), lv.count('medium'), lv.count('high'),
                         round(statistics.fmean(ps), 4)))
        _bulk(conn, 'INSERT INTO course_risk_snapshots (offering_id, week_no, low_count, '
                    'medium_count, high_count, avg_risk)', '(%s,%s,%s,%s,%s,%s)', snap,
              'ON CONFLICT (offering_id, week_no) DO UPDATE SET low_count=EXCLUDED.low_count, '
              'medium_count=EXCLUDED.medium_count, high_count=EXCLUDED.high_count, '
              'avg_risk=EXCLUDED.avg_risk')

        # общий риск студента: максимум по курсам. Взвешенное среднее размывает
        # студента, который валит один курс из шести, а он и нужен эдвайзеру.
        top: dict = {}
        for (stu, off, _), prob in zip(keys, p):
            top[stu] = max(top.get(stu, 0.0), float(prob))
        if offering_id is not None:
            # пересчитан один курс: максимум берём по всем курсам студента из базы
            top = {r['student_id']: float(r['m']) for r in rows(conn, '''
                SELECT p.student_id, MAX(p.risk_probability) AS m FROM risk_predictions p
                JOIN course_offerings o ON o.id = p.offering_id
                WHERE p.model_id=%(m)s AND p.week_no=%(w)s AND o.semester_id=%(s)s
                  AND p.student_id IN (SELECT student_id FROM enrollments WHERE offering_id=%(o)s)
                GROUP BY p.student_id''', {'m': mid, 'w': w, 's': sid, 'o': offering_id})}
        _bulk(conn, 'INSERT INTO student_risk_overall (student_id, semester_id, week_no, '
                    'risk_probability, risk_level, method)', '(%s,%s,%s,%s,%s,%s)',
              [(s, sid, w, round(v, 4), level(v, b), 'max_over_courses') for s, v in top.items()],
              'ON CONFLICT (student_id, semester_id, week_no) DO UPDATE SET '
              'risk_probability=EXCLUDED.risk_probability, risk_level=EXCLUDED.risk_level, '
              'method=EXCLUDED.method')

        prev_level, new_levels = new_levels, {(s, o): level(float(x), b) for (s, o, _), x in zip(keys, p)}
        summary['weeks'].append(w)
        summary['predictions'] += len(keys)

    if notify and new_levels and prev_level:
        summary['notifications'] = _notify_risk_up(conn, prev_level, new_levels, now_week)
    conn.commit()
    return summary


ORDER = {'low': 0, 'medium': 1, 'high': 2}


def _notify_risk_up(conn, prev, cur, week) -> int:
    names = {r['id']: r['name'] for r in rows(conn, 'SELECT o.id, c.name FROM course_offerings o '
                                                    'JOIN courses c ON c.id = o.course_id')}
    teacher = {r['id']: r['teacher_id'] for r in rows(conn, 'SELECT id, teacher_id FROM course_offerings')}
    out = []
    risen: dict = {}
    for (stu, off), lv in cur.items():
        if ORDER[lv] > ORDER.get(prev.get((stu, off), 'low'), 0) and lv != 'low':
            title = f'Риск вырос до «{lv}» по курсу «{names[off]}» (неделя {week})'
            out.append((stu, title, f'/student/risk?offering={off}'))
            risen[off] = risen.get(off, 0) + 1
    # преподавателю одно сообщение на курс, а не по одному на студента
    for off, n in risen.items():
        t = teacher.get(off)
        if t:
            out.append((t, f'Курс «{names[off]}», неделя {week}: у {n} студентов вырос риск',
                        f'/teacher/courses/{off}/insights'))
    if not out:
        return 0
    have = {(r['user_id'], r['title']) for r in rows(
        conn, "SELECT user_id, title FROM notifications WHERE type='risk_up'")}
    fresh = [(u, 'risk_up', t, l) for u, t, l in out if (u, t) not in have]
    if fresh:
        _bulk(conn, 'INSERT INTO notifications (user_id, type, title, link)', '(%s,%s,%s,%s)', fresh)
    return len(fresh)


if __name__ == '__main__':
    from .db import connect
    with connect() as c:
        print(recompute(c))
