// Страницы, подключённые к живому API: отчёты (E), очередь куратора и журнал (D),
// объявления (B), импорт оценок из CSV (G). В демо-режиме App.jsx показывает старые демо-страницы.
import React, { useEffect, useState } from 'react';
import {
  AlertCircle, CalendarClock, ChevronDown, ChevronRight, ClipboardCheck, Download, Eye,
  FileSpreadsheet, FolderOpen, Mail, MessageCircle, Plus, Search, ShieldCheck, Upload, Users, X,
} from 'lucide-react';
import { get, send, download, upload } from './api';

// ---------------------------------------------------------------- общие элементы (те же классы, что в App.jsx)
const statusClass = (status) => {
  const s = String(status).toLowerCase();
  if (['low', 'ok', 'new', 'done', 'recorded', 'unchanged'].some((x) => s.includes(x))) return 'success';
  if (['medium', 'update', 'due', 'open'].some((x) => s.includes(x))) return 'warning';
  if (['high', 'error', 'attention', 'overdue'].some((x) => s.includes(x))) return 'danger';
  return 'neutral';
};
const initials = (name = 'Student') => name.split(' ').map((p) => p[0]).slice(0, 2).join('').toUpperCase();
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : '—');
const pct = (p) => (p === null || p === undefined ? '—' : `${Math.round(Number(p) * 100)}%`);
const day = (iso) => (iso ? new Date(String(iso).replace(' ', 'T')).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—');

function PageHeading({ eyebrow, title, subtitle, actions }) {
  return <div className="page-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{actions && <div className="heading-actions">{actions}</div>}</div>;
}
function Button({ children, variant = 'primary', icon: Icon, onClick, type = 'button', disabled = false, size = '' }) {
  return <button type={type} disabled={disabled} className={`btn ${variant} ${size}`} onClick={onClick}>{Icon && <Icon size={16}/>}{children}</button>;
}
function Card({ children, className = '', title, subtitle, action }) {
  return <section className={`card ${className}`}>{(title || action) && <div className="card-header"><div>{title && <h3>{title}</h3>}{subtitle && <p>{subtitle}</p>}</div>{action}</div>}{children}</section>;
}
function StatCard({ label, value, foot, icon: Icon, color = 'blue' }) {
  return <div className="stat-card"><div className="stat-top"><span>{label}</span><span className={`stat-icon ${color}`}><Icon size={18}/></span></div><div className="stat-value">{value}</div><div className="stat-foot"><span>{foot}</span></div></div>;
}
function Avatar({ name }) { return <div className="avatar avatar-sm" style={{ '--avatar-color': '#dfe7ff' }}>{initials(name)}</div>; }
function Status({ children }) { return <span className={`status ${statusClass(children)}`}><i/>{children}</span>; }
function EmptyState({ title, text }) {
  return <div className="empty-state"><div className="empty-icon"><FolderOpen size={25}/></div><h3>{title}</h3><p>{text}</p></div>;
}
const row = { display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' };

// ================================================================= E: отчёты
const REPORTS = [
  ['course-performance', 'Course performance', 'Current percent, letter grade, absences and risk level for every student.'],
  ['attendance-summary', 'Attendance summary', 'Present, late, absent and excused lessons, and who is over the absence limit.'],
  ['gradebook', 'Gradebook export', 'One column per assessment with every score, including grades not yet published.'],
  ['student-risk', 'Student risk overview', 'Risk level, change since last week, main factors and the last contact, highest risk first.'],
];

export function LiveReportsPage({ courses, onToast }) {
  const [oid, setOid] = useState(courses[0]?.id);
  const [kind, setKind] = useState(REPORTS[0][0]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [recent, setRecent] = useState([]);
  useEffect(() => { setPreview(null); }, [oid, kind]);
  useEffect(() => { if (!oid && courses[0]) setOid(courses[0].id); }, [courses]);
  if (!courses.length) return <><PageHeading eyebrow="REPORTING" title="Reports" subtitle="Course, attendance, grades and risk reports."/><EmptyState title="No courses" text="Reports are built for the courses you teach."/></>;
  const info = REPORTS.find((r) => r[0] === kind);
  const course = courses.find((c) => c.id === oid);
  async function show() {
    setBusy(true);
    try { setPreview(await get(`/api/teacher/reports/${kind}?offering_id=${oid}&format=json`)); }
    catch (e) { onToast(`Could not build the report (${e.message})`); }
    setBusy(false);
  }
  async function save() {
    setBusy(true);
    try {
      const name = await download(`/api/teacher/reports/${kind}?offering_id=${oid}`, `${kind}.csv`);
      setRecent((p) => [{ name, title: `${info[1]} — ${course?.code || ''}`, at: new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) }, ...p].slice(0, 5));
      onToast(`Saved ${name}`);
    } catch (e) { onToast(`Could not download the report (${e.message})`); }
    setBusy(false);
  }
  return <><PageHeading eyebrow="REPORTING" title="Reports" subtitle="Course, attendance, grades and risk reports from live portal data."/>
    <div className="report-builder card"><div className="report-builder-icon"><FileSpreadsheet size={24}/></div>
      <div><h2>Build a report</h2><p>{info[2]}</p></div>
      <div className="form-grid">
        <label>Course<select value={oid} onChange={(e) => setOid(Number(e.target.value))}>{courses.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}</select></label>
        <label>Report type<select value={kind} onChange={(e) => setKind(e.target.value)}>{REPORTS.map((r) => <option key={r[0]} value={r[0]}>{r[1]}</option>)}</select></label>
      </div>
      <div style={row}><Button variant="outline" icon={Eye} disabled={busy} onClick={show}>Preview</Button><Button icon={Download} disabled={busy} onClick={save}>Download CSV</Button></div>
    </div>
    {preview && <Card title={`${info[1]} — ${preview.course.code}`} subtitle={`${preview.total} students · week ${preview.week} · first ${Math.min(15, preview.total)} rows shown`}>
      <div className="table-scroll"><table><thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>
        {preview.rows.slice(0, 15).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v === null || v === '' ? '—' : String(v)}</td>)}</tr>)}
      </tbody></table></div></Card>}
    {recent.length > 0 && <Card title="Downloaded in this session" subtitle="Files are saved to your browser's download folder">
      {recent.map((r) => <div className="report-row" key={r.name + r.at}><span className="file-type csv">CSV</span><span><b>{r.title}</b><small>{r.name} · {r.at}</small></span><Status>Done</Status></div>)}</Card>}
    <div className="notice-box"><ShieldCheck size={17}/><span>A report contains only the students of a course you teach. Files open in Excel; scores marked as unpublished are visible to you only.</span></div></>;
}

// ================================================================= D: очередь куратора и журнал
const KINDS = [['meeting', 'Meeting'], ['message', 'Message'], ['referral', 'Referral'], ['other', 'Other']];

export function LiveAdvisingPage({ onToast }) {
  const [data, setData] = useState(null);
  const [log, setLog] = useState([]);
  const [query, setQuery] = useState('');
  const [risk, setRisk] = useState('All');
  const [open, setOpen] = useState(null);                       // student_id выбранного студента
  const [form, setForm] = useState({ kind: 'meeting', summary: '', recheck_on: '' });
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState({});
  async function load() {
    try {
      const [a, j] = await Promise.all([get('/api/teacher/advisees'), get('/api/teacher/interventions')]);
      setData(a); setLog(j.items || []);
    } catch (e) { onToast(`Could not load advising data (${e.message})`); setData({ items: [], stats: null }); }
  }
  useEffect(() => { load(); }, []);
  if (!data) return <><PageHeading eyebrow="ADVISOR WORKSPACE" title="Advising" subtitle="Your advisees, ordered by who needs attention first."/><Card><p>Loading…</p></Card></>;
  const st = data.stats || { total: 0, needs_attention: 0, high: 0, contacted: 0 };
  const items = (data.items || []).filter((s) => (risk === 'All' || cap(s.risk_level) === risk)
    && `${s.first_name} ${s.last_name} ${s.login_id} ${s.group_code || ''}`.toLowerCase().includes(query.toLowerCase()));
  const selected = (data.items || []).find((s) => s.student_id === open);
  const history = log.filter((x) => x.student_id === open);
  async function add() {
    if (!form.summary.trim()) { onToast('Write what was done or agreed'); return; }
    setBusy(true);
    try {
      await send('/api/teacher/interventions', 'POST', { student_id: open, scope: 'advising', kind: form.kind, summary: form.summary.trim(), recheck_on: form.recheck_on || null });
      setForm({ kind: 'meeting', summary: '', recheck_on: '' }); onToast('Saved to the intervention log'); await load();
    } catch (e) { onToast(`Not saved (${e.message})`); }
    setBusy(false);
  }
  async function close(id) {
    const text = (outcome[id] || '').trim();
    if (!text) { onToast('Write the outcome first'); return; }
    setBusy(true);
    try { await send(`/api/teacher/interventions/${id}`, 'PUT', { outcome: text }); onToast('Outcome recorded'); await load(); }
    catch (e) { onToast(`Not saved (${e.message})`); }
    setBusy(false);
  }
  const followUp = (s) => (s.recheck_due ? 'Re-check due' : s.needs_attention ? 'Needs attention' : 'OK');
  return <><PageHeading eyebrow="ADVISOR WORKSPACE" title="Advising" subtitle={`Your advisees, ordered by who needs attention first · week ${data.week ?? '—'}`}/>
    <div className="stats-grid four">
      <StatCard label="My advisees" value={st.total} foot="active assignments" icon={Users}/>
      <StatCard label="Need attention" value={st.needs_attention} foot={`high risk, no contact for ${data.followup_days ?? 14}+ days, or re-check due`} icon={AlertCircle} color="pink"/>
      <StatCard label="High overall risk" value={st.high} foot="across all their courses" icon={ClipboardCheck} color="orange"/>
      <StatCard label="Contacted" value={st.contacted} foot="have at least one log entry" icon={CalendarClock} color="green"/>
    </div>
    {st.total === 0 ? <EmptyState title="No advisees" text="You are not assigned as an advisor to any student this semester."/> : <>
      <Card title="Advising queue" subtitle="Open a student to see the log and add an entry">
        <div className="student-filterbar"><label className="searchbox table-search"><Search size={15}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by name, ID or group"/></label>
          <select className="select-control" value={risk} onChange={(e) => setRisk(e.target.value)}><option>All</option><option>High</option><option>Medium</option><option>Low</option></select></div>
        <div className="table-scroll"><table><thead><tr><th>Student</th><th>Overall risk</th><th>Change</th><th>Courses at risk</th><th>Last contact</th><th>Follow-up</th><th/></tr></thead><tbody>
          {items.length === 0 && <tr><td colSpan={7}><small>No students match the filter</small></td></tr>}
          {items.map((s) => { const name = `${s.first_name} ${s.last_name}`; const ch = s.change === null || s.change === undefined ? null : Math.round(Number(s.change) * 100); return <tr key={s.student_id}>
            <td><div className="student-table-person"><Avatar name={name}/><span><b>{name}</b><small>{s.login_id}{s.group_code ? ` · ${s.group_code}` : ''}</small></span></div></td>
            <td>{s.risk_level ? <><Status>{cap(s.risk_level)}</Status> <small>{pct(s.risk_probability)}</small></> : <small>No forecast yet</small>}</td>
            <td>{ch === null ? '—' : `${ch > 0 ? '+' : ch < 0 ? '−' : ''}${Math.abs(ch)}%`}</td>
            <td>{s.courses_at_risk}</td>
            <td>{s.last_contact ? <>{day(s.last_contact)}<br/><small>{s.days_since_contact} days ago</small></> : <small>No contact yet</small>}</td>
            <td><Status>{followUp(s)}</Status></td>
            <td><button className="icon-btn small" aria-label={`Open ${name}`} onClick={() => setOpen(open === s.student_id ? null : s.student_id)}>{open === s.student_id ? <ChevronDown size={17}/> : <ChevronRight size={17}/>}</button></td></tr>; })}
        </tbody></table></div></Card>
      {selected && <Card title={`${selected.first_name} ${selected.last_name} — intervention log`} subtitle={`${selected.login_id} · ${history.length} entries`} action={<button className="icon-btn small" aria-label="Close" onClick={() => setOpen(null)}><X size={16}/></button>}>
        <div style={{ ...row, alignItems: 'flex-end', marginBottom: 14 }}>
          <label className="field-label">Type<br/><select className="select-control" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{KINDS.map((k) => <option key={k[0]} value={k[0]}>{k[1]}</option>)}</select></label>
          <label className="field-label" style={{ flex: 1, minWidth: 240 }}>What was done or agreed<br/><input className="grade-cell-input" style={{ width: '100%' }} value={form.summary} onChange={(e) => setForm({ ...form, summary: e.target.value })} placeholder="e.g. Talked about missed quizzes, agreed on a weekly plan"/></label>
          <label className="field-label">Re-check on<br/><input className="grade-cell-input" type="date" style={{ width: 160 }} value={form.recheck_on} onChange={(e) => setForm({ ...form, recheck_on: e.target.value })}/></label>
          <Button icon={Plus} disabled={busy} onClick={add}>Add entry</Button>
        </div>
        {history.length === 0 ? <small>No entries for this student yet.</small> : <div className="intervention-list">
          {history.map((x) => <div className="intervention-row" key={x.id} style={{ alignItems: 'flex-start' }}><span className="intervention-icon"><MessageCircle size={16}/></span>
            <span style={{ flex: 1 }}><b>{cap(x.kind)} · {x.summary}</b><small>{day(x.created_at)} · {x.author}{x.course_code ? ` · ${x.course_code}` : ' · advising'}{x.recheck_on ? ` · re-check ${day(x.recheck_on)}` : ''}</small>
              {x.outcome ? <small>Outcome: {x.outcome}</small> : x.mine && <span style={{ ...row, marginTop: 6 }}><input className="grade-cell-input" style={{ width: 280 }} placeholder="Outcome" value={outcome[x.id] || ''} onChange={(e) => setOutcome({ ...outcome, [x.id]: e.target.value })}/><Button variant="outline" size="small" disabled={busy} onClick={() => close(x.id)}>Record outcome</Button></span>}</span>
            <Status>{x.outcome ? 'Outcome recorded' : 'Open'}</Status></div>)}
        </div>}</Card>}
      <Card title="Recent interventions" subtitle="Latest entries you can see">
        {log.length === 0 ? <small>The log is empty.</small> : <div className="intervention-list">
          {log.slice(0, 8).map((x) => <div className="intervention-row" key={x.id}><span className="intervention-icon"><MessageCircle size={16}/></span><span><b>{cap(x.kind)} · {x.student}</b><small>{day(x.created_at)} · {x.author} · {x.summary}</small></span><Status>{x.outcome ? 'Outcome recorded' : 'Open'}</Status></div>)}
        </div>}</Card></>}
    <div className="notice-box"><ShieldCheck size={17}/><span>Advising is the only place where an advisor can see a student's cross-course overall risk. Teachers see risk only for their own courses.</span></div></>;
}

// ================================================================= B: объявления
export function LiveAnnouncementsPage({ role, courses = [], courseId, onToast }) {
  const [items, setItems] = useState(null);
  const [filter, setFilter] = useState('All');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const canPost = role === 'teacher' || role === 'admin';
  const [form, setForm] = useState({ offering_id: courseId || courses[0]?.id || '', title: '', body: '' });
  async function load() {
    try { const r = await get('/api/announcements'); setItems(r.items || []); }
    catch (e) { onToast(`Could not load announcements (${e.message})`); setItems([]); }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => { if (!form.offering_id && (courseId || courses[0])) setForm((f) => ({ ...f, offering_id: courseId || courses[0].id })); }, [courses, courseId]);
  async function publish() {
    if (!form.title.trim() || !form.body.trim()) { onToast('Fill in the title and the text'); return; }
    setBusy(true);
    try {
      await send('/api/announcements', 'POST', { offering_id: form.offering_id ? Number(form.offering_id) : null, title: form.title.trim(), body: form.body.trim() });
      setForm({ ...form, title: '', body: '' }); setShow(false); onToast('Announcement published'); await load();
    } catch (e) { onToast({ forbidden: 'You can post only to a course you teach', bad_request: 'Please check the title and the text' }[e.message] || `Not published (${e.message})`); }
    setBusy(false);
  }
  async function remove(id) {
    setBusy(true);
    try { await send(`/api/announcements/${id}`, 'DELETE'); onToast('Announcement deleted'); await load(); }
    catch (e) { onToast(`Not deleted (${e.message})`); }
    setBusy(false);
  }
  const list = (items || []).filter((a) => (courseId ? a.offering_id === courseId : true)
    && (filter === 'All' || (filter === 'Courses' && a.offering_id) || (filter === 'University' && !a.offering_id)));
  return <><PageHeading eyebrow="CAMPUS UPDATES" title="Announcements" subtitle="News and updates from your courses and university."
      actions={canPost && <Button icon={show ? X : Plus} variant={show ? 'outline' : 'primary'} onClick={() => setShow(!show)}>{show ? 'Cancel' : 'New announcement'}</Button>}/>
    {show && canPost && <Card title="New announcement" subtitle="Students enrolled in the course will see it right away">
      <div className="form-grid">
        <label>Course<select value={form.offering_id} onChange={(e) => setForm({ ...form, offering_id: e.target.value })}>
          {courses.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}
          {role === 'admin' && <option value="">University-wide</option>}</select></label>
        <label>Title<input value={form.title} maxLength={200} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Quiz 2 moved to Friday"/></label>
      </div>
      <label className="field-label">Text<textarea rows="4" value={form.body} maxLength={5000} onChange={(e) => setForm({ ...form, body: e.target.value })} placeholder="What students need to know"/></label>
      <div style={{ ...row, marginTop: 12 }}><Button icon={Mail} disabled={busy} onClick={publish}>Publish</Button></div></Card>}
    {!courseId && <div className="tabs"><button className={filter === 'All' ? 'active' : ''} onClick={() => setFilter('All')}>All</button><button className={filter === 'Courses' ? 'active' : ''} onClick={() => setFilter('Courses')}>My courses</button><button className={filter === 'University' ? 'active' : ''} onClick={() => setFilter('University')}>University</button></div>}
    {items === null ? <Card><p>Loading…</p></Card> : list.length === 0 ? <EmptyState title="No announcements" text="Nothing has been posted here yet."/> :
      <div className="announcement-list">{list.map((a, i) => <Card key={a.id} className="announcement-card">
        <div className="announcement-head"><span className={`announcement-icon ${['purple', 'orange', 'blue'][i % 3]}`}><Mail size={18}/></span>
          <div><b>{a.title}</b><small>{a.course_code ? `${a.course_code} · ${a.course_name}` : 'University announcement'} · {a.author}</small></div>
          <span className="announcement-date">{day(a.published_at)}</span></div>
        <p style={{ whiteSpace: 'pre-wrap' }}>{a.body}</p>
        {a.can_delete && <button className="text-button" disabled={busy} onClick={() => remove(a.id)}>Delete <X size={14}/></button>}</Card>)}</div>}</>;
}

// ================================================================= G: импорт оценок из CSV
const ROW_ERRORS = {
  missing_student_id: 'No student ID in this row',
  unknown_student: 'There is no student with this ID',
  not_enrolled: 'This student is not enrolled in the course',
  duplicate_in_file: 'This student appears twice in the file',
  missing_score: 'The score is empty',
  bad_score: 'The score is not a number',
  score_out_of_range: 'The score is below 0 or above the maximum',
};
const FILE_ERRORS = {
  empty_file: 'The file is empty', file_too_large: 'The file is larger than 1 MB', bad_encoding: 'The file is not a text CSV file',
  bad_header: 'The first line must contain the columns student_id and score', too_many_rows: 'The file has more than 2000 rows',
  has_errors: 'The file has rows with errors, nothing was saved', reason_required: 'Give a reason: the file changes existing grades',
  forbidden: 'You do not teach this course',
};
const ACTION = { new: 'New', update: 'Update', unchanged: 'Unchanged', error: 'Error' };

export function ImportGradesPanel({ assessment, onDone, onToast }) {
  const [file, setFile] = useState(null);
  const [res, setRes] = useState(null);
  const [reason, setReason] = useState('');
  const [skip, setSkip] = useState(false);
  const [busy, setBusy] = useState(false);
  const [nonce, setNonce] = useState(0);                       // новый номер очищает поле выбора файла
  useEffect(() => { setFile(null); setRes(null); setReason(''); setSkip(false); setNonce((n) => n + 1); }, [assessment?.id]);
  if (!assessment) return null;
  const url = `/api/teacher/assessments/${assessment.id}/grades-import`;
  async function run(dry) {
    if (!file) { onToast('Choose a CSV file first'); return; }
    setBusy(true);
    const r = await upload(url, { file, dry_run: dry ? '1' : '0', reason: reason.trim(), skip_invalid: skip ? '1' : '0' });
    setBusy(false);
    if (!r.data) { onToast('The server did not answer'); return; }
    if (r.data.rows) setRes(r.data);
    if (!r.ok) { onToast(FILE_ERRORS[r.data.error] || `Not imported (${r.data.error})`); return; }
    if (!dry) { onToast(`Imported ${r.data.written} grades as drafts`); setFile(null); setRes(null); setReason(''); setNonce((n) => n + 1); onDone && onDone(); }
  }
  const s = res?.summary;
  const toWrite = s ? s.new + s.update : 0;
  const blocked = !s || toWrite === 0 || (s.errors > 0 && !skip) || (s.update > 0 && !reason.trim());
  return <Card title="Import grades from CSV" subtitle={`${assessment.title} · max ${Number(assessment.max_score)} · saved as drafts, publish them afterwards`}>
    <div style={row}>
      <Button variant="outline" size="small" icon={Download} onClick={async () => { try { await download(`/api/teacher/assessments/${assessment.id}/grades-template`, 'grades.csv'); } catch (e) { onToast(`Could not download the template (${e.message})`); } }}>Download template</Button>
      <input type="file" accept=".csv,text/csv" key={nonce} onChange={(e) => { setFile(e.target.files[0] || null); setRes(null); }} aria-label="CSV file with grades"/>
      <Button size="small" icon={Eye} disabled={busy || !file} onClick={() => run(true)}>Check file</Button>
    </div>
    <p><small>Columns: <b>student_id</b> (portal ID), <b>score</b>, optional <b>comment</b>. Nothing is saved until you press Import.</small></p>
    {s && <>
      <div style={{ ...row, margin: '10px 0' }}><span><b>{s.total}</b> rows</span><Status>{`${s.new} new`}</Status><Status>{`${s.update} update`}</Status><span className="status neutral"><i/>{s.unchanged} unchanged</span>{s.errors > 0 && <Status>{`${s.errors} errors`}</Status>}</div>
      <div className="table-scroll" style={{ maxHeight: 320, overflowY: 'auto' }}><table><thead><tr><th>Line</th><th>Student ID</th><th>Student</th><th>Score</th><th>Was</th><th>Result</th></tr></thead><tbody>
        {res.rows.map((r) => <tr key={r.line}><td>{r.line}</td><td>{r.student_id || '—'}</td><td>{r.name || '—'}</td><td>{r.score === null ? '—' : r.score}</td><td>{r.old_score === null ? '—' : r.old_score}</td>
          <td>{r.action === 'error' ? <><Status>Error</Status> <small>{ROW_ERRORS[r.error] || r.error}</small></> : <Status>{ACTION[r.action]}</Status>}</td></tr>)}
      </tbody></table></div>
      {s.update > 0 && <label className="field-label" style={{ display: 'block', marginTop: 10 }}>Reason for changing existing grades (stored in the audit log)<br/><input className="grade-cell-input" style={{ width: 360 }} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Regrade after appeal"/></label>}
      {s.errors > 0 && <label style={{ ...row, marginTop: 10 }}><input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)}/> Skip the {s.errors} rows with errors and import the rest</label>}
      <div style={{ ...row, marginTop: 12 }}><Button icon={Upload} disabled={busy || blocked} onClick={() => run(false)}>{`Import ${toWrite} grades`}</Button>
        {s.errors > 0 && !skip && <small>Fix the file and check it again, or choose to skip the rows with errors.</small>}
        {toWrite === 0 && s.errors === 0 && <small>Nothing to import: all scores are already in the gradebook.</small>}</div></>}
  </Card>;
}
