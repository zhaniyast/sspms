"""
ТОЛЬКО ДЛЯ ТЕСТОВ В ПЕСОЧНИЦЕ, где нельзя поставить psycopg.
Делает вид, что это psycopg, но гонит запросы через постоянный процесс psql.
На машине Жании не используется: там стоит настоящий psycopg.
"""
import csv, io, json, os, re, subprocess, sys, types, datetime, decimal

SENT = '__END_OF_RESULT__'


def lit(v):
    if v is None: return 'NULL'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float, decimal.Decimal)): return repr(v) if not isinstance(v, decimal.Decimal) else str(v)
    if isinstance(v, (list, tuple)):
        return 'ARRAY[' + ','.join(lit(x) for x in v) + ']' if v else "'{}'"
    if isinstance(v, dict): v = json.dumps(v)
    return "'" + str(v).replace("'", "''") + "'"


def conv(s):
    if s is None: return None
    if s == 't': return True
    if s == 'f': return False
    if re.fullmatch(r'-?\d+', s): return int(s)
    if re.fullmatch(r'-?\d+\.\d+', s): return decimal.Decimal(s)
    return s


class Cursor:
    def __init__(self, c): self.c = c; self.description = None; self._rows = []
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def execute(self, sql, params=None):
        if params:
            if isinstance(params, dict):
                sql = re.sub(r'%\((\w+)\)s', lambda m: lit(params[m.group(1)]), sql)
            else:
                it = iter(params); sql = re.sub(r'%s', lambda m: lit(next(it)), sql)
        sql = sql.replace('%%', '%')
        p = self.c.p
        p.stdin.write(sql.strip().rstrip(';') + ';\n\\echo ' + SENT + '\n'); p.stdin.flush()
        out = []
        while True:
            line = p.stdout.readline()
            if line.strip() == SENT: break
            out.append(line)
        text = ''.join(out)
        if re.search(r'^ERROR:', text, re.M):
            self.c.p.stdin.write('ROLLBACK;\n\\echo ' + SENT + '\n'); self.c.p.stdin.flush()
            while self.c.p.stdout.readline().strip() != SENT: pass
            raise RuntimeError(text.strip())
        m = re.match(r'^(INSERT|UPDATE|DELETE|BEGIN|COMMIT|ROLLBACK|SET|CREATE|ALTER|TRUNCATE)\b', text.strip())
        if text.strip() == '' or (m and '\n' not in text.strip() and not text.strip().startswith('id')):
            self.description = None; self._rows = []; return
        r = list(csv.reader(io.StringIO(text)))
        # psql --csv выводит пустые значения как пустую строку, а NULL тоже пустой: считаем пустое NULL
        hdr = r[0]; self.description = [(h,) for h in hdr]
        self._rows = [{h: (conv(v) if v != '' else None) for h, v in zip(hdr, row)} for row in r[1:]]
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None
    @property
    def rowcount(self): return len(self._rows)
    def executemany(self, sql, seq):
        for s in seq: self.execute(sql, s)


class Conn:
    def __init__(self):
        env = dict(os.environ, PGHOST='/tmp', PGPORT='5444', PGUSER='pg', PGDATABASE=os.environ.get('PGDATABASE', 'portal'))
        self.p = subprocess.Popen(['psql', '--csv', '-q', '-X', '-v', 'ON_ERROR_STOP=0'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        self.p.stdin.write('BEGIN;\n\\echo ' + SENT + '\n'); self.p.stdin.flush()
        while self.p.stdout.readline().strip() != SENT: pass
    def cursor(self): return Cursor(self)
    def _x(self, s):
        self.p.stdin.write(s + ';\nBEGIN;\n\\echo ' + SENT + '\n'); self.p.stdin.flush()
        while self.p.stdout.readline().strip() != SENT: pass
    def commit(self): self._x('COMMIT')
    def rollback(self): self._x('ROLLBACK')
    def close(self):
        try: self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception: pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def connect(dsn=None, row_factory=None, **kw): return Conn()


def install():
    m = types.ModuleType('psycopg'); m.connect = connect
    r = types.ModuleType('psycopg.rows'); r.dict_row = object()
    m.rows = r
    ci = types.ModuleType('psycopg.conninfo'); ci.make_conninfo = lambda **k: ''; m.conninfo = ci
    sys.modules['psycopg.conninfo'] = ci
    sys.modules['psycopg'] = m; sys.modules['psycopg.rows'] = r
