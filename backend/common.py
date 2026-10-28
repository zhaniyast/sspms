"""Запросы, общие для студенческой и преподавательской частей."""
from .db import rows, one
from .scoring import active_model_id, current_semester, current_week, bundle

LANG = {'kk': 'text_kk', 'ru': 'text_ru', 'en': 'text_en'}


def lang_col(lang):
    return LANG.get(lang, 'text_ru')


def risk_history(c, student_id, offering_id=None):
    mid = active_model_id(c)
    return rows(c, '''
        SELECT offering_id, week_no, risk_probability, risk_level, predicted_score_low, predicted_score_high
        FROM risk_predictions
        WHERE student_id = %(s)s AND model_id = %(m)s AND (%(o)s::int IS NULL OR offering_id = %(o)s::int)
        ORDER BY offering_id, week_no''', {'s': student_id, 'm': mid, 'o': offering_id})


def explanations(c, prediction_ids, lang='ru'):
    if not prediction_ids:
        return {}
    col = lang_col(lang)
    out = {}
    for r in rows(c, f'''SELECT prediction_id, feature, impact, {col} AS text
                         FROM prediction_explanations WHERE prediction_id = ANY(%(ids)s)
                         ORDER BY prediction_id, impact DESC''', {'ids': list(prediction_ids)}):
        out.setdefault(r['prediction_id'], []).append(
            {'feature': r['feature'], 'impact': float(r['impact']), 'text': r['text']})
    return out


def latest_week(c):
    sem = current_semester(c)
    return sem, current_week(sem)


def weighted_grade(c, student_id, offering_id):
    """Текущий процент: набранные взвешенные баллы из веса уже оценённых работ.
    Только опубликованные оценки."""
    return one(c, '''
        SELECT COALESCE(SUM(g.score / a.max_score * a.weight_pct), 0) AS earned,
               COALESCE(SUM(a.weight_pct), 0)                         AS weight_done
        FROM grades g JOIN assessments a ON a.id = g.assessment_id
        WHERE g.student_id = %(s)s AND a.offering_id = %(o)s
          AND g.status = 'published' AND g.score IS NOT NULL''',
               {'s': student_id, 'o': offering_id})


def letter(c, offering_id, percent):
    r = one(c, '''
        SELECT l.letter, l.gpa_points FROM course_offerings o
        JOIN grade_scale_levels l ON l.scale_id = o.grade_scale_id
        WHERE o.id = %(o)s AND l.min_percent <= %(p)s
        ORDER BY l.min_percent DESC LIMIT 1''', {'o': offering_id, 'p': percent})
    return r


def person_name(c, user_id):
    r = one(c, '''SELECT first_name, last_name FROM students WHERE user_id = %(u)s
                  UNION ALL SELECT first_name, last_name FROM teachers WHERE user_id = %(u)s''', {'u': user_id})
    return f"{r['first_name']} {r['last_name']}" if r else None
