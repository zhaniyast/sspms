"""
Сборка признаков модели из базы портала.

Десять признаков, все считаются из таблиц, которые уже есть в схеме.
Кликовых признаков из OULAD здесь нет намеренно: проверено, что без них
модель работает не хуже (recall 0.714 против 0.700), поэтому добавлять
колонки в weekly_activity не понадобилось.

Главное правило: признаки описывают состояние на КОНЕЦ НЕДЕЛИ N.
Ничего, что произошло позже, попасть в них не должно.
"""
from __future__ import annotations

FEATURES = [
    'num_of_prev_attempts',
    'studied_credits',
    'total_materials',
    'silent_weeks',
    'n_submitted',
    'mean_score',
    'min_score',
    'points_earned',
    'n_missed',
    'submitted_share',
]

# Подписи для интерфейса. Ключ хранится в prediction_explanations.feature,
# переводы берутся отсюда, а не из базы.
LABELS = {
    'num_of_prev_attempts': ('Бұл курсты бұрын алу саны',
                             'попыток пройти этот курс раньше',
                             'previous attempts at this course'),
    'studied_credits':      ('Семестрдегі кредит жүктемесі',
                             'кредитная нагрузка в семестре',
                             'credit load this term'),
    'total_materials':      ('Ашылған материалдар саны',
                             'открыто материалов курса',
                             'course materials opened'),
    'silent_weeks':         ('Белсенділіксіз апталар',
                             'недель без активности',
                             'weeks with no activity'),
    'n_submitted':          ('Тапсырылған жұмыстар',
                             'сдано работ',
                             'assignments submitted'),
    'mean_score':           ('Орташа балл',
                             'средний балл',
                             'average score so far'),
    'min_score':            ('Ең төмен балл',
                             'минимальный балл',
                             'lowest score so far'),
    'points_earned':        ('Жиналған салмақты балл',
                             'набрано взвешенных баллов',
                             'weighted points earned'),
    'n_missed':             ('Тапсырылмаған жұмыстар',
                             'пропущено работ',
                             'assignments missed'),
    'submitted_share':      ('Тапсырылған жұмыстардың үлесі',
                             'доля сданных работ',
                             'share of work submitted'),
}

# Единственный запрос. Возвращает по строке на пару (студент, курс)
# для одной недели одного семестра.
#
# Параметры: %(semester_id)s, %(week)s, необязательно %(offering_id)s
FEATURE_SQL = """
WITH sem AS (
    SELECT id, start_date
    FROM semesters
    WHERE id = %(semester_id)s::int
),
-- конец недели N: последняя секунда седьмого дня
cut AS (
    SELECT (start_date + (%(week)s::int * 7) * INTERVAL '1 day')::timestamptz AS at
    FROM sem
),
-- кто учится в этом семестре
roster AS (
    SELECT e.student_id, e.offering_id, c.credits
    FROM enrollments e
    JOIN course_offerings o ON o.id = e.offering_id
    JOIN courses c          ON c.id = o.course_id
    WHERE o.semester_id = %(semester_id)s::int
      AND e.status = 'enrolled'
      AND (%(offering_id)s::int IS NULL OR e.offering_id = %(offering_id)s::int)
),
-- кредитная нагрузка: по всем курсам семестра, не только по этому
load AS (
    SELECT e.student_id, SUM(c.credits)::numeric AS studied_credits
    FROM enrollments e
    JOIN course_offerings o ON o.id = e.offering_id
    JOIN courses c          ON c.id = o.course_id
    WHERE o.semester_id = %(semester_id)s::int AND e.status = 'enrolled'
    GROUP BY e.student_id
),
-- сколько раз этот курс уже заваливали или бросали в прошлые семестры
attempts AS (
    SELECT e.student_id, o.course_id, COUNT(*)::numeric AS n
    FROM enrollments e
    JOIN course_offerings o  ON o.id = e.offering_id
    JOIN semesters s         ON s.id = o.semester_id
    JOIN sem                 ON TRUE
    JOIN semesters cur       ON cur.id = sem.id
    WHERE e.status IN ('failed', 'dropped')
      AND s.start_date < cur.start_date
    GROUP BY e.student_id, o.course_id
),
-- активность за недели 1..N
act AS (
    SELECT w.student_id, w.offering_id,
           SUM(w.materials_viewed)::numeric AS total_materials,
           COUNT(*) FILTER (
               WHERE w.logins = 0 AND w.materials_viewed = 0 AND w.forum_posts = 0
           )::numeric AS blank_rows,
           COUNT(*)::numeric AS rows_present
    FROM weekly_activity w
    WHERE w.week_no BETWEEN 1 AND %(week)s::int
    GROUP BY w.student_id, w.offering_id
),
-- работы, срок которых уже наступил
due AS (
    SELECT a.offering_id, COUNT(*)::numeric AS n_due
    FROM assessments a, cut
    WHERE a.status = 'published' AND a.due_at <= cut.at
    GROUP BY a.offering_id
),
-- сдано: считаем по submissions, а не по оценкам. Оценки выставляют позже,
-- и работа, сданная но ещё не проверенная, не должна выглядеть как пропущенная.
sub AS (
    SELECT s.student_id, a.offering_id, COUNT(*)::numeric AS n_submitted
    FROM submissions s
    JOIN assessments a ON a.id = s.assessment_id
    CROSS JOIN cut
    WHERE a.status = 'published'
      AND a.due_at <= cut.at
      AND s.status <> 'not_submitted'
      AND s.submitted_at IS NOT NULL
      AND s.submitted_at <= cut.at
    GROUP BY s.student_id, a.offering_id
),
-- оценки: только опубликованные и только за работы со сроком до среза
sc AS (
    SELECT g.student_id, a.offering_id,
           AVG(g.score / a.max_score * 100)::numeric                AS mean_score,
           MIN(g.score / a.max_score * 100)::numeric                AS min_score,
           SUM(g.score / a.max_score * a.weight_pct)::numeric       AS points_earned
    FROM grades g
    JOIN assessments a ON a.id = g.assessment_id
    CROSS JOIN cut
    WHERE g.status = 'published'
      AND g.score IS NOT NULL
      AND a.status = 'published'
      AND a.due_at <= cut.at
    GROUP BY g.student_id, a.offering_id
)
SELECT
    r.student_id,
    r.offering_id,
    %(week)s::int                                        AS week_no,
    COALESCE(att.n, 0)                                   AS num_of_prev_attempts,
    COALESCE(l.studied_credits, r.credits)               AS studied_credits,
    COALESCE(act.total_materials, 0)                     AS total_materials,
    -- недели без активности: пустые строки плюс недели, строк за которые нет
    COALESCE(act.blank_rows, 0) + (%(week)s::int - COALESCE(act.rows_present, 0))
                                                         AS silent_weeks,
    COALESCE(sub.n_submitted, 0)                         AS n_submitted,
    COALESCE(sc.mean_score, 0)                           AS mean_score,
    COALESCE(sc.min_score, 0)                            AS min_score,
    COALESCE(sc.points_earned, 0)                        AS points_earned,
    GREATEST(COALESCE(d.n_due, 0) - COALESCE(sub.n_submitted, 0), 0)
                                                         AS n_missed,
    CASE WHEN COALESCE(d.n_due, 0) = 0 THEN 1
         ELSE LEAST(COALESCE(sub.n_submitted, 0) / d.n_due, 1) END AS submitted_share
FROM roster r
JOIN course_offerings o ON o.id = r.offering_id
LEFT JOIN load     l   ON l.student_id   = r.student_id
LEFT JOIN attempts att ON att.student_id = r.student_id AND att.course_id = o.course_id
LEFT JOIN act          ON act.student_id = r.student_id AND act.offering_id = r.offering_id
LEFT JOIN sub          ON sub.student_id = r.student_id AND sub.offering_id = r.offering_id
LEFT JOIN sc           ON sc.student_id  = r.student_id AND sc.offering_id = r.offering_id
LEFT JOIN due     d    ON d.offering_id  = r.offering_id
ORDER BY r.offering_id, r.student_id
"""


def fetch_features(conn, semester_id: int, week: int, offering_id: int | None = None):
    """Возвращает (keys, matrix): ключи строк (студент, курс, неделя) и матрицу
    признаков в порядке FEATURES. Соединение отдаёт строки словарями (dict_row)."""
    with conn.cursor() as cur:
        cur.execute(FEATURE_SQL, {'semester_id': semester_id,
                                  'week': week,
                                  'offering_id': offering_id})
        data = cur.fetchall()
    keys = [(r['student_id'], r['offering_id'], r['week_no']) for r in data]
    matrix = [[float(r[f]) for f in FEATURES] for r in data]
    return keys, matrix
