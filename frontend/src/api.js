// Связь фронта с Flask-API. В dev запросы идут на тот же адрес и проксируются
// Vite-ом на http://127.0.0.1:8000 (см. vite.config.js), поэтому cookie-сессия работает.
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

async function raw(path, method = 'GET', body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch { /* пустой ответ */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `API ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

// старый интерфейс (оставлен, чтобы остальной код работал)
export async function apiGet(path, fallback) {
  if (DEMO_MODE) return fallback;
  try { return await raw(path.startsWith('/api') ? path : `/api${path}`); }
  catch (e) { console.warn(`Could not load ${path}`, e); return fallback; }
}
export async function apiSend(path, method, body) {
  if (DEMO_MODE) return { demo: true };
  return raw(path.startsWith('/api') ? path : `/api${path}`, method, body);
}

export const get = (p) => raw(p);
export const send = (p, m, b) => raw(p, m, b);

export async function login(loginId, password) {
  return raw('/api/auth/login', 'POST', { login_id: loginId, password });
}
export const logout = () => raw('/api/auth/logout', 'POST', {});
export const me = () => raw('/api/me');

// ---------------------------------------------------------------- адаптеры
const PALETTE = ['#4f6bed', '#14a38b', '#e6a23c', '#a16ae8', '#e36d87', '#219ebc'];
const num = (v) => (v === null || v === undefined ? null : Number(v));
const pct = (p) => (p === null || p === undefined ? null : Math.round(Number(p) * 100));
const cap = (l) => (l ? l[0].toUpperCase() + l.slice(1) : 'Low');
const fmtDate = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
};
const levelOfAvg = (p) => (p >= 0.7 ? 'high' : p >= 0.4 ? 'medium' : 'low');
const safe = async (fn, fb) => { try { return await fn(); } catch (e) { console.warn(e); return fb; } };

export async function loadStudent() {
  const [cs, rk, ov, dl, nt] = await Promise.all([
    get('/api/student/courses'),
    safe(() => get('/api/student/risk?lang=en'), { courses: [] }),
    safe(() => get('/api/student/overall-risk'), { items: [] }),
    safe(() => get('/api/student/deadlines'), { items: [] }),
    safe(() => get('/api/notifications'), { items: [] }),
  ]);
  const riskBy = {};
  (rk.courses || []).forEach((r) => { riskBy[r.offering_id] = r; });
  const nextDue = {};
  (dl.items || []).forEach((d) => {
    if (d.submission_status === 'not_submitted' && new Date(d.due_at) >= new Date()) {
      if (!nextDue[d.offering_id] || new Date(d.due_at) < new Date(nextDue[d.offering_id])) nextDue[d.offering_id] = d.due_at;
    }
  });
  const courses = (cs.courses || []).map((c, i) => {
    const r = riskBy[c.offering_id];
    const lat = r && r.latest;
    return {
      id: c.offering_id, code: c.code, name: c.name, teacher: c.teacher || '', credits: c.credits,
      progress: Math.round(Number(c.weight_done || 0)), grade: c.current_percent === null ? 0 : Math.round(c.current_percent),
      letter: c.letter, color: c.color || PALETTE[i % PALETTE.length],
      deadline: fmtDate(nextDue[c.offering_id]) || '—', room: '', time: '', type: 'Lecture',
      risk: (lat && lat.risk_level) || (c.risk && c.risk.risk_level) || 'low',
      riskPct: lat ? pct(lat.risk_probability) : c.risk ? pct(c.risk.risk_probability) : null,
      students: 0,
    };
  });
  const history = {};
  const factors = {};
  (rk.courses || []).forEach((r) => {
    history[r.offering_id] = (r.history || []).map((h) => ({ week: `W${h.week_no}`, risk: pct(h.risk_probability) }));
    factors[r.offering_id] = r.factors || [];
  });
  const range = {};
  (rk.courses || []).forEach((r) => {
    const l = r.latest;
    if (l && l.predicted_score_low !== null && l.predicted_score_low !== undefined) range[r.offering_id] = `${Math.round(l.predicted_score_low)}–${Math.round(l.predicted_score_high)}`;
  });
  const gl = await Promise.all(courses.map((c) => safe(() => get(`/api/student/courses/${c.id}/grades`), { assessments: [] })));
  const grades = {};
  courses.forEach((c, i) => {
    grades[c.id] = (gl[i].assessments || []).map((a) => {
      const scored = a.score !== null && a.score !== undefined;
      const past = new Date(a.due_at) < new Date();
      const status = scored ? 'Graded' : a.submission_status && a.submission_status !== 'not_submitted' ? 'Submitted' : past ? 'Overdue' : 'In progress';
      return [a.title, Number(a.weight_pct), scored ? Number(a.score) : '—', fmtDate(a.due_at), status, Number(a.max_score)];
    });
  });
  const weeklyRisk = (ov.items || []).map((h) => ({ week: `W${h.week_no}`, risk: pct(h.risk_probability) }));
  const assignments = (dl.items || []).slice(0, 8).map((d) => ({
    id: d.assessment_id, title: d.title, course: d.code, due: fmtDate(d.due_at), points: `${d.weight_pct}%`,
    status: { not_submitted: new Date(d.due_at) < new Date() ? 'Overdue' : 'In progress', submitted: 'Submitted', late: 'Submitted', graded: 'Graded' }[d.submission_status] || 'In progress',
    color: (courses.find((c) => c.id === d.offering_id) || {}).color || PALETTE[0],
  }));
  const notifications = (nt.items || []).map((n) => ({
    id: n.id, title: n.title, detail: '', time: fmtDate(n.created_at),
    type: n.type === 'risk_up' ? 'deadline' : n.type, unread: !n.is_read,
  }));
  return { week: cs.week, courses, history, factors, range, grades, weeklyRisk, assignments, notifications, overallThreshold: rk.threshold, students: [], studentsByOid: {} };
}

export async function loadTeacher() {
  const [cs, nt] = await Promise.all([
    get('/api/teacher/courses'),
    safe(() => get('/api/notifications'), { items: [] }),
  ]);
  const base = cs.courses || [];
  const ins = await Promise.all(base.map((c) => safe(() => get(`/api/teacher/courses/${c.offering_id}/insights?lang=en`), null)));
  const courses = base.map((c, i) => {
    const avg = Number(c.avg_risk || 0);
    return {
      id: c.offering_id, code: c.code, name: c.name, teacher: '', credits: c.credits, progress: 0, grade: 0,
      color: c.color || PALETTE[i % PALETTE.length], deadline: '—', room: '', time: '', type: 'Lecture',
      risk: levelOfAvg(avg), riskPct: Math.round(avg * 100), students: Number(c.students || 0),
      low: Number(c.low_count || 0), medium: Number(c.medium_count || 0), high: Number(c.high_count || 0),
    };
  });
  const byId = {};
  const trendBy = {};
  const studentsByOid = {};
  ins.forEach((r, i) => {
    if (!r) return;
    const oid = base[i].offering_id;
    trendBy[oid] = (r.trend || []).map((t) => ({ week: `W${t.week_no}`, risk: Math.round(Number(t.avg_risk) * 100) }));
    studentsByOid[oid] = r.students.map((s) => ({
      id: String(s.student_id), sid: s.student_id, name: `${s.first_name} ${s.last_name}`, group: `G${s.group_id ?? ''}`,
      grade: s.predicted_score_low !== null ? Math.round((Number(s.predicted_score_low) + Number(s.predicted_score_high)) / 2) : 0,
      attendance: 0, risk: cap(s.risk_level), riskPct: pct(s.risk_probability),
      change: s.change === null ? '—' : `${s.change >= 0 ? '+' : '−'}${Math.abs(Math.round(s.change * 100))}%`,
      reason: (s.factors[0] && s.factors[0].text) || '—', last: s.last_contact ? fmtDate(s.last_contact) : 'No contact yet',
      oid,
    }));
    studentsByOid[oid].forEach((s) => {
      const prev = byId[s.id];
      if (!prev || (s.riskPct || 0) > (prev.riskPct || 0)) byId[s.id] = { ...s, oids: [...(prev ? prev.oids : []), oid] };
      else prev.oids.push(oid);
    });
  });
  const students = Object.values(byId).sort((a, b) => (b.riskPct || 0) - (a.riskPct || 0));
  const notifications = (nt.items || []).map((n) => ({
    id: n.id, title: n.title, detail: '', time: fmtDate(n.created_at), type: n.type, unread: !n.is_read,
  }));
  return { week: cs.week, courses, history: {}, factors: {}, weeklyRisk: [], assignments: [], notifications, students, studentsByOid, trendBy };
}

export const loadStudentGrades = (oid) => get(`/api/student/courses/${oid}/grades`);
export const loadGradebook = (oid) => get(`/api/teacher/courses/${oid}/gradebook`);
export const saveGrade = (assessment_id, student_id, score, reason) =>
  raw('/api/teacher/grades', 'PUT', { assessment_id, student_id, score, reason, status: 'published' });
export const predict = (offering_id, overrides, student_id) =>
  raw('/api/predict', 'POST', { offering_id, overrides, student_id });
export const readAllNotifications = () => raw('/api/notifications/read-all', 'POST', {});

export const loadStudentCurriculum = () => get('/api/student/curriculum');

// ---------------------------------------------------------------- файлы
// Файл с сервера (отчёт, шаблон оценок): сохраняется через браузер. Возвращает имя файла.
export async function download(path, fallbackName = 'report.csv') {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' });
  if (!res.ok) {
    let d = null;
    try { d = await res.json(); } catch { /* не JSON */ }
    const err = new Error((d && d.error) || `API ${res.status}`);
    err.status = res.status;
    throw err;
  }
  const blob = await res.blob();
  const m = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') || '');
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = m ? m[1] : fallbackName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return a.download;
}

// Отправка файла (multipart). Возвращает ответ целиком и при ошибке: в нём список строк с ошибками.
export async function upload(path, fields) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null) fd.append(k, v); });
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', credentials: 'include', body: fd });
  let data = null;
  try { data = await res.json(); } catch { /* пустой ответ */ }
  return { ok: res.ok, status: res.status, data };
}
