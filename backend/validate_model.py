"""Проверка модели риска на данных портала (задача I, риск R4).

    python -m backend.validate_model
    python -m backend.validate_model --pass-mark 50 --target-recall 0.60

Что считается.
Модель обучена на OULAD, поэтому её нужно проверить на данных самого портала.
Для каждой недели прогноза k берётся прогноз, сделанный по данным до конца недели k,
и сравнивается с тем, что случилось ПОСЛЕ этой недели:

  * если в базе уже есть итоги семестра (enrollments.status = completed / failed / dropped),
    студент считается «в зоне риска», когда курс не пройден (failed или dropped);
  * пока итогов нет, берётся результат по работам со сроком сдачи после недели k:
    взвешенный процент ниже проходного балла (--pass-mark, по умолчанию 50).
    Несданная работа, по которой у группы уже выставлены оценки, считается за 0.

Так в оценку качества не попадает информация, которой модель в момент прогноза не видела.

Результат печатается и пишется в docs/portal_validation.csv. Вторая таблица,
docs/portal_feature_scale.csv, показывает, какие признаки портала выходят за диапазон,
на котором модель обучалась.

Ограничение: демо-база синтетическая, поэтому цифры показывают, что расчёт и порог
работают на данных портала, но не заменяют проверку на настоящих итогах семестра.
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from .db import connect, rows, one
from .features import FEATURES, fetch_features
from .scoring import active_model_id, bundle, current_semester, current_week

ROOT = Path(__file__).resolve().parent.parent
MIN_ROWS = 30            # меньше строк — метрики слишком шумные, неделя помечается


def _later_work(c, sem):
    """Результаты по опубликованным оценкам: (student, offering) -> [(неделя срока, вес, доля балла)]."""
    data = rows(c, '''
        WITH asm AS (
            SELECT a.id, a.offering_id, a.max_score, a.weight_pct,
                   ((a.due_at::date - %(start)s::date) / 7 + 1) AS wk
            FROM assessments a JOIN course_offerings o ON o.id = a.offering_id
            WHERE o.semester_id = %(sem)s AND a.status = 'published' AND a.due_at <= now() AND a.weight_pct > 0
              AND EXISTS (SELECT 1 FROM grades g WHERE g.assessment_id = a.id AND g.status = 'published'))
        SELECT e.student_id, e.offering_id, asm.wk, asm.weight_pct,
               COALESCE(g.score, 0) / asm.max_score AS share
        FROM enrollments e
        JOIN asm ON asm.offering_id = e.offering_id
        LEFT JOIN grades g ON g.assessment_id = asm.id AND g.student_id = e.student_id
                          AND g.status = 'published' AND g.score IS NOT NULL
        WHERE e.status = 'enrolled' ''', {'sem': sem['id'], 'start': str(sem['start_date'])[:10]})
    out = {}
    for r in data:
        out.setdefault((r['student_id'], r['offering_id']), []).append(
            (int(r['wk']), float(r['weight_pct']), float(r['share'])))
    return out


def _final_status(c, sem):
    data = rows(c, '''SELECT e.student_id, e.offering_id, e.status FROM enrollments e
                      JOIN course_offerings o ON o.id = e.offering_id
                      WHERE o.semester_id = %(sem)s AND e.status <> 'enrolled' ''', {'sem': sem['id']})
    return {(r['student_id'], r['offering_id']): int(r['status'] in ('failed', 'dropped')) for r in data}


def metrics(y, p, threshold):
    y, p = np.asarray(y), np.asarray(p)
    flag = p >= threshold
    tp, fp, fn = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum()), int((~flag & (y == 1)).sum())
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    auc = float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else None
    return {'n': len(y), 'at_risk': int(y.sum()), 'flagged': int(flag.sum()), 'roc_auc': auc,
            'recall': recall, 'precision': precision, 'f1': f1}


def threshold_for_recall(y, p, target):
    """Самый высокий порог, при котором recall не ниже target. None, если нет положительных."""
    y, p = np.asarray(y), np.asarray(p)
    pos = np.sort(p[y == 1])[::-1]
    if len(pos) == 0:
        return None
    need = int(np.ceil(target * len(pos)))
    return float(pos[max(need, 1) - 1])


def validate(c, pass_mark=50.0, target_recall=0.60):
    b = bundle()
    sem = current_semester(c)
    now_week = current_week(sem)
    mid = active_model_id(c)
    preds = rows(c, '''SELECT student_id, offering_id, week_no, risk_probability FROM risk_predictions
                       WHERE model_id = %(m)s''', {'m': mid})
    if not preds:
        return {'error': 'Прогнозов нет. Сначала запустите: python -m backend.scoring'}
    final = _final_status(c, sem)
    mode = 'final' if final else 'later_work'
    work = {} if final else _later_work(c, sem)
    by_week = {}
    for r in preds:
        by_week.setdefault(int(r['week_no']), []).append(r)
    out = []
    for k in sorted(by_week):
        y, p = [], []
        for r in by_week[k]:
            key = (r['student_id'], r['offering_id'])
            if final:
                if key not in final:
                    continue
                label = final[key]
            else:
                later = [(w, s) for wk, w, s in work.get(key, []) if wk > k]
                wsum = sum(w for w, _ in later)
                if not wsum:
                    continue
                label = int(sum(w * s for w, s in later) / wsum * 100 < pass_mark)
            y.append(label); p.append(float(r['risk_probability']))
        if not y:
            continue
        m = metrics(y, p, b['threshold'])
        m.update(week=k, outcome=mode, threshold=round(float(b['threshold']), 3),
                 threshold_for_target=threshold_for_recall(y, p, target_recall),
                 note='мало строк' if m['n'] < MIN_ROWS else ('нет студентов в зоне риска' if not m['at_risk'] else ''))
        out.append(m)
    return {'model': b['version'], 'prediction_week': int(b.get('prediction_week', 6)), 'current_week': now_week,
            'outcome': mode, 'pass_mark': pass_mark, 'target_recall': target_recall, 'weeks': out,
            'train_metrics': {k: float(v) for k, v in b.get('metrics', {}).items()}}


def feature_scale(c, week):
    """Сравнить диапазон признаков портала с диапазоном, на котором модель обучалась."""
    train_csv = ROOT / 'data' / 'processed' / 'final_model_data.csv'
    if not train_csv.exists():
        return None
    with open(train_csv, encoding='utf-8') as f:
        rd = list(csv.DictReader(f))
    sem = current_semester(c)
    _, matrix = fetch_features(c, sem['id'], week)
    if not matrix:
        return None
    x = np.asarray(matrix, dtype=float)
    out = []
    for i, name in enumerate(FEATURES):
        tr = np.asarray([float(r[name]) for r in rd if r.get(name) not in (None, '')])
        lo, hi = np.percentile(tr, [1, 99])
        col = x[:, i]
        outside = float(((col < lo) | (col > hi)).mean())
        out.append({'feature': name, 'train_p1': round(float(lo), 2), 'train_median': round(float(np.median(tr)), 2),
                    'train_p99': round(float(hi), 2), 'portal_min': round(float(col.min()), 2),
                    'portal_median': round(float(np.median(col)), 2), 'portal_max': round(float(col.max()), 2),
                    'portal_outside_train_range_pct': round(outside * 100, 1)})
    return out


def _fmt(v, nd=3):
    return '   -  ' if v is None else f'{v:.{nd}f}'


def main(argv=None):
    ap = argparse.ArgumentParser(description='Проверка модели риска на данных портала')
    ap.add_argument('--pass-mark', type=float, default=50.0, help='проходной процент (по умолчанию 50)')
    ap.add_argument('--target-recall', type=float, default=0.60, help='минимально допустимый recall (риск R4)')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'portal_validation.csv'))
    a = ap.parse_args(argv)
    with connect() as c:
        res = validate(c, a.pass_mark, a.target_recall)
        if 'error' in res:
            print(res['error']); return 1
        scale = feature_scale(c, min(res['prediction_week'], res['current_week']))
    how = 'итоговый статус курса' if res['outcome'] == 'final' else f"работы после недели прогноза, проходной балл {a.pass_mark:g}%"
    print(f"Модель {res['model']}, текущая неделя {res['current_week']}. Исход: {how}")
    print(f"На обучении (OULAD): recall {res['train_metrics'].get('recall', float('nan')):.3f}, "
          f"ROC-AUC {res['train_metrics'].get('roc_auc', float('nan')):.3f}\n")
    print('week      n  at_risk  flagged  roc_auc  recall  precision     f1   note')
    for m in res['weeks']:
        print(f"{m['week']:>4} {m['n']:>6} {m['at_risk']:>8} {m['flagged']:>8}   {_fmt(m['roc_auc'])}  {_fmt(m['recall'])}"
              f"     {_fmt(m['precision'])}  {_fmt(m['f1'])}   {m['note']}")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    cols = ['week', 'outcome', 'n', 'at_risk', 'flagged', 'threshold', 'roc_auc', 'recall', 'precision', 'f1',
            'threshold_for_target', 'note']
    with open(a.out, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(cols)
        for m in res['weeks']:
            w.writerow(['' if m[k] is None else (round(m[k], 4) if isinstance(m[k], float) else m[k]) for k in cols])
    print(f'\nТаблица сохранена: {a.out}')

    main_week = next((m for m in res['weeks'] if m['week'] == res['prediction_week']), None) or \
                (res['weeks'][0] if res['weeks'] else None)
    if not main_week or main_week['recall'] is None:
        print('\nR4: проверить нельзя, для недели прогноза пока нет студентов с плохим исходом.')
    elif main_week['recall'] < a.target_recall:
        t = main_week['threshold_for_target']
        print(f"\nR4 СРАБОТАЛ: recall на неделе {main_week['week']} = {main_week['recall']:.3f}, ниже {a.target_recall:.2f}. "
              f"Порог модели {main_week['threshold']}; чтобы recall был не ниже цели, порог нужно снизить до {t:.3f}.")
    else:
        print(f"\nR4 не сработал: recall на неделе {main_week['week']} = {main_week['recall']:.3f}, "
              f"не ниже {a.target_recall:.2f}. Порог менять не нужно.")

    if scale:
        p = Path(a.out).with_name('portal_feature_scale.csv')
        with open(p, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(scale[0])); w.writeheader(); w.writerows(scale)
        bad = [s for s in scale if s['portal_outside_train_range_pct'] > 20]
        print(f'\nШкала признаков сохранена: {p}')
        if bad:
            print('Признаки, которые в портале часто выходят за диапазон обучения (больше 20% строк):')
            for s in bad:
                print(f"  {s['feature']}: обучение {s['train_p1']}..{s['train_p99']}, "
                      f"портал {s['portal_min']}..{s['portal_max']} ({s['portal_outside_train_range_pct']}% вне диапазона)")
        else:
            print('Все признаки портала лежат в диапазоне, на котором модель обучалась.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
