#!/usr/bin/env python3
"""Demo data generator for the university portal (PostgreSQL schema.sql).

  python seed.py --dsn postgresql://user:pass@localhost/portal --init     # schema + data
  python seed.py --dsn ... --reset                                        # wipe tables, refill
  python seed.py --csv-dir out/                                           # no DB: CSV + checks

Courses: the WHOLE list from --courses (default SDU_Unique_Course_List.csv) goes to the catalog (table courses);
--offered N of them (default 60) get a Fall 2026 offering with teacher, timetable, assignments and students.
More teachers: --teachers 40. The resolved list (department, credits, offered) is written to --courses-out;
edit it and pass it back with --courses to override departments, credits or the offered set (column offer = 1).
Same --seed => same database.
"""
import argparse, base64, collections, csv, hashlib, json, math, os, random, re, secrets, sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from namegen import NameGen

HERE = Path(__file__).parent
TZ = timezone(timedelta(hours=5))                      # Almaty

# ------------------------------------------------------------------ schema parsing
def parse_schema(text):
    text = re.sub(r"--.*", "", text)
    tabs = {}
    for m in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\);", text, re.S):
        name, body = m.group(1), m.group(2)
        t = dict(cols=[], serial=False, fks=[], uniq=[], order=len(tabs))
        pk_single = None
        for line in body.splitlines():
            mm = re.match(r" {4}(\w+)\s+([A-Z]+)", line)
            if mm and mm.group(1) not in ("UNIQUE", "PRIMARY", "CHECK", "FOREIGN", "CONSTRAINT"):
                c = mm.group(1); t["cols"].append(c)
                if re.search(r"SERIAL PRIMARY KEY", line): t["serial"] = True
                if "PRIMARY KEY" in line: t["uniq"].append((c,))
                elif re.search(r"\bUNIQUE\b", line): t["uniq"].append((c,))
                r = re.search(r"REFERENCES (\w+)\((\w+)\)", line)
                if r: t["fks"].append((c, r.group(1), r.group(2)))
            else:
                u = re.match(r"\s+(?:UNIQUE|PRIMARY KEY) \(([^)]*)\)", line)
                if u: t["uniq"].append(tuple(x.strip() for x in u.group(1).split(",")))
        tabs[name] = t
    return tabs

SCHEMA = parse_schema((HERE / "schema.sql").read_text(encoding="utf-8"))

class DB:
    def __init__(s): s.rows = {t: [] for t in SCHEMA}
    def add(s, table, **row):
        if SCHEMA[table]["serial"] and "id" not in row:
            row = {"id": len(s.rows[table]) + 1, **row}
        s.rows[table].append(row)
        return row.get("id")

def hash_password(pw):
    try:
        from argon2 import PasswordHasher
        return PasswordHasher().hash(pw)
    except ImportError:                                  # Django-compatible pbkdf2
        salt = secrets.token_hex(8); it = 100_000
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), it)
        return f"pbkdf2_sha256${it}${salt}${base64.b64encode(dk).decode()}"

# ------------------------------------------------------------------ constants
DEFAULT_COURSES = [
    ("CS101", "Programming Fundamentals", 5, "Computer Science"),
    ("CS201", "Data Structures and Algorithms", 5, "Computer Science"),
    ("CS230", "Database Systems", 4, "Computer Science"),
    ("CS250", "Operating Systems", 4, "Computer Science"),
    ("MATH201", "Linear Algebra", 3, "Mathematics"),
    ("MATH210", "Probability and Statistics", 3, "Mathematics"),
    ("DS301", "Machine Learning", 5, "Data Science"),
    ("DS310", "Data Visualization", 3, "Data Science"),
    ("IS220", "Web Development", 4, "Information Systems"),
    ("IS320", "Information Systems Analysis", 3, "Information Systems"),
]
DEPTS = ["Computer Science", "Mathematics", "Information Systems", "Data Science", "General Education"]
YEARS = (2023, 2024, 2025, 2026)                       # admission years => study years 4, 3, 2, 1
OFFER_SHARE = {"Computer Science": .36, "Mathematics": .16, "Information Systems": .16, "Data Science": .16, "General Education": .16}
OFFICE_BLD = {"Computer Science": "A", "Mathematics": "B", "Information Systems": "C", "Data Science": "D", "General Education": "E"}
PROGRAMS = [("CS", "Computer Science", "Computer Science"), ("IS", "Information Systems", "Information Systems"),
            ("DS", "Data Science", "Data Science"), ("SE", "Software Engineering", "Computer Science")]
TITLES = ["Assistant Professor", "Senior Lecturer", "Associate Professor", "Lecturer"]
COLORS = ["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6", "#EF4444", "#06B6D4", "#EC4899", "#84CC16", "#F97316", "#6366F1"]
PERIODS = [(9, 0), (10, 30), (12, 0), (14, 0), (15, 30), (17, 0)]
TOPICS = ["Introduction", "Core concepts", "Methods", "Practice session", "Case study", "Review", "Advanced topics",
          "Midterm preparation", "Midterm", "Applications", "Project work", "Special topics", "Integration",
          "Project presentations", "Revision", "Final exam"]
PROFILES = ["strong", "average", "late", "burnout", "at_risk"]
PROFILE_W = [.25, .35, .15, .15, .10]


# ------------------------------------------------------------------ course list helpers
LOOKALIKE = str.maketrans({"А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
                           "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i"})
GENED_RE = re.compile(r"(kazakh|russian|english|turkish|foreign|german|chinese|french|korean|arabic) language|general english|foreign language|"
                      r"history of kazakhstan|philosophy|physical education|economy|entrepreneurship|inclusive education|"
                      r"research methods|academic writing|sociology|politic|psycholog|culture|life safety|ecology|religio", re.I)
MATH_RE = re.compile(r"calculus|algebra|discrete|probability|differential|numerical|physics|geometry|optimi[sz]ation|combinatorics|"
                     r"number theory|symbolic logic|mathematic|mathematical|topology|statistics", re.I)
DS_RE = re.compile(r"machine learning|deep learning|neural|data (analysis|analytics|mining|science|visuali[sz]ation)|big data|generative|"
                   r"natural language|computer vision|pattern recognition|artificial intelligence|ai fundamentals|reinforcement|"
                   r"topological data|operations research|data-driven", re.I)
EXCLUDE_RE = re.compile(r"industrial|pregraduational|graduation|diploma|thesis|comprehensive exam|state exam|defen[cs]e|physical education", re.I)

def looks_cut_off(name):
    """Names such as 'tools and' or 'to Business' (a word was lost in the source file) are never auto-selected for the timetable."""
    w = name.split()
    return name[:1].islower() or name.split()[-1].lower() in ("and", "of", "for", "to", "in", "the") or (len(w) == 1 and len(name) < 8)

def classify_dept(code, name):
    """Best-guess department from the code prefix and the course name. Override with a 'department' column."""
    p = code.split()[0]
    if p in ("MDE", "ECO", "PED") or GENED_RE.search(name): return "General Education"
    if p == "SDS": return "Data Science"
    if p in ("MAT", "MCM") or MATH_RE.search(name): return "Mathematics"
    if DS_RE.search(name): return "Data Science"
    if p in ("INF", "MMS"): return "Information Systems"
    return "Computer Science"

def course_level(code):
    m = re.search(r"(\d+)\s*$", code)
    return max(1, int(m.group(1)[0])) if m else 1

def load_courses(path, default_credits=5):
    """Catalog rows: dict(code, name, credits, department, level, offer)."""
    if not path:
        return [dict(code=c, name=n, credits=cr, department=d, level=course_level(c), offer=False) for c, n, cr, d in DEFAULT_COURSES]
    text = open(path, encoding="utf-8-sig").read()
    head = text.splitlines()[0]
    delim = ";" if head.count(";") > head.count(",") else ","
    out, seen = [], set()
    for r in csv.DictReader(text.splitlines(), delimiter=delim):
        r = {re.sub(r"[\s_]+", "_", (k or "").strip().lower()): (v or "").strip() for k, v in r.items()}
        code = re.sub(r"\s+", " ", r.get("course_code") or r.get("code") or "").upper()
        code = re.sub(r"^([A-Z]+)\s*(\d+)$", r"\1 \2", code)
        name = re.sub(r"\s+", " ", r.get("course_name") or r.get("name") or "")
        if not code or not name: continue
        if re.search(r"[A-Za-z]", name): name = name.translate(LOOKALIKE)       # Cyrillic lookalikes -> Latin
        if code in seen: print("WARNING: duplicate course code skipped:", code); continue
        seen.add(code)
        out.append(dict(code=code, name=name, credits=int(float(r.get("credits") or default_credits)),
                        department=r.get("department") or classify_dept(code, name), level=course_level(code),
                        offer=(r.get("offer") or "").lower() in ("1", "yes", "true", "y")))
    return out

def select_offered(catalog, n, rng):
    """Which catalog courses run in Fall 2026: balanced over departments and study years 1-4, unique names."""
    forced = [c for c in catalog if c["offer"]]
    if forced:
        chosen = forced[:]
    else:
        pool = [c for c in catalog if 1 <= c["level"] <= 4 and not EXCLUDE_RE.search(c["name"]) and not looks_cut_off(c["name"])]
        rng.shuffle(pool)
        seen, uniq = set(), []
        for c in pool:
            if c["name"].lower() not in seen: seen.add(c["name"].lower()); uniq.append(c)
        if n <= 0: n = len(uniq)
        by = collections.defaultdict(list)
        for c in uniq: by[(c["department"], c["level"])].append(c)
        chosen, raw = [], {d: n * sh for d, sh in OFFER_SHARE.items()}
        quotas = {d: int(v) for d, v in raw.items()}
        for d in sorted(raw, key=lambda x: raw[x] - quotas[x], reverse=True)[:n - sum(quotas.values())]: quotas[d] += 1
        for d in OFFER_SHARE:
            quota, got, progress = quotas[d], 0, True
            while got < quota and progress:
                progress = False
                for lv in (1, 2, 3, 4):
                    if got < quota and by[(d, lv)]: chosen.append(by[(d, lv)].pop()); got += 1; progress = True
        left = [c for c in uniq if c not in chosen]
        chosen += left[:max(0, n - len(chosen))]
    order = {d: i for i, d in enumerate(DEPTS)}
    chosen.sort(key=lambda c: (order.get(c["department"], 99), c["level"], c["code"]))
    anchor = next((c for c in chosen if c["department"] == "Computer Science" and c["level"] == 3),
                  next((c for c in chosen if c["department"] == "Computer Science"), chosen[0]))
    chosen.remove(anchor)
    return [anchor] + chosen                                   # the first course = demo student's "problem" course, taught by T001

def teacher_departments(offered, n_teachers):
    """Department of every teacher: T001 = Computer Science (demo advisor), T002 = Mathematics (demo teacher), then proportional."""
    cnt = collections.Counter(c["department"] for c in offered)
    out = [d for d in ("Computer Science", "Mathematics", "Information Systems", "Data Science", "General Education") if cnt[d]][:n_teachers]
    have, quota = collections.Counter(out), {d: cnt[d] / len(offered) * n_teachers for d in cnt}
    while len(out) < n_teachers:
        d = max(cnt, key=lambda x: (quota[x] - have[x], cnt[x])); out.append(d); have[d] += 1
    return out

def pick_courses(rng, prog_dept, year, offerings, k=5, fixed=()):
    """k offerings for one student: own department and study year first, no timetable overlaps, at most 1 general-education course."""
    chosen, ids = list(fixed), {id(o) for o in fixed}
    cells = set().union(*[o["cells"] for o in chosen]) if chosen else set()
    keyed = []
    for o in offerings:
        if id(o) in ids: continue
        w = 4.0 if o["dept"] == prog_dept else 3.0 if (o["dept"] == "Mathematics" and year <= 2) else 2.0 if o["dept"] == "General Education" else .5
        w *= 4.0 if o["level"] == year else 1.5 if abs(o["level"] - year) == 1 else .1
        keyed.append((rng.random() ** (1 / w), o))
    keyed.sort(key=lambda t: -t[0])
    gened = sum(1 for o in chosen if o["dept"] == "General Education")
    for relax in (False, True):                                 # second pass only if the timetable leaves no choice
        for _, o in keyed:
            if len(chosen) >= k: break
            if id(o) in ids or (not relax and o["cells"] & cells): continue
            if o["dept"] == "General Education" and gened >= 1 and not relax: continue
            chosen.append(o); ids.add(id(o)); cells |= o["cells"]; gened += o["dept"] == "General Education"
    return chosen

def P(p, w):
    if p == "strong":  return dict(att=.96, sub=.98, ontime=.95, score=.90, act=9)
    if p == "average": return dict(att=.88, sub=.90, ontime=.80, score=.76, act=6)
    if p == "late":
        e = w <= 4
        return dict(att=.55 if e else .90, sub=.50 if e else .92, ontime=.6, score=.55 if e else .72, act=2 if e else 7)
    if p == "burnout":
        return dict(att=max(.30, .97 - .08 * w), sub=max(.30, .97 - .08 * w), ontime=max(.3, .9 - .06 * w),
                    score=max(.42, .9 - .05 * w), act=max(1, 9 - .9 * w))
    return dict(att=.60 - .01 * w, sub=.58, ontime=.35, score=.52, act=2.5)

# kind, title, category, max, week, weekday | relative hours | weight
ASSESS = [
    ("Assignment 1", "assignment", "Assignments", 100, ("w", 3, 5), 6), ("Assignment 2", "assignment", "Assignments", 100, ("w", 5, 5), 6),
    ("Assignment 3", "assignment", "Assignments", 100, ("w", 7, 5), 6), ("Assignment 4", "assignment", "Assignments", 100, ("h", -30), 6),
    ("Assignment 5", "assignment", "Assignments", 100, ("h", 48), 6),
    ("Quiz 1", "quiz", "Quizzes", 20, ("w", 4, 3), 3.34), ("Quiz 2", "quiz", "Quizzes", 20, ("h", -96), 3.33),
    ("Quiz 3", "quiz", "Quizzes", 20, ("h", 240), 3.33),
    ("Midterm Exam", "midterm", "Midterm", 100, ("w", 8, 4), 20), ("Final Exam", "final", "Final", 100, ("w", 16, 5), 40)]
CAT_W = {"Assignments": 30, "Quizzes": 10, "Midterm": 20, "Final": 40}

FEAT_TXT = {  # feature: (raises risk text, lowers risk text)  per language
    "attendance": {"ru": ("Посещаемость {v}%: ниже нормы", "Посещаемость {v}%: стабильно хорошая"),
                   "en": ("Attendance {v}%: below the norm", "Attendance {v}%: consistently good"),
                   "kk": ("Қатысу {v}%: нормадан төмен", "Қатысу {v}%: тұрақты жақсы")},
    "avg_score": {"ru": ("Средний балл за задания {v}%: низкий", "Средний балл за задания {v}%: высокий"),
                  "en": ("Average assignment score {v}%: low", "Average assignment score {v}%: high"),
                  "kk": ("Тапсырмалар бойынша орташа балл {v}%: төмен", "Тапсырмалар бойынша орташа балл {v}%: жоғары")},
    "on_time_rate": {"ru": ("Сдано вовремя {v}% работ: есть просрочки и пропуски", "Сдано вовремя {v}% работ: дисциплина в порядке"),
                     "en": ("{v}% submitted on time: late or missed work", "{v}% submitted on time: good discipline"),
                     "kk": ("Уақытында тапсырылғаны {v}%: кешіктіру бар", "Уақытында тапсырылғаны {v}%: тәртіп жақсы")},
    "activity": {"ru": ("Активность в системе {v}% от средней по курсу", "Активность в системе {v}% от средней по курсу, это хорошо"),
                 "en": ("Activity is {v}% of the course average", "Activity is {v}% of the course average, which is good"),
                 "kk": ("Белсенділік курс орташасының {v}%-ы", "Белсенділік курс орташасының {v}%-ы, бұл жақсы")}}
REC_TXT = {"attendance": "Не пропускай занятия по курсу «{c}»", "avg_score": "Разбери слабые темы курса «{c}» с преподавателем",
           "on_time_rate": "Сдавай задания по курсу «{c}» до дедлайна", "activity": "Заходи в материалы курса «{c}» каждую неделю"}

def sigmoid(x): return 1 / (1 + math.exp(-x))
def level(p): return "low" if p < .35 else "medium" if p < .65 else "high"

# ------------------------------------------------------------------ generator
def generate(a):
    rng = random.Random(a.seed); db = DB(); gen = NameGen(seed=a.seed)
    today = a.today; NOW = datetime.combine(today, time(12, 0), tzinfo=TZ)
    def dt(d, h=0, m=0): return datetime.combine(d, time(h, m), tzinfo=TZ)
    creds = []

    # --- A. reference data
    dept_id = {n: db.add("departments", name=n) for n in DEPTS}
    prog_id = {c: db.add("programs", code=c, name=n, total_credits=240, department_id=dept_id[d]) for c, n, d in PROGRAMS}
    sem_start = today - timedelta(days=today.weekday()) - timedelta(weeks=8)      # => current week is 9
    W = (today - sem_start).days // 7 + 1
    week_of = lambda d: (d - sem_start).days // 7 + 1
    sem_id = db.add("semesters", name="Fall 2026", start_date=sem_start, end_date=sem_start + timedelta(weeks=16, days=-3),
                    total_weeks=16, is_current=True)
    groups = []
    for pc, _, _ in PROGRAMS:
        for yr in YEARS:
            for k in (1, 2):
                gid = db.add("student_groups", code=f"{pc}-{yr % 100}{k:02d}", program_id=prog_id[pc], admission_year=yr)
                groups.append((gid, pc, yr))
    room_ids = [db.add("rooms", building=b, number=str(n), capacity=rng.choice([30, 40, 60, 120]))
                for b in "ABCD" for n in range(101, 111)]
    scale = db.add("grade_scales", name="Standard 4.0")
    for l, m, g in [("A", 95, 4.0), ("A-", 90, 3.67), ("B+", 85, 3.33), ("B", 80, 3.0), ("B-", 75, 2.67), ("C+", 70, 2.33),
                    ("C", 65, 2.0), ("C-", 60, 1.67), ("D+", 55, 1.33), ("D", 50, 1.0), ("F", 0, 0.0)]:
        db.add("grade_scale_levels", scale_id=scale, letter=l, min_percent=m, gpa_points=g)
    late_pol = db.add("late_policies", name="Standard", grace_hours=2, penalty_pct_day=10, max_penalty_pct=50)

    # --- B. course catalog, offered subset, teachers
    catalog = load_courses(a.courses, a.default_credits)
    for c in catalog:
        if c["department"] not in dept_id: dept_id[c["department"]] = db.add("departments", name=c["department"])
    offered = select_offered(catalog, a.offered, rng)
    offered_codes = {c["code"] for c in offered}
    t_depts = teacher_departments(offered, a.teachers)

    def new_user(login, pw, role):
        return db.add("users", login_id=login, password_hash=hash_password(pw), role=role, is_active=True,
                      last_login=None, created_at=NOW - timedelta(days=60), created_by=None)
    new_user("A001", "admin1234", "admin"); creds.append(("A001", "admin1234", "admin", "Admin", ""))
    admin_uid = 1
    teachers = []                                            # (uid, dept)
    for i in range(1, a.teachers + 1):
        n = gen.make(); pw = "demo1234" if i <= 2 else secrets.token_urlsafe(8); login = f"T{i:03d}"
        uid = new_user(login, pw, "teacher"); dep = t_depts[i - 1]
        db.add("teachers", user_id=uid, first_name=n["first_name"], last_name=n["last_name"], email=f"{login.lower()}@univ.kz",
               photo_url=None, title=rng.choice(TITLES), department_id=dept_id[dep], office=f"{OFFICE_BLD.get(dep, 'B')}-{200 + i}",
               office_hours_note=rng.choice(["Tue/Thu 16:00-17:00", "Mon/Wed 15:30-16:30", "Wed/Fri 14:00-15:00"]) if i > 2 else "Tue/Thu 16:00-17:00")
        teachers.append((uid, dep)); creds.append((login, pw, "teacher", n["first_name"], n["last_name"]))
    tname = {uid: (db.rows["teachers"][i]["first_name"], db.rows["teachers"][i]["last_name"]) for i, (uid, _) in enumerate(teachers)}

    # --- C. catalog (ALL courses), offerings, timetable
    cat_id = {}
    for c in catalog:
        text = (f"{c['name']}: course for the Fall 2026 semester." if c["code"] in offered_codes
                else f"{c['name']}. Catalog course, not offered in the current semester.")
        cat_id[c["code"]] = db.add("courses", code=c["code"], name=c["name"], credits=c["credits"], department_id=dept_id[c["department"]], description=text)
    by_dept_t, load = {}, {uid: 0 for uid, _ in teachers}
    for uid, dep in teachers: by_dept_t.setdefault(dep, []).append(uid)
    assign = {}
    for c in offered:                                        # least-loaded teacher of the same department
        pool = by_dept_t.get(c["department"]) or [t[0] for t in teachers]
        uid = min(pool, key=lambda u: (load[u], u)); assign[c["code"]] = uid; load[uid] += 1
    adv_uid, adv_dep = teachers[0]                           # demo advisor T001 must teach at least 2 offerings
    while load[adv_uid] < 2:
        donors = [c for c in offered if c["department"] == adv_dep and assign[c["code"]] != adv_uid and load[assign[c["code"]]] > 1]
        if not donors: break
        c = donors[-1]; load[assign[c["code"]]] -= 1; assign[c["code"]] = adv_uid; load[adv_uid] += 1
    cells = [(wd, p) for wd in range(1, 6) for p in range(len(PERIODS))]
    busy_t, busy_r, cell_load = set(), set(), collections.Counter()
    offerings = []                                           # dict(id, teacher, name, code, dept, level, slots, cells)
    for ci, c in enumerate(offered):
        tid = assign[c["code"]]
        oid = db.add("course_offerings", course_id=cat_id[c["code"]], semester_id=sem_id, teacher_id=tid, color=COLORS[ci % len(COLORS)],
                     grade_scale_id=scale, max_absence_pct=20, format_note="Lectures and practice")
        o = dict(id=oid, teacher=tid, name=c["name"], code=c["code"], dept=c["department"], level=c["level"], slots=[], cells=set())
        offerings.append(o)
        days = set()
        for k in range(2):                                   # no teacher/room clashes, two different days, evenly spread over the week
            def free_cells(strict):
                return [(wd, p) for wd, p in cells if (not strict or wd not in days) and (tid, wd, p) not in busy_t
                        and any((r, wd, p) not in busy_r for r in room_ids)]
            free = free_cells(True) or free_cells(False)
            low = min(cell_load[x] for x in free)
            wd, per = rng.choice([x for x in free if cell_load[x] == low])
            rid = rng.choice([r for r in room_ids if (r, wd, per) not in busy_r])
            busy_t.add((tid, wd, per)); busy_r.add((rid, wd, per)); days.add(wd); cell_load[(wd, per)] += 1; o["cells"].add((wd, per))
            sid = db.add("schedule_slots", offering_id=oid, section_id=None, weekday=wd, start_time=time(*PERIODS[per]),
                         end_time=(datetime.combine(today, time(*PERIODS[per])) + timedelta(minutes=80)).time(),
                         room_id=rid, lesson_type="lecture" if k == 0 else rng.choice(["practice", "lab"]))
            o["slots"].append(sid)
        for w in range(1, 17):
            db.add("syllabus_weeks", offering_id=oid, week_no=w, topic=TOPICS[w - 1], description=f"Week {w}: {TOPICS[w - 1]}")
    slot_by_id = {r["id"]: r for r in db.rows["schedule_slots"]}
    meetings = {o["id"]: [] for o in offerings}              # offering -> [(meeting_id, datetime_end, week)]
    for o in offerings:
        for sid in o["slots"]:
            s = slot_by_id[sid]
            for w in range(1, 17):
                d = sem_start + timedelta(weeks=w - 1, days=s["weekday"] - 1)
                mid = db.add("class_meetings", offering_id=o["id"], section_id=None, slot_id=sid, meeting_date=d,
                             start_time=s["start_time"], end_time=s["end_time"], room_id=s["room_id"],
                             lesson_type=s["lesson_type"], topic=TOPICS[w - 1], week_no=w)
                meetings[o["id"]].append((mid, datetime.combine(d, s["end_time"], tzinfo=TZ), d, w))
    for o in offerings:                                       # categories and assessments
        cat = {c: db.add("assessment_categories", offering_id=o["id"], name=c, weight_pct=w) for c, w in CAT_W.items()}
        o["assess"] = []
        for title, kind, cname, mx, due, wt in ASSESS:
            d = dt(sem_start + timedelta(weeks=due[1] - 1, days=due[2] - 1), 23, 59) if due[0] == "w" else NOW + timedelta(hours=due[1])
            aid = db.add("assessments", offering_id=o["id"], category_id=cat[cname], title=title,
                         description="Complete the task and submit your solution before the deadline.", kind=kind, due_at=d,
                         max_score=mx, weight_pct=wt, status="published" if d <= NOW + timedelta(days=14) else "draft",
                         visible_from=max(dt(sem_start), d - timedelta(days=21)), late_policy_id=late_pol if kind == "assignment" else None,
                         created_by=o["teacher"], created_at=dt(sem_start))
            o["assess"].append(dict(id=aid, title=title, kind=kind, max=mx, due=d, week=week_of(d.date())))
        for w in range(1, W + 2):
            for j in range(rng.choice([1, 2])):
                vis = "visible" if w <= W else "scheduled"
                db.add("materials", offering_id=o["id"], week_no=w, title=f"Week {w} {rng.choice(['slides', 'reading', 'lab sheet'])}",
                       material_type=rng.choice(["slides", "pdf", "link"]), url=f"/files/{o['code'].lower()}/w{w}_{j}.pdf",
                       visibility=vis, visible_from=dt(sem_start + timedelta(weeks=w - 1)) if w > W else None,
                       uploaded_by=o["teacher"], created_at=dt(sem_start + timedelta(weeks=w - 1)))
    # --- students (each takes a timetable-consistent set of courses for their program and study year)
    students = []                                             # dict(uid, profile, offs)
    demo_idx = 3; sem_year = sem_start.year
    prog_dept = {pc: d for pc, _, d in PROGRAMS}
    for i in range(1, a.students + 1):
        n = gen.make()
        if i == demo_idx: gid, pc, yr = next(g for g in groups if g[1] == "CS" and g[2] == 2024)     # 3rd-year Computer Science
        else: gid, pc, yr = rng.choice(groups)
        login = f"{yr % 100}{i:05d}"
        pw = "demo1234" if i == demo_idx else secrets.token_urlsafe(8)
        uid = new_user(login, pw, "student")
        db.add("students", user_id=uid, first_name=n["first_name"], last_name=n["last_name"], email=f"{login}@stud.univ.kz",
               phone=None, photo_url=None, group_id=gid, program_id=prog_id[pc], admission_year=yr, status="active")
        prof = rng.choices(PROFILES, PROFILE_W)[0]
        offs = pick_courses(rng, prog_dept[pc], sem_year - yr + 1, offerings, a.per_student, fixed=[offerings[0]] if i == demo_idx else ())
        students.append(dict(uid=uid, profile=prof, offs=offs, name=n, login=login))
        creds.append((login, pw, "student", n["first_name"], n["last_name"]))
    demo = students[demo_idx - 1]; demo["profile"] = "strong"
    ov = {(demo["uid"], demo["offs"][0]["id"]): "burnout"}                 # demo student: one course going badly
    prof_of = lambda s, o: ov.get((s["uid"], o["id"]), s["profile"])
    for s in students:
        db.add("user_settings", user_id=s["uid"], language=rng.choices(["kk", "ru", "en"], [.55, .35, .10])[0], theme=rng.choice(["light", "dark", "system"]))
        for o in s["offs"]:
            db.add("enrollments", student_id=s["uid"], offering_id=o["id"], section_id=None, status="enrolled", enrolled_at=dt(sem_start))
    for uid, _ in teachers + [(admin_uid, "")]:
        db.add("user_settings", user_id=uid, language=rng.choice(["ru", "en", "kk"]), theme="light")
    enrolled = {o["id"]: [s for s in students if o in s["offs"]] for o in offerings}

    # --- D. submissions and grades
    feats = {}                                                # (sid, oid) -> list of published grade facts
    state_cnt = {"published": 0, "draft": 0, "queue": 0}
    for o in offerings:
        for st in enrolled[o["id"]]:
            feats[(st["uid"], o["id"])] = []
        for A in o["assess"]:
            if A["due"] > NOW: continue
            age = (NOW - A["due"]).total_seconds() / 86400
            state = "published" if age > 6 else "draft" if age > 2 else "queue"
            for st in enrolled[o["id"]]:
                par = P(prof_of(st, o), A["week"]); sid_ = st["uid"]
                exam = A["kind"] != "assignment"
                submitted = rng.random() < (min(.99, par["sub"] + .05) if exam else par["sub"])
                late = False; sub_at = None
                if submitted and not exam and rng.random() > par["ontime"]:
                    late = True; hrs = min(rng.uniform(1, 60), age * 24 - 1)
                    if hrs < 1: late = False
                    sub_at = A["due"] + timedelta(hours=max(hrs, 0))
                if submitted and sub_at is None: sub_at = A["due"] - timedelta(hours=rng.uniform(1, 70))
                graded = state != "queue"
                status = "not_submitted" if not submitted else ("graded" if graded else ("late" if late else "submitted"))
                subid = db.add("submissions", assessment_id=A["id"], student_id=sid_, status=status,
                               file_url=f"/files/submissions/{A['id']}/{sid_}.pdf" if submitted and A["kind"] == "assignment" else None,
                               text_answer=None, attempt_no=1, submitted_at=sub_at)
                if not graded:
                    state_cnt['queue'] += 1; continue
                excused = submitted is False and rng.random() < .03
                if excused:
                    raw = None; pen = 0; frac = None
                elif not submitted:
                    raw = 0.0; pen = 0.0; frac = 0.0
                else:
                    raw = round(min(1, max(0, rng.gauss(par["score"], .08))) * A["max"] * 2) / 2
                    pen = 0.0
                    if late:
                        days = math.ceil(max(0, (sub_at - A["due"]).total_seconds() / 3600 - 2) / 24)
                        pen = round(raw * min(50, 10 * days) / 100, 1)
                    frac = max(0, raw - pen) / A["max"]
                pub = state == "published"
                gid = db.add("grades", assessment_id=A["id"], student_id=sid_, submission_id=subid, score=raw, late_penalty=pen,
                             is_excused=excused, status="published" if pub else "draft",
                             comment=rng.choice(["Хорошая работа", "Проверьте раздел 2", "Нужно больше примеров", None, None]) if submitted else None,
                             graded_by=o["teacher"], graded_at=A["due"] + timedelta(hours=18),
                             published_at=A["due"] + timedelta(days=2, hours=rng.randint(0, 10)) if pub else None)
                state_cnt[state] += 1
                if pub and frac is not None:
                    feats[(sid_, o["id"])].append(dict(week=A["week"], frac=frac, ontime=submitted and not late, a=A["id"]))
    # --- E. attendance, excuses, activity
    att_cnt = {}; recent_abs = []; unmarked = None
    first_t_offs = [o for o in offerings if o["teacher"] == teachers[0][0]]
    for o in offerings:
        past = [m for m in meetings[o["id"]] if m[1] <= NOW]
        if first_t_offs and o is first_t_offs[0] and past:
            unmarked = max(past, key=lambda m: m[1])[0]                    # one lesson left unmarked on purpose
        for mid, end, d, w in past:
            if mid == unmarked: continue
            for st in enrolled[o["id"]]:
                par = P(prof_of(st, o), w); r = rng.random()
                docid = None
                if r < par["att"]:
                    stt = "late" if rng.random() < .08 else "present"
                else:
                    stt = "absent"
                    if rng.random() < .10:
                        age = (NOW - end).days
                        ds = "pending" if age <= 7 and rng.random() < .15 else rng.choices(["approved", "rejected"], [.8, .2])[0]
                        docid = db.add("excuse_documents", student_id=st["uid"], meeting_id=mid, file_url=f"/files/excuses/{mid}_{st['uid']}.pdf",
                                       status=ds, reviewed_by=o["teacher"] if ds != "pending" else None,
                                       review_comment="Принято" if ds == "approved" else ("Документ не читается" if ds == "rejected" else None),
                                       uploaded_at=end + timedelta(hours=5), reviewed_at=end + timedelta(days=1) if ds != "pending" else None)
                        if ds == "approved": stt = "excused"
                    elif (NOW - end).days <= 10: recent_abs.append((o, st, mid, end))
                db.add("attendance", meeting_id=mid, student_id=st["uid"], status=stt, marked_by=o["teacher"],
                       marked_at=end + timedelta(minutes=5), excuse_document_id=docid)
                if stt != "excused":
                    k = (st["uid"], o["id"], w); x = att_cnt.get(k, (0, 0))
                    att_cnt[k] = (x[0] + (stt != "absent"), x[1] + 1)
    n_pend = sum(1 for d in db.rows["excuse_documents"] if d["status"] == "pending")
    taken = {(d["student_id"], d["meeting_id"]) for d in db.rows["excuse_documents"]}
    for o, st, mid, end in recent_abs:
        if n_pend >= 3: break
        if (st["uid"], mid) in taken: continue
        db.add("excuse_documents", student_id=st["uid"], meeting_id=mid, file_url=f"/files/excuses/{mid}_{st['uid']}.pdf", status="pending",
               reviewed_by=None, review_comment=None, uploaded_at=end + timedelta(hours=6), reviewed_at=None)
        n_pend += 1
    logins = {}
    for o in offerings:
        for st in enrolled[o["id"]]:
            for w in range(1, W + 1):
                par = P(prof_of(st, o), w); sc = .55 if w == W else 1
                lg = int(max(0, rng.gauss(par["act"], 1.5)) * sc)
                db.add("weekly_activity", student_id=st["uid"], offering_id=o["id"], week_no=w, logins=lg,
                       materials_viewed=int(lg * rng.uniform(2, 4)), forum_posts=int(max(0, rng.gauss(par["act"] * .3, .8)) * sc),
                       minutes_online=int(lg * rng.uniform(15, 25)))
                logins[(st["uid"], o["id"], w)] = lg
    mean_login = {(o["id"], w): max(1, sum(logins[(st["uid"], o["id"], w)] for st in enrolled[o["id"]]) / max(1, len(enrolled[o["id"]])))
                  for o in offerings for w in range(1, W + 1)}

    # --- H. risk (rule-based placeholder until the trained OULAD model is plugged in)
    mv = db.add("model_versions", version="rule-based-v0", trained_at=NOW, metrics=json.dumps({"note": "placeholder, replace with trained model"}),
                description="Heuristic baseline used to fill demo data")
    pred = {}                                                 # (sid, oid, w) -> dict
    for o in offerings:
        for st in enrolled[o["id"]]:
            for w in range(3, W + 1):
                g = [e for e in feats[(st["uid"], o["id"])] if e["week"] <= w]
                score = sum(e["frac"] for e in g) / len(g) if g else None
                ontime = sum(e["ontime"] for e in g) / len(g) if g else None
                att_a = sum(att_cnt.get((st["uid"], o["id"], k), (0, 0))[0] for k in range(1, w + 1))
                att_m = sum(att_cnt.get((st["uid"], o["id"], k), (0, 0))[1] for k in range(1, w + 1))
                att = att_a / att_m if att_m else None
                ws = range(max(1, w - 2), w + 1)
                act = sum(logins[(st["uid"], o["id"], k)] / mean_login[(o["id"], k)] for k in ws) / len(ws)
                c = {"avg_score": 2.2 * (.75 - score) if score is not None else 0.0,
                     "attendance": 1.8 * (.88 - att) if att is not None else 0.0,
                     "on_time_rate": 1.2 * (.8 - ontime) if ontime is not None else 0.0,
                     "activity": .9 * (1 - min(act, 1.5))}
                p = round(sigmoid(-.75 + sum(c.values())), 4)
                ctr = 100 * (.7 * (score if score is not None else .75) + .3 * (att if att is not None else .88))
                pid = db.add("risk_predictions", student_id=st["uid"], offering_id=o["id"], week_no=w, model_id=mv, risk_probability=p,
                             risk_level=level(p), predicted_score_low=round(max(0, ctr - 6), 1), predicted_score_high=round(min(100, ctr + 6), 1), created_at=NOW)
                val = {"avg_score": score, "attendance": att, "on_time_rate": ontime, "activity": act}
                pred[(st["uid"], o["id"], w)] = dict(id=pid, p=p, lvl=level(p), c=c, val=val)
                if w == W:
                    top = sorted(c.items(), key=lambda kv: -abs(kv[1]))[:4]
                    for f, imp in top:
                        v = val[f]; vtxt = round((v if v is not None else 0) * 100)
                        i = 0 if imp > 0 else 1
                        db.add("prediction_explanations", prediction_id=pid, feature=f, impact=round(imp, 4),
                               text_kk=FEAT_TXT[f]["kk"][i].format(v=vtxt), text_ru=FEAT_TXT[f]["ru"][i].format(v=vtxt), text_en=FEAT_TXT[f]["en"][i].format(v=vtxt))
                    if level(p) != "low":
                        for rk, (f, imp) in enumerate([x for x in sorted(c.items(), key=lambda kv: -kv[1]) if x[1] > 0][:3]):
                            db.add("recommendations", student_id=st["uid"], offering_id=o["id"], priority=rk + 1,
                                   text=REC_TXT[f].format(c=o["name"]), is_done=False, created_at=NOW)
            if rng.random() < .35:
                db.add("student_goals", student_id=st["uid"], offering_id=o["id"], target_grade=rng.choice(["A", "A-", "B+", "B"]), updated_at=NOW - timedelta(days=10))
    for o in offerings:
        for w in range(3, W + 1):
            ps = [pred[(st["uid"], o["id"], w)]["p"] for st in enrolled[o["id"]]]
            if not ps: continue
            lv = [level(x) for x in ps]
            db.add("course_risk_snapshots", offering_id=o["id"], week_no=w, low_count=lv.count("low"), medium_count=lv.count("medium"),
                   high_count=lv.count("high"), avg_risk=round(sum(ps) / len(ps), 4))
    overall = {}
    for st in students:
        for w in range(3, W + 1):
            mx = max(pred[(st["uid"], o["id"], w)]["p"] for o in st["offs"])
            db.add("student_risk_overall", student_id=st["uid"], semester_id=sem_id, week_no=w, risk_probability=mx, risk_level=level(mx), method="max_over_courses")
            if w == W: overall[st["uid"]] = mx

    # --- I. advising, interventions, office hours
    adv = teachers[0][0]; adv_offs = [o for o in offerings if o["teacher"] == adv]
    cand = {s["uid"]: s for o in adv_offs for s in enrolled[o["id"]]}
    ranked = sorted(cand.values(), key=lambda s: -overall[s["uid"]])
    hi = [s for s in ranked if level(overall[s["uid"]]) == "high"][:4]
    me = [s for s in ranked if level(overall[s["uid"]]) == "medium"][:3]
    lo = [s for s in reversed(ranked) if level(overall[s["uid"]]) == "low"][:3]
    advisees = (hi + me + lo) or ranked[:10]
    for s in advisees:
        db.add("advisor_assignments", advisor_id=adv, student_id=s["uid"], starts_on=sem_start, ends_on=None, assigned_by=admin_uid)
    if len(teachers) > 1 and students:
        db.add("advisor_assignments", advisor_id=teachers[1][0], student_id=students[10 % len(students)]["uid"], starts_on=sem_start - timedelta(days=200),
               ends_on=today - timedelta(days=20), assigned_by=admin_uid)
    w_hi = [(s, o) for o in adv_offs for s in enrolled[o["id"]] if pred[(s["uid"], o["id"], W)]["lvl"] == "high"][:5]
    kinds = ["message", "meeting", "message", "referral", "meeting"]
    outs = ["Студент ответил, обещал сдать работу", "Договорились о плане подтягивания", "Ответа пока нет", "Направлен к эдвайзеру", "Посещаемость улучшилась"]
    for i, (s, o) in enumerate(w_hi):
        db.add("interventions", student_id=s["uid"], offering_id=o["id"], author_id=adv, kind=kinds[i % 5], scope="course",
               summary=f"Рост риска по курсу «{o['name']}», связался со студентом", outcome=outs[i % 5],
               recheck_on=today + timedelta(days=7 - i), prediction_id=pred[(s["uid"], o["id"], W)]["id"], created_at=NOW - timedelta(days=i + 1))
    for i, s in enumerate(advisees[:3]):
        db.add("interventions", student_id=s["uid"], offering_id=None, author_id=adv, kind=["meeting", "referral", "other"][i], scope="advising",
               summary="Встреча эдвайзера по общей успеваемости", outcome="Составлен план на семестр", recheck_on=today + timedelta(days=14),
               prediction_id=None, created_at=NOW - timedelta(days=3 + i))
    for uid, _ in teachers:
        past_slot = db.add("office_hour_slots", teacher_id=uid, starts_at=dt(today - timedelta(days=5), 16), ends_at=dt(today - timedelta(days=5), 17), room_id=rng.choice(room_ids), capacity=2)
        slots = [db.add("office_hour_slots", teacher_id=uid, starts_at=dt(today + timedelta(days=d), 16), ends_at=dt(today + timedelta(days=d), 17),
                        room_id=rng.choice(room_ids), capacity=2) for d in (2, 4, 9)]
        if uid == adv and advisees:
            db.add("appointments", slot_id=past_slot, student_id=advisees[0]["uid"], topic="План на семестр", status="done", notes="Обсудили нагрузку")
            for j, st in enumerate(advisees[1:4]):
                db.add("appointments", slot_id=slots[j % 3], student_id=st["uid"], topic="Низкая посещаемость", status=["requested", "requested", "accepted"][j], notes=None)
            for st in advisees[:3]:
                db.add("access_log", teacher_id=adv, student_id=st["uid"], page="advising/profile", accessed_at=NOW - timedelta(hours=rng.randint(1, 50)))

    # --- F. communication, announcements, forum, notifications
    ntext = {"new_grade": "Опубликована новая оценка", "deadline": "Приближается дедлайн", "message": "Новое сообщение", "risk_up": "Обратите внимание на курс"}
    for o in offerings:
        db.add("announcements", author_id=o["teacher"], offering_id=o["id"], title="Добро пожаловать в курс", body=f"Начинаем курс «{o['name']}». Материалы в разделе Materials.", published_at=dt(sem_start))
        db.add("announcements", author_id=o["teacher"], offering_id=o["id"], title="Напоминание о дедлайне", body="Проверьте ближайшие сроки сдачи заданий.", published_at=NOW - timedelta(days=1))
        cv = db.add("conversations", kind="course", offering_id=o["id"], title=f"{o['code']} chat", created_at=dt(sem_start))
        db.add("conversation_participants", conversation_id=cv, user_id=o["teacher"], last_read_at=NOW)
        for st in enrolled[o["id"]]: db.add("conversation_participants", conversation_id=cv, user_id=st["uid"], last_read_at=None)
        db.add("messages", conversation_id=cv, sender_id=o["teacher"], body="Вопросы по заданиям пишите сюда.", attachment_url=None, sent_at=NOW - timedelta(days=2))
        for t in range(2):
            th = db.add("discussion_threads", offering_id=o["id"], author_id=rng.choice(enrolled[o["id"]] or students)["uid"], title=rng.choice(["Вопрос по заданию", "Не понял тему недели", "Где материалы?"]), is_pinned=False, created_at=NOW - timedelta(days=rng.randint(1, 8)))
            for _ in range(rng.randint(2, 3)):
                db.add("discussion_posts", thread_id=th, author_id=rng.choice([o["teacher"]] + [x["uid"] for x in enrolled[o["id"]][:5]]), body="Посмотрите материалы недели, там есть пример.", created_at=NOW - timedelta(days=rng.randint(0, 3)))
        db.add("feedback_surveys", offering_id=o["id"], opens_at=dt(sem_start + timedelta(weeks=14)), closes_at=dt(sem_start + timedelta(weeks=16, days=-4)))
    db.add("announcements", author_id=admin_uid, offering_id=None, title="Расписание экзаменов", body="Расписание сессии появится в начале декабря.", published_at=NOW - timedelta(days=4))
    db.add("announcements", author_id=admin_uid, offering_id=None, title="Работа библиотеки", body="Библиотека работает до 20:00.", published_at=NOW - timedelta(days=9))
    for uid, _ in teachers:
        db.add("message_templates", teacher_id=uid, title="Пропущены задания", body="Заметил, что вы пропустили несколько заданий. Давайте обсудим, чем помочь.")
        for t in ["Хорошая работа", "Нужно больше примеров", "Проверьте формулы", "Не хватает выводов"]:
            db.add("comment_bank", teacher_id=uid, text=t)
    db.add("message_templates", teacher_id=None, title="Приглашение на встречу", body="Приглашаю вас на встречу в часы приёма.")
    for s, o in w_hi[:3]:
        cv = db.add("conversations", kind="direct", offering_id=o["id"], title=None, created_at=NOW - timedelta(days=1))
        db.add("conversation_participants", conversation_id=cv, user_id=adv, last_read_at=NOW)
        db.add("conversation_participants", conversation_id=cv, user_id=s["uid"], last_read_at=None)
        m1 = db.add("messages", conversation_id=cv, sender_id=adv, body="Заметил, что вы пропустили задания. Давайте обсудим, чем помочь.", attachment_url=None, sent_at=NOW - timedelta(days=1))
        db.add("message_reads", message_id=m1, user_id=adv, read_at=NOW - timedelta(days=1))
    def notif(uid, typ, title, hrs=0, link=None):
        db.add("notifications", user_id=uid, type=typ, title=title, link=link, is_read=rng.random() < .3, created_at=NOW - timedelta(hours=hrs))
    told = set(); aset = {o['id']: {x['id'] for x in o['assess']} for o in offerings}
    for o in offerings:
        q = sum(1 for r in db.rows["submissions"] if r["status"] in ("submitted", "late") and r["assessment_id"] in {x["id"] for x in o["assess"]})
        if q: notif(o["teacher"], "submission_new", f"{q} работ ждут проверки по курсу «{o['name']}»", 3)
        drafts = sum(1 for r in db.rows["grades"] if r["status"] == "draft" and r["assessment_id"] in {x["id"] for x in o["assess"]})
        if drafts: notif(o["teacher"], "grading_due", f"Оценки по курсу «{o['name']}» ещё не опубликованы", 5)
        for st in enrolled[o["id"]]:
            recent = [g for g in db.rows["grades"] if g["student_id"] == st["uid"] and g["status"] == "published"
                      and g["published_at"] >= NOW - timedelta(days=10) and g["assessment_id"] in aset[o["id"]]]
            if recent and (st is demo or rng.random() < .25):
                notif(st["uid"], "new_grade", f"Новая оценка по курсу «{o['name']}»", rng.randint(30, 150))
            nxt = [A for A in o["assess"] if NOW < A["due"] <= NOW + timedelta(days=3)]
            if nxt and st["uid"] not in told:
                told.add(st["uid"]); notif(st["uid"], "deadline", f"{nxt[0]['title']} по курсу «{o['name']}»: срок через 2 дня", 6)
            if W - 1 >= 3 and pred[(st["uid"], o["id"], W)]["p"] - pred[(st["uid"], o["id"], W - 1)]["p"] >= .06:
                notif(st["uid"], "risk_up", f"Обратите внимание на курс «{o['name']}»", 8); notif(o["teacher"], "risk_up", f"Рост риска у студента по курсу «{o['name']}»", 8)
    for d in db.rows["excuse_documents"]:
        if d["status"] == "pending":
            mtg = next(m for m in db.rows["class_meetings"] if m["id"] == d["meeting_id"])
            notif(next(o["teacher"] for o in offerings if o["id"] == mtg["offering_id"]), "excuse_pending", "Справка студента ждёт проверки", 4)
    for ap in db.rows["appointments"]:
        if ap["status"] == "requested": notif(adv, "appointment_request", "Новая запись на приём", 7)
    if unmarked: notif(adv, "grading_due", "Не отмечена посещаемость за последнее занятие", 2)
    for uid in [s["uid"] for s in students]:
        for t in ["new_grade", "deadline", "message", "risk_up"]:
            db.add("notification_settings", user_id=uid, type=t, by_email=rng.random() < .7, in_app=True)
    for uid, _ in teachers:
        for t in ["submission_new", "excuse_pending", "risk_up", "appointment_request", "grading_due", "message"]:
            db.add("notification_settings", user_id=uid, type=t, by_email=rng.random() < .6, in_app=True)

    # --- J. student tools and secondary
    db.add("calendar_events", user_id=demo["uid"], title="Встреча с командой проекта", starts_at=NOW + timedelta(days=1, hours=3), ends_at=None, note=None)
    for A in demo["offs"][0]["assess"]:
        if NOW < A["due"] <= NOW + timedelta(days=14):
            db.add("study_planner_tasks", student_id=demo["uid"], offering_id=demo["offs"][0]["id"], assessment_id=A["id"], title=f"Подготовить {A['title']}", column_name="this_week", due_on=A["due"].date())
    cs = db.add("chat_sessions", user_id=demo["uid"], created_at=NOW - timedelta(hours=2))
    for snd, b in [("user", "Какие у меня дедлайны?"), ("assistant", "Ближайший дедлайн: Assignment 5 через 2 дня."), ("user", "Как поднять оценку?")]:
        db.add("chat_messages", session_id=cs, sender=snd, body=b, created_at=NOW - timedelta(hours=2))
    for st in rng.sample(students, min(6, len(students))):
        db.add("document_requests", student_id=st["uid"], doc_type=rng.choice(["Справка с места учёбы", "Транскрипт"]), status=rng.choice(["new", "processing", "ready"]), created_at=NOW - timedelta(days=rng.randint(0, 9)))
    for t, u in [("Электронная библиотека", "https://library.univ.kz"), ("Научные журналы", "https://journals.univ.kz"), ("Онлайн-курсы", "https://learn.univ.kz")]:
        db.add("library_resources", title=t, url=u, description=None, category="resources")
    for q, an in [("Как сбросить пароль?", "Обратитесь в поддержку: пароли выдаёт администратор."), ("Как загрузить справку?", "Откройте Attendance и нажмите «Загрузить справку»."),
                  ("Где посмотреть оценки?", "Раздел Grades."), ("Как связаться с преподавателем?", "Через раздел Messages.")]:
        db.add("faq_items", question=q, answer=an, language="ru", sort_order=len(db.rows["faq_items"]))
    prof_risk = {}
    for st in students:
        prof_risk.setdefault(st["profile"], []).append(sum(pred[(st["uid"], o["id"], W)]["p"] for o in st["offs"]) / len(st["offs"]))
    info = dict(profile_mean_risk={k: round(sum(v) / len(v), 2) for k, v in prof_risk.items()}, week=W, today=str(today), demo_student=demo["login"], advisor="T001", teacher="T002", admin="A001",
                states=state_cnt, advisees=len(advisees), risk_levels={l: sum(1 for k, v in pred.items() if k[2] == W and v["lvl"] == l) for l in ("low", "medium", "high")})
    per_off = [len(enrolled[o["id"]]) for o in offerings]
    clashes = sum(1 for s in students for x in range(len(s["offs"])) for y in range(x + 1, len(s["offs"])) if s["offs"][x]["cells"] & s["offs"][y]["cells"])
    info.update(courses_in_catalog=len(catalog), offerings=len(offerings), teachers=len(teachers), students=len(students),
                teacher_load_max=max(load.values()), teachers_without_courses=sum(1 for v in load.values() if v == 0),
                students_per_offering=dict(min=min(per_off), avg=round(sum(per_off) / len(per_off), 1), max=max(per_off)),
                students_with_time_clash=clashes, demo_courses=[o["code"] for o in demo["offs"]], advisor_courses=[o["code"] for o in offerings if o["teacher"] == teachers[0][0]])
    if a.courses_out:
        with open(a.courses_out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(["code", "name", "credits", "department", "offer"])
            for c in catalog: w.writerow([c["code"], c["name"], c["credits"], c["department"], int(c["code"] in offered_codes)])
    return db, creds, info

# ------------------------------------------------------------------ validation
def validate(db):
    errs = []
    vals = {t: {c: {r.get(c) for r in rows} for c in SCHEMA[t]["cols"]} for t, rows in db.rows.items()}
    for t, sc in SCHEMA.items():
        for r in db.rows[t]:
            for c, rt, rc in sc["fks"]:
                v = r.get(c)
                if v is not None and v not in vals[rt][rc]: errs.append(f"FK {t}.{c}={v} -> {rt}.{rc}")
            for c in r:
                if c not in sc["cols"]: errs.append(f"unknown column {t}.{c}")
        for key in sc["uniq"]:
            seen = set()
            for r in db.rows[t]:
                k = tuple(r.get(c) for c in key)
                if None in k: continue
                if k in seen: errs.append(f"duplicate {t}{key}={k}"); break
                seen.add(k)
    for r in db.rows["assessment_categories"]: pass
    tot = {}
    for r in db.rows["assessment_categories"]: tot[r["offering_id"]] = tot.get(r["offering_id"], 0) + r["weight_pct"]
    errs += [f"weights of offering {o} = {w}" for o, w in tot.items() if abs(w - 100) > 1e-9]
    tot = {}
    for r in db.rows["assessments"]: tot[r["offering_id"]] = round(tot.get(r["offering_id"], 0) + float(r["weight_pct"]), 2)
    errs += [f"assessment weights of offering {o} = {w}" for o, w in tot.items() if w != 100]
    off_t = {o["id"]: o["teacher_id"] for o in db.rows["course_offerings"]}
    for what, keyf in (("teacher", lambda s: off_t[s["offering_id"]]), ("room", lambda s: s["room_id"])):
        seen = set()
        for s in db.rows["schedule_slots"]:
            k = (keyf(s), s["weekday"], s["start_time"])
            if k in seen: errs.append(f"{what} double-booked: {k}")
            seen.add(k)
    names = [(r["first_name"], r["last_name"]) for t in ("students", "teachers") for r in db.rows[t]]
    if len(names) != len(set(names)): errs.append("full names are not unique")
    return errs

# ------------------------------------------------------------------ output
def cols_of(db, t):
    cols = []
    for r in db.rows[t]:
        for c in r:
            if c not in cols: cols.append(c)
    return cols

def write_csv(db, d):
    Path(d).mkdir(parents=True, exist_ok=True)
    for t in sorted(SCHEMA, key=lambda x: SCHEMA[x]["order"]):
        cols = cols_of(db, t)
        with open(Path(d) / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(cols)
            for r in db.rows[t]: w.writerow([r.get(c) for c in cols])

def write_pg(db, dsn, init, reset):
    import psycopg
    order = sorted(SCHEMA, key=lambda x: SCHEMA[x]["order"])
    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        if init: cur.execute((HERE / "schema.sql").read_text(encoding="utf-8"))
        if reset: cur.execute("TRUNCATE " + ", ".join(order) + " RESTART IDENTITY CASCADE")
        for t in order:
            if not db.rows[t]: continue
            cols = cols_of(db, t)
            with cur.copy(f"COPY {t} ({', '.join(cols)}) FROM STDIN") as cp:
                for r in db.rows[t]: cp.write_row([r.get(c) for c in cols])
            if SCHEMA[t]["serial"]:
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{t}','id'), (SELECT MAX(id) FROM {t}))")
        conn.commit()

def main():
    ap = argparse.ArgumentParser()
    default_csv = HERE / "SDU_Unique_Course_List.csv"
    ap.add_argument("--students", type=int, default=300); ap.add_argument("--teachers", type=int, default=40)
    ap.add_argument("--offered", type=int, default=60, help="how many catalog courses run this semester (0 = all eligible)")
    ap.add_argument("--per-student", type=int, default=5, help="courses per student"); ap.add_argument("--default-credits", type=int, default=5)
    ap.add_argument("--courses-out", default="courses_resolved.csv")
    ap.add_argument("--seed", type=int, default=42); ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--courses", default=str(default_csv) if default_csv.exists() else None); ap.add_argument("--dsn"); ap.add_argument("--init", action="store_true"); ap.add_argument("--reset", action="store_true")
    ap.add_argument("--csv-dir"); ap.add_argument("--out", default="credentials.csv")
    a = ap.parse_args()
    db, creds, info = generate(a)
    errs = validate(db)
    print("rows:", {t: len(r) for t, r in db.rows.items() if r}); print("info:", info)
    if errs: print("VALIDATION ERRORS:", *errs[:30], sep="\n  "); sys.exit(1)
    print("validation OK (foreign keys, unique keys, weights = 100, unique full names)")
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["login_id", "password", "role", "first_name", "last_name"]); w.writerows(creds)
    if a.csv_dir: write_csv(db, a.csv_dir); print("CSV written to", a.csv_dir)
    if a.dsn: write_pg(db, a.dsn, a.init, a.reset); print("data loaded into PostgreSQL")

if __name__ == "__main__":
    main()
