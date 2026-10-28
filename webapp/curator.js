/* curator.js — the curator side of SSPMS.
 *
 * US9  (prototype level) role switch: Student / Curator
 * US11 group dashboard: every student in the cohort, sorted by model risk
 * US18 capacity-aware intervention queue
 * US19 intervention log
 *
 * Reads the same predictions.json the Performance page uses, so every number
 * here is real model output. Interventions live in memory only — they are
 * what the database your team is building will store.
 */
(function () {
  const $ = id => document.getElementById(id);
  const esc = v => String(v).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));

  let DATA = null;
  let sortKey = 'risk', sortDir = -1, filter = 'all', selected = null;
  let capacity = 8;
  const log = [];          // US19 — replace with a table when the DB is ready

  const band = r => r >= 0.70 ? 'high' : r >= 0.40 ? 'medium' : 'low';
  const bandLabel = { high: 'High', medium: 'Watch', low: 'On track' };

  // ---------- chrome: role switch + nav ----------
  function injectChrome() {
    const nav = document.querySelector('#sideNav');
    if (!nav) return;

    nav.insertAdjacentHTML('afterend', `
      <div class="nav-label more" id="curatorLabel">CURATOR SPACE</div>
      <nav id="curatorNav">
        <button class="nav" data-page="curator">▥ <span>Group dashboard</span><em>US11</em></button>
        <button class="nav" data-page="queue">◎ <span>Intervention queue</span><em>US18</em></button>
        <button class="nav" data-page="log">✎ <span>Intervention log</span><em>US19</em></button>
      </nav>`);

    const crumb = document.querySelector('.topbar .crumb');
    if (crumb) crumb.insertAdjacentHTML('afterend', `
      <div class="role-switch" id="roleSwitch">
        <span>Viewing as</span>
        <div class="segmented">
          <button class="selected" data-role="student">Student</button>
          <button data-role="curator">Curator</button>
        </div>
      </div>`);

    document.querySelectorAll('[data-role]').forEach(b =>
      b.addEventListener('click', () => setRole(b.dataset.role)));
    setRole('student');
  }

  function setRole(role) {
    document.querySelectorAll('[data-role]').forEach(b =>
      b.classList.toggle('selected', b.dataset.role === role));
    const curator = role === 'curator';
    // Show one side of the app at a time: a curator has no "My courses".
    document.querySelectorAll('.sidebar .nav-label, .sidebar nav').forEach(el => {
      const mine = el.id === 'curatorLabel' || el.id === 'curatorNav';
      el.style.display = (curator === mine) ? '' : 'none';
    });
    const sup = document.querySelector('.support');
    if (sup) sup.style.display = curator ? 'none' : '';

    // Swap the signed-in identity, or the curator screens look like a student's.
    const who = curator
      ? ['DK', 'Dana Kenzhe', 'Curator · SDS-302', 'Curator']
      : ['AM', 'Aidana Mukan', 'Year 3 · SDS-302', 'Student'];
    const side = document.querySelector('.identity');
    if (side) {
      side.querySelector('.avatar').textContent = who[0];
      side.querySelector('b').textContent = who[1];
      side.querySelector('small').textContent = who[2];
    }
    const top = document.querySelector('.profile-top');
    if (top) {
      top.querySelector('.avatar').textContent = who[0];
      const lbl = top.querySelector('span:nth-child(2)');
      lbl.childNodes[0].nodeValue = who[1];
      lbl.querySelector('small').textContent = who[3];
    }

    const open = document.querySelector('.page.active');
    const onCurator = open && ['page-curator', 'page-queue', 'page-log'].includes(open.id);
    if (curator && !onCurator) go('curator');
    if (!curator && onCurator) go('home');
  }

  const go = page => document.querySelector(`[data-page="${page}"]`).click();

  // ---------- pages ----------
  function injectPages() {
    document.querySelector('.content').insertAdjacentHTML('beforeend', `
      <section class="page" id="page-curator">
        <div class="page-intro-row">
          <div class="page-intro">
            <small>GROUP OVERVIEW</small>
            <h1>My group <span class="ai-pill">✧ MODEL RANKED</span></h1>
            <p>Every student in the cohort, ordered by the risk the model assigns at week 6.</p>
          </div>
          <button class="btn secondary" id="exportGroup">↓ Export CSV</button>
        </div>
        <div class="course-summary" id="groupStats"></div>
        <div class="panel">
          <div class="calendar-toolbar">
            <div class="segmented" id="riskFilter">
              <button class="selected" data-filter="all">All</button>
              <button data-filter="high">High risk</button>
              <button data-filter="medium">Watch</button>
              <button data-filter="low">On track</button>
            </div>
            <input class="group-search" id="groupSearch" placeholder="Find a student...">
          </div>
          <div id="groupTable"></div>
        </div>
        <div class="responsible" id="groupNote"></div>
      </section>

      <section class="page" id="page-queue">
        <div class="page-intro">
          <small>PLAN YOUR WEEK</small>
          <h1>Intervention queue</h1>
          <p>A curator cannot talk to everyone. Say how many conversations you have time
             for and the queue takes the highest-risk students that fit.</p>
        </div>
        <div class="panel capacity-bar">
          <label>Conversations I can have this week
            <b><span id="capValue">8</span></b></label>
          <input type="range" id="capacity" min="1" max="20" value="8">
          <div><small>1</small><small>20</small></div>
          <p id="capacityNote"></p>
        </div>
        <div id="queueList" class="queue-list"></div>
      </section>

      <section class="page" id="page-log">
        <div class="page-intro">
          <small>WHAT WAS DONE</small>
          <h1>Intervention log</h1>
          <p>Every contact is recorded so the effect can be measured later —
             did the students we reached do better than the ones we missed?</p>
        </div>
        <div class="panel" id="logPanel"></div>
      </section>`);

    $('riskFilter').addEventListener('click', e => {
      const b = e.target.closest('[data-filter]'); if (!b) return;
      filter = b.dataset.filter;
      $('riskFilter').querySelectorAll('button').forEach(x => x.classList.toggle('selected', x === b));
      renderTable();
    });
    $('groupSearch').addEventListener('input', renderTable);
    $('exportGroup').addEventListener('click', exportCSV);
    $('capacity').addEventListener('input', e => {
      capacity = +e.target.value; $('capValue').textContent = capacity; renderQueue();
    });

    // app.js only knows the student pages, so it writes the raw key into the
    // breadcrumb for ours. Its listener runs first; this one corrects it.
    const NAMES = { curator: 'Group dashboard', queue: 'Intervention queue', log: 'Intervention log' };
    document.addEventListener('click', e => {
      const p = e.target.closest('[data-page]');
      if (p && NAMES[p.dataset.page]) $('crumb').textContent = NAMES[p.dataset.page];
    });

    document.addEventListener('click', e => {
      const row = e.target.closest('[data-student]');
      if (row && !e.target.closest('[data-contact]')) {
        selected = selected === +row.dataset.student ? null : +row.dataset.student;
        renderTable();
      }
      const c = e.target.closest('[data-contact]');
      if (c) { record(+c.dataset.contact, c.dataset.how || 'Message'); }
    });
  }

  // ---------- US11: the group table ----------
  function visible() {
    const q = ($('groupSearch').value || '').toLowerCase();
    return DATA.students
      .filter(s => filter === 'all' || band(s.risk) === filter)
      .filter(s => !q || s.name.toLowerCase().includes(q) || String(s.id).includes(q))
      .sort((a, b) => {
        const x = sortKey === 'name' ? a.name.localeCompare(b.name) : a[sortKey] - b[sortKey];
        return x * sortDir;
      });
  }

  function renderTable() {
    const rows = visible();
    const arrow = k => sortKey === k ? (sortDir < 0 ? ' ↓' : ' ↑') : '';

    $('groupTable').innerHTML =
      `<div class="grow head">
         <span data-sort="name">STUDENT${arrow('name')}</span>
         <span data-sort="risk">RISK${arrow('risk')}</span>
         <span>MAIN REASON</span>
         <span>STATUS</span>
         <span></span>
       </div>` +
      (rows.length ? rows.map(s => {
        const b = band(s.risk), pct = Math.round(s.risk * 100);
        const done = log.some(l => l.id === s.id);
        const open = selected === s.id;
        return `<div class="grow ${open ? 'open' : ''}" data-student="${s.id}">
          <span class="who"><b>${esc(s.name)}</b><small>${s.id} · ${esc(s.course)}</small></span>
          <span class="riskcell">
            <i class="riskbar ${b}"><u style="width:${pct}%"></u></i><b>${pct}%</b></span>
          <span class="reason">${s.factors.length ? esc(s.factors[0].label) : 'no risk factors'}</span>
          <span><b class="att-status ${b === 'high' ? 'absent' : b === 'medium' ? 'late' : 'present'}">${bandLabel[b]}</b></span>
          <span class="act">${done
            ? '<em class="logged">✓ contacted</em>'
            : `<button class="btn secondary" data-contact="${s.id}">Contact</button>`}</span>
        </div>` + (open ? detail(s) : '');
      }).join('') : '<div class="grow empty">No students match this filter.</div>');

    $('groupTable').querySelectorAll('[data-sort]').forEach(h =>
      h.addEventListener('click', () => {
        const k = h.dataset.sort;
        sortDir = sortKey === k ? -sortDir : (k === 'name' ? 1 : -1);
        sortKey = k; renderTable();
      }));

    renderStats();
  }

  function detail(s) {
    const max = Math.max(...s.factors.map(f => f.weight), 0.01);
    const pts = w => (w * 100 >= 1 ? (w * 100).toFixed(0) : (w * 100).toFixed(1));
    return `<div class="grow-detail">
      <div class="why">
        <b>Why the model flags ${esc(s.name.split(' ')[0])}</b>
        ${s.factors.length ? s.factors.map(f => `
          <div class="wrow">
            <span>${esc(f.label)}</span>
            <i><u style="width:${Math.round(f.weight / max * 100)}%"></u></i>
            <b>${f.value}</b>
            <small>avg ${f.average} · +${pts(f.weight)} pts</small>
          </div>`).join('')
        : '<p class="muted-p">Nothing in this student\'s record raises their risk.</p>'}
      </div>
      <div class="why-act">
        <small>SUGGESTED NEXT STEP</small>
        <p>${suggest(s)}</p>
        <button class="btn primary" data-contact="${s.id}" data-how="Meeting">Log a meeting</button>
        <button class="btn secondary" data-contact="${s.id}" data-how="Message">Log a message</button>
      </div>
    </div>`;
  }

  function suggest(s) {
    const f = (s.factors[0] || {}).label || '';
    if (f.includes('submitted') || f.includes('missed'))
      return 'Nothing has been handed in. Ask what is blocking the first submission before the next deadline.';
    if (f.includes('score'))
      return 'Work is coming in but scoring low. Offer to go through the last piece together.';
    if (f.includes('activity') || f.includes('clicks') || f.includes('active'))
      return 'The student has gone quiet in the course materials. A short check-in is usually enough.';
    return 'No single factor dominates. A general check-in on how the course is going.';
  }

  function renderStats() {
    const all = DATA.students, flagged = all.filter(s => s.flag);
    const mean = all.reduce((a, s) => a + s.risk, 0) / all.length;
    $('groupStats').innerHTML = [
      [all.length, 'Students in cohort'],
      [flagged.length, 'Flagged by the model'],
      [Math.round(mean * 100) + '%', 'Average risk'],
      [all.filter(s => log.some(l => l.id === s.id)).length + ' / ' + flagged.length, 'Flagged students contacted'],
    ].map(([b, s]) => `<div><b>${b}</b><small>${s}</small></div>`).join('');

    $('groupNote').innerHTML =
      `<b>ⓘ A guide, not a verdict.</b> Ranking comes from ${esc(DATA.model)}, ` +
      `recall ${DATA.recall_mean.toFixed(3)} ± ${DATA.recall_sd.toFixed(3)} across held-out cohorts. ` +
      `Roughly one flag in three is a false alarm, and on the weakest cohort the model misses ` +
      `four at-risk students in ten. Treat the order as a starting point for your own judgement.`;
  }

  // ---------- US18: capacity-aware queue ----------
  function renderQueue() {
    const pending = DATA.students
      .filter(s => s.flag && !log.some(l => l.id === s.id))
      .sort((a, b) => b.risk - a.risk);
    const take = pending.slice(0, capacity), rest = pending.length - take.length;

    $('capacityNote').textContent = rest > 0
      ? `${pending.length} students are flagged. With ${capacity} conversations you reach the top ${take.length}; ${rest} wait until next week.`
      : `${pending.length} students are flagged and all of them fit in ${capacity} conversations.`;

    $('queueList').innerHTML = take.length ? take.map((s, i) => `
      <article class="panel qrow" data-student="${s.id}">
        <b class="qnum">${i + 1}</b>
        <span class="who"><b>${esc(s.name)}</b><small>${esc(s.course)} · risk ${Math.round(s.risk * 100)}%</small></span>
        <span class="reason">${s.factors.length ? esc(s.factors[0].label) : '—'}</span>
        <button class="btn primary" data-contact="${s.id}" data-how="Meeting">Contact</button>
      </article>`).join('')
      : '<div class="panel placeholder"><h2>Queue is empty</h2><p>Every flagged student has been contacted.</p></div>';
  }

  // ---------- US19: intervention log ----------
  function record(id, how) {
    const s = DATA.students.find(x => x.id === id);
    if (!s || log.some(l => l.id === id)) return;
    log.push({
      id, name: s.name, how,
      risk_at_contact: s.risk,
      reason: s.factors.length ? s.factors[0].label : '—',
      when: new Date().toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }),
    });
    renderTable(); renderQueue(); renderLog();
    if (window.toast) window.toast(`${how} logged for ${s.name}`);
  }

  function renderLog() {
    if (!log.length) {
      $('logPanel').innerHTML =
        `<div class="placeholder"><h2>Nothing logged yet</h2>
         <p>Contact a student from the group dashboard or the queue and it appears here.</p></div>`;
      return;
    }
    const avg = log.reduce((a, l) => a + l.risk_at_contact, 0) / log.length;
    $('logPanel').innerHTML =
      `<div class="panel-head"><div><h2>${log.length} contacts recorded</h2>
        <p>Average risk at the moment of contact: ${Math.round(avg * 100)}%</p></div></div>` +
      `<div class="lrow head"><span>WHEN</span><span>STUDENT</span><span>TYPE</span>
        <span>RISK THEN</span><span>REASON GIVEN</span></div>` +
      log.slice().reverse().map(l => `<div class="lrow">
        <span>${esc(l.when)}</span>
        <span><b>${esc(l.name)}</b><br><small>${l.id}</small></span>
        <span>${esc(l.how)}</span>
        <span><b>${Math.round(l.risk_at_contact * 100)}%</b></span>
        <span>${esc(l.reason)}</span></div>`).join('') +
      `<div class="responsible" style="margin:13px">
        <b>ⓘ Not saved anywhere yet.</b> This log lives in the browser and is lost on refresh.
        It is the table the database should hold, and the input for measuring whether
        contacting a student actually changed their outcome.</div>`;
  }

  function exportCSV() {
    const rows = [['id', 'name', 'course', 'risk', 'flagged', 'reason_1', 'reason_2', 'reason_3'],
    ...visible().map(s => [s.id, s.name, s.course, s.risk, s.flag ? 1 : 0,
    ...[0, 1, 2].map(i => (s.factors[i] || {}).label || '')])];
    const blob = new Blob([rows.map(r => r.map(x => `"${String(x).replace(/"/g, '""')}"`).join(',')).join('\r\n')],
      { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'group-risk.csv';
    a.click();
    URL.revokeObjectURL(a.href);
    if (window.toast) window.toast('Group exported');
  }

  // ---------- boot ----------
  fetch('predictions.json').then(r => r.json()).then(d => {
    DATA = d;
    injectChrome();
    injectPages();
    renderTable(); renderQueue(); renderLog();
  }).catch(err => console.warn('curator: predictions.json not loaded', err));
})();
