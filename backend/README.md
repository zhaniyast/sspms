# Бэкенд портала (Flask + PostgreSQL)

Работает на готовой базе `portal` из дампа Мадины. Схему менять не нужно.

## Какая база
Основная теперь `portal_new`: её создаёт генератор Мадины (`seed.py`: 317 курсов SDU, 60 открытых в семестре,
40 преподавателей, 300 студентов). Бэкенд работает и на старой `portal` из дампа, переключение одной настройкой.

## Подключение
Положи в корень проекта (`C:\Users\ilash\SSPMS`) файл `.env` (как у Мадины):
```
PGHOST=localhost
PGPORT=5432
PGDATABASE=portal_new
PGUSER=postgres
PGPASSWORD=пароль
```
Либо задай `$env:DATABASE_URL = "postgresql://postgres:пароль@localhost:5432/portal_new"`.
Файл `.env` нельзя пересылать и класть в общий архив: в нём пароль.

## Создать базу portal_new (один раз)
Файлы Мадины (`seed.py`, `schema.sql`, `namegen.py`, `SDU_Unique_Course_List.csv`, `courses_resolved.csv`) положи в папку `seed`.
```powershell
$env:PGPASSWORD = "пароль"
createdb -U postgres portal_new
cd C:\Users\ilash\SSPMS\seed
C:\Users\ilash\anaconda3\python.exe -m pip install psycopg[binary] argon2-cffi
C:\Users\ilash\anaconda3\python.exe seed.py --dsn "postgresql://postgres:пароль@localhost:5432/portal_new" --init --courses courses_resolved.csv
psql -U postgres -d portal_new -f ..\docs\patch_audit_trigger.sql
```
Демо-пароли после генерации: `A001 / admin1234`, `T001` и `T002 / demo1234`, студент `2400003 / demo1234`.
Остальные пароли случайные, пишутся в `credentials.csv`.

## Запуск (из папки SSPMS)
```powershell
C:\Users\ilash\anaconda3\python.exe -m pip install -r backend\requirements.txt
C:\Users\ilash\anaconda3\python.exe -m backend.scoring     # посчитать риски (10-30 сек)
C:\Users\ilash\anaconda3\python.exe -m backend.app         # сервер на http://127.0.0.1:8000
```
Заново запускать `-m backend.scoring` нужно после каждой генерации базы и когда меняются оценки.

## Пароли
Если пароль неизвестен (старая база из дампа), задай свой:

```powershell
C:\Users\ilash\anaconda3\python.exe -m backend.set_password T001 mypassword
```


## Проверка
`python backend\tests\test_api.py` гоняет 40+ проверок (права, черновики оценок, аудит, посещаемость, анонимные отзывы).
Тест пишет в базу (оценки откатываются, остаются записи аудита и вмешательство): запускай на своей копии.

## Новое: импорт, отчёты, куратор, объявления, расписание
| что | как пользоваться |
|---|---|
| Импорт оценок из CSV | Gradebook → **Import CSV**: шаблон, проверка файла без записи, импорт черновиками. Правила в `routes_import.py` |
| Отчёты | More → **Reports**: четыре отчёта по курсу, предпросмотр и CSV |
| Очередь куратора | **Advising**: кому нужно внимание, журнал вмешательств, результат |
| Объявления | More → **Announcements**: преподаватель публикует для своего курса, общие только админ |
| Ежедневный пересчёт | `SCORING_DAILY_AT=03:00` в `.env` (сервер считает сам) или `python -m backend.scheduler --once` по расписанию |
| Проверка модели на данных портала | `python -m backend.validate_model` → `docs/portal_validation.csv` |
| Деплой | `docs/DEPLOY.md`, `render.yaml` |

Проверка новых функций: `python backend\tests\test_features.py` (70 проверок, данные возвращаются как были).
Инструкция для пользователей: `docs/USER_GUIDE.md`. Чек-лист приёмки: `docs/ACCEPTANCE_TESTS.md`.

## Что внутри
| файл | что делает |
|---|---|
| `features.py` | один SQL: 10 признаков модели из `grades`, `submissions`, `assessments`, `weekly_activity`, `enrollments` |
| `scoring.py` | пересчёт: `risk_predictions`, `prediction_explanations`, `course_risk_snapshots`, `student_risk_overall`, уведомления `risk_up`. Одна транзакция, повторный запуск безопасен |
| `access.py` | кто что видит (`teaches`, `advises`, `can_see_student`) |
| `routes_student.py` | курсы, оценки (только опубликованные), риск, дедлайны, посещаемость, справки, сдача работ, анонимный отзыв |
| `routes_teacher.py` | курсы, Class Insights, профиль студента, журнал оценок (черновик/публикация + аудит), посещаемость, вмешательства, эдвайзинг, отзывы (от 5 ответов) |
| `routes_common.py` | вход, уведомления, сообщения, объявления, `/api/predict` (what-if), `/api/model` |
| `routes_import.py` | импорт оценок из CSV: шаблон, проверка (dry-run), запись всё-или-ничего, аудит |
| `routes_reports.py` | отчёты преподавателя: успеваемость, посещаемость, журнал оценок, риски |
| `scheduler.py` | ежедневный пересчёт рисков с блокировкой от двойного запуска |
| `validate_model.py` | recall, precision и ROC-AUC модели на данных портала, сравнение шкал признаков |

## Правила, которые зашиты в код
- студент видит только `published` оценки; черновик возвращается как `null`;
- изменение оценки без `reason` отклоняется и пишется в `grade_audit_log`;
- в признаках нет демографии и нет `date_unregistration`; всё считается на конец недели N;
- прогноз только с 4-й недели (раньше неустойчив);
- общий риск студента = максимум по курсам (`max_over_courses`);
- аудит оценок: если применён `docs/patch_audit_trigger.sql`, причину и автора пишет триггер (одна строка); без патча бэкенд пишет свою строку, и в истории будет дубль;
- отзывы анонимны: ответ и факт участия лежат в разных таблицах, агрегат скрыт, пока ответов меньше 5.

## Ограничения
- `predicted_score_low/high` считаются арифметикой по схеме оценивания (набранное ± 15% на оставшийся вес), не моделью.
- Модель обучена на OULAD; в портале шкала `studied_credits` (16–23 против 30–135) и `total_materials` другая. Проверено: порядок студентов почти не меняется (корреляция 0.99), но абсолютные проценты нужно трактовать осторожно.
- Посещаемость в модель не входит (в OULAD её нет).
