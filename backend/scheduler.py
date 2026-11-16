"""Ежедневный пересчёт рисков (задача F).

Три способа запуска, выбирается один:

1) Внутри сервера. Задать переменную окружения SCORING_DAILY_AT=03:00 (время сервера,
   на Render это UTC: 22:00 UTC = 03:00 по Алматы). Сервер сам пересчитывает раз в сутки.
2) Отдельной командой по расписанию (cron, Планировщик заданий Windows, Render Cron Job):
       python -m backend.scheduler --once
3) Отдельным процессом, который сам ждёт нужного времени:
       python -m backend.scheduler --at 03:00

Двойной запуск безопасен: на время пересчёта берётся блокировка в базе
(pg_try_advisory_lock), второй процесс просто пропускает свой запуск.
"""
import datetime as dt
import os
import sys
import threading
import time

from .db import connect, one

LOCK_KEY = 743_001                      # произвольный номер блокировки для этого задания
STATE = {'enabled': False, 'daily_at': None, 'next_run': None, 'last_run': None,
         'last_result': None, 'last_error': None}
_started = False


def parse_hhmm(value):
    """'03:00' -> (3, 0). None, если формат неверный."""
    try:
        h, m = str(value).strip().split(':')
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    return (h, m) if 0 <= h < 24 and 0 <= m < 60 else None


def next_run(hhmm, now=None):
    """Ближайший момент hh:mm строго после now."""
    now = now or dt.datetime.now()
    t = now.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
    return t if t > now else t + dt.timedelta(days=1)


def run_once():
    """Один пересчёт. Возвращает словарь с итогом; ошибок наружу не бросает."""
    from .scoring import recompute
    started = dt.datetime.now()
    try:
        with connect() as c:
            got = one(c, 'SELECT pg_try_advisory_lock(%(k)s) AS ok', {'k': LOCK_KEY})['ok']
            if not got:
                result = {'skipped': 'another run is in progress'}
            else:
                try:
                    result = recompute(c)
                    c.commit()
                finally:
                    one(c, 'SELECT pg_advisory_unlock(%(k)s) AS ok', {'k': LOCK_KEY})
                    c.commit()
        STATE.update(last_run=started.isoformat(timespec='seconds'), last_result=result, last_error=None)
        return result
    except Exception as e:                                   # задание не должно ронять сервер
        STATE.update(last_run=started.isoformat(timespec='seconds'), last_error=str(e))
        print('daily scoring failed:', e, file=sys.stderr)
        return {'error': str(e)}


def _loop(hhmm):
    while True:
        nxt = next_run(hhmm)
        STATE['next_run'] = nxt.isoformat(timespec='seconds')
        while True:
            left = (nxt - dt.datetime.now()).total_seconds()
            if left <= 0:
                break
            time.sleep(min(left, 60))
        print('daily scoring:', run_once())


def start(daily_at=None):
    """Запустить фоновое расписание в этом процессе. Без SCORING_DAILY_AT ничего не делает."""
    global _started
    value = daily_at or os.environ.get('SCORING_DAILY_AT')
    hhmm = parse_hhmm(value) if value else None
    if not hhmm or _started:
        return False
    _started = True
    STATE.update(enabled=True, daily_at=f'{hhmm[0]:02d}:{hhmm[1]:02d}')
    threading.Thread(target=_loop, args=(hhmm,), daemon=True, name='daily-scoring').start()
    return True


if __name__ == '__main__':
    args = sys.argv[1:]
    if '--once' in args:
        print(run_once())
    else:
        at = args[args.index('--at') + 1] if '--at' in args and len(args) > args.index('--at') + 1 \
            else os.environ.get('SCORING_DAILY_AT', '03:00')
        hhmm = parse_hhmm(at)
        if not hhmm:
            sys.exit('Время задаётся как ЧЧ:ММ, например --at 03:00')
        print(f'Пересчёт рисков каждый день в {hhmm[0]:02d}:{hhmm[1]:02d}. Остановить: Ctrl+C')
        _loop(hhmm)
