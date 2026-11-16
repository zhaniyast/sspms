# Деплой портала: Render + Neon (задача H, ответ на риск R2)

Схема: один веб-сервис на Render собирается из `Dockerfile` (Flask отдаёт и API, и собранный React),
база PostgreSQL лежит на Neon. Локально ничего не меняется.

Что уже готово в проекте:

| файл | зачем |
|---|---|
| `Dockerfile` | сборка React и запуск Flask через gunicorn |
| `render.yaml` | описание сервиса для Render (Blueprint) |
| `.github/workflows/keep-warm.yml` | раз в 10 минут открывает `/readyz`, чтобы сервис и база не засыпали |
| `/healthz` | «сервер жив» (без базы), по нему Render проверяет сервис |
| `/readyz` | «сервер и база живы», его опрашивает keep-warm |

Цены и названия тарифов меняются, перед оплатой сверьте их на страницах тарифов Render и Neon.

## 0. Что понадобится

- Аккаунты на GitHub, Render и Neon.
- Проект в репозитории GitHub. Render собирает сервис из репозитория, поэтому для деплоя Git нужен,
  даже если в команде файлы пересылаются архивами. В репозиторий не должны попасть `.env`,
  `credentials.csv` и дампы базы: они уже перечислены в `.gitignore`.

```powershell
cd C:\Users\ilash\SSPMS
git add -A
git status          # проверьте глазами: в списке нет .env и credentials.csv
git commit -m "Deploy: reports, CSV import, advising queue, announcements, daily scoring"
git push
```

## 1. База на Neon

1. В Neon создайте проект (регион Frankfurt, ближе всего к Render Frankfurt) и базу `portal_new`.
2. Скопируйте строку подключения (Connection string). Она выглядит так:
   `postgresql://USER:PASSWORD@HOST/portal_new?sslmode=require`. Это секрет, в чат и в репозиторий её не кладут.
3. Заполните базу демо-данными со своего компьютера (один раз):

```powershell
cd C:\Users\ilash\SSPMS\seed
$env:NEON = "postgresql://USER:PASSWORD@HOST/portal_new?sslmode=require"
C:\Users\ilash\anaconda3\python.exe seed.py --dsn $env:NEON --init --courses courses_resolved.csv
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" $env:NEON -f ..\docs\patch_audit_trigger.sql
cd ..
$env:DATABASE_URL = $env:NEON
C:\Users\ilash\anaconda3\python.exe -m backend.scoring
Remove-Item Env:DATABASE_URL
```

Последняя строка обязательна: пока `DATABASE_URL` задан, локальный бэкенд тоже ходит в Neon, а не в вашу локальную базу.

`seed.py` печатает демо-логины и пишет остальные пароли в `credentials.csv` (файл остаётся у вас).

## 2. Сервис на Render

1. Render → **New** → **Blueprint** → выберите репозиторий. Render прочитает `render.yaml`.
2. Render спросит значение `DATABASE_URL`: вставьте строку подключения Neon.
   `SECRET_KEY` он сгенерирует сам, `SCORING_DAILY_AT` уже задан (22:00 UTC = 03:00 по Алматы).
3. Нажмите **Apply** и дождитесь сборки (первая сборка идёт несколько минут).

Проверка после сборки (подставьте адрес сервиса):

```powershell
curl.exe https://ВАШ-СЕРВИС.onrender.com/healthz     # {"ok":true}
curl.exe https://ВАШ-СЕРВИС.onrender.com/readyz      # {"db":true,"ok":true}
```

Затем откройте адрес в браузере и войдите как `T001 / demo1234` и `2400003 / demo1234`.

## 3. Чтобы сервис не засыпал (keep-warm)

Бесплатный план Render усыпляет сервис без запросов, и первое открытие занимает десятки секунд;
платный план не засыпает. База Neon на бесплатном плане тоже приостанавливается без запросов.
Поэтому `/readyz` опрашивается по расписанию:

1. GitHub → репозиторий → **Settings → Secrets and variables → Actions → Variables** →
   переменная `SITE_URL` = `https://ВАШ-СЕРВИС.onrender.com` (без `/` в конце).
2. Вкладка **Actions** → workflow **keep-warm** → **Run workflow** (первый запуск вручную, дальше сам каждые 10 минут).

Расписание GitHub Actions может запаздывать на несколько минут. Если нужна точность, тот же адрес
можно опрашивать любым внешним сервисом мониторинга.

## 4. Перед демо (чек-лист R2)

- [ ] За день до демо: `/readyz` отвечает `200`, вход под тремя ролями работает.
- [ ] За 5 минут до демо: открыть сайт и войти (прогревает сервис и базу).
- [ ] В логах Render нет `Out of memory` и перезапусков. Триггер риска R2: первая загрузка дольше 30 секунд или OOM в логах.
- [ ] Запасной вариант: локальный запуск (`python -m backend.app` и `npm run dev`) на ноутбуке докладчика.

## 5. Ежедневный пересчёт рисков (задача F)

На Render он уже включён переменной `SCORING_DAILY_AT`. Проверить:

- админ: `GET /api/admin/scoring-status` показывает время следующего и последнего запуска;
- админ: `POST /api/admin/scoring-run` запускает пересчёт сейчас.

Локально на Windows (если нужен пересчёт без сервера), Планировщик заданий:

```powershell
schtasks /Create /TN "SSPMS daily scoring" /SC DAILY /ST 03:00 `
  /TR "cmd /c cd /d C:\Users\ilash\SSPMS && C:\Users\ilash\anaconda3\python.exe -m backend.scheduler --once"
```

Либо просто держать открытым окно: `python -m backend.scheduler --at 03:00`.

## 6. Обновление сервиса

`git push` в основную ветку: Render пересоберёт сервис сам (`autoDeployTrigger: commit`).
Если менялась схема оценивания или импортировались оценки, риски пересчитаются ночью
или сразу через `POST /api/admin/scoring-run`.

## Ограничения

- `gunicorn` запускается с одним процессом (`--workers 1`). Это нужно расписанию пересчёта:
  при нескольких процессах пересчёт запускался бы в каждом (от одновременного запуска защищает блокировка в базе).
- В образ входит только `models/model_db10.joblib`. Скрипт `backend.validate_model` запускается локально.
- Сборка на Render в этой сессии не проверялась: проверены синтаксис `render.yaml`, эндпоинты `/healthz` и `/readyz` и тесты бэкенда.
