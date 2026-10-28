"""Задать пароль пользователю:   python -m backend.set_password T001 новый_пароль
Нужно, потому что в дампе лежат только хеши, а пароли из генератора неизвестны."""
import sys
from argon2 import PasswordHasher
from .db import connect, run

if len(sys.argv) != 3:
    sys.exit('использование: python -m backend.set_password LOGIN ПАРОЛЬ')
login, pw = sys.argv[1], sys.argv[2]
with connect() as c:
    r = run(c, 'UPDATE users SET password_hash=%(h)s WHERE login_id=%(l)s RETURNING id, role',
            {'h': PasswordHasher().hash(pw), 'l': login})
    print(f'готово: {login} ({r[0]["role"]})' if r else 'такого login_id нет')
