/* model.js — connects the trained model to the prototype.
 *
 * Loads two files produced by notebooks/03_modelling.ipynb:
 *   predictions.json — real risk scores and top-3 factors for a held-out cohort
 *   whatif.json      — the model's response surface, precomputed over a grid
 *
 * The browser cannot run scikit-learn, so the What-if simulator reads real
 * model outputs from that grid instead of recomputing them. Everything this
 * file writes to the page comes from the model; nothing here is invented.
 *
 * Loaded after app.js, so its listeners run second and win.
 */
(function () {
  const $ = id => document.getElementById(id);
  const S = {};                       // predictions.json
  let WI = null;                      // whatif.json
  let demo = null;                    // the student shown on the Performance page

  const esc = v => String(v).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));

  const band = r => r < 0.30 ? 'low' : r < 0.55 ? 'medium' : 'high';
  const arcFor = r => r < 0.30 ? 'M25 108 A85 85 0 0 1 129 27'
    : r < 0.55 ? 'M25 108 A85 85 0 0 1 155 33'
      : 'M25 108 A85 85 0 0 1 192 80';

  // ---------- load ----------
  let LIVE = false;          // true when server.py is answering

  Promise.all([
    fetch('predictions.json').then(r => r.json()),
    fetch('whatif.json').then(r => r.json()).catch(() => null),
    fetch('api/model').then(r => r.ok ? r.json() : null).catch(() => null),
  ]).then(([preds, whatif, api]) => {
    Object.assign(S, preds);
    WI = whatif;
    LIVE = !!api;
    if (LIVE && !WI) {
      // No grid file, but the backend can score anything: synthesise the axes.
      WI = { axes: { score: [0, 100], clicks: [0, 40], share: [0, 1] },
             threshold: api.threshold, grid: null,
             demo_student: { id: S.students[0].id, base_risk: S.students[0].risk,
                             start: { score: 60, clicks: 20, share: 1 } } };
    }
    // Show a student near the decision boundary — the interesting case for a
    // curator, and the one the what-if grid was built around.
    demo = S.students.find(s => s.id === WI.demo_student.id) ||
      S.students.reduce((a, b) =>
        Math.abs(b.risk - S.threshold) < Math.abs(a.risk - S.threshold) ? b : a);
    paintRisk();
    paintFactors();
    paintBadge();
    wireSimulator();
  }).catch(err => {
    console.warn('model data not loaded:', err);
    const note = document.querySelector('.responsible');
    if (note) note.innerHTML =
      '<b>ⓘ Model data not loaded.</b> Open the page through a local server ' +
      '(<code>python -m http.server 8000</code>), not by double-clicking the file — ' +
      'the browser blocks <code>fetch</code> on <code>file://</code>. ' +
      'The numbers below are placeholders until then.';
  });

  // ---------- current risk indicator ----------
  function paintRisk() {
    const pct = Math.round(demo.risk * 100);
    $('riskPercent').textContent = pct + '%';
    $('riskStatus').textContent = band(demo.risk).toUpperCase() + ' RISK';
    $('riskStatus').className = 'risk-pill ' + band(demo.risk);
    $('gaugeArc').setAttribute('d', arcFor(demo.risk));
    $('gaugeArc').setAttribute('stroke',
      demo.risk < 0.30 ? '#22ad78' : demo.risk < 0.55 ? '#e5a13a' : '#d9525a');

    const helper = document.querySelector('.perf-card .helper');
    if (helper) helper.textContent =
      `Model output for student ${demo.id} (${demo.course}), week ${S.prediction_week}. ` +
      `Flagged above ${Math.round(S.threshold * 100)}%.`;
  }

  // ---------- "Why these results?" — real top factors ----------
  function paintFactors() {
    const panel = document.querySelector('.panel.factors');
    if (!panel) return;
    panel.querySelectorAll('.factor').forEach(n => n.remove());

    const max = Math.max(...demo.factors.map(f => Math.abs(f.weight)), 0.01);
    const pts = w => (w * 100 >= 1 ? (w * 100).toFixed(0) : (w * 100).toFixed(1));
    const html = demo.factors.map(f => {
      const below = f.value < f.average;
      const width = Math.round(Math.abs(f.weight) / max * 100);
      return `<div class="factor">
        <div><b>− ${esc(f.label)}: ${f.value}</b>
             <em class="impact up">+${pts(f.weight)} pts of risk</em></div>
        <div class="factor-track"><i class="red-bar" style="width:${width}%"></i></div>
        <p>${below ? 'Below' : 'Above'} the cohort average of ${f.average}.
           Removing this one value from the model drops the risk score by
           ${pts(f.weight)} points.</p>
      </div>`;
    }).join('');

    panel.insertAdjacentHTML('beforeend', html ||
      `<div class="factor"><div><b>+ No factors raise this student's risk</b>
       <em class="impact down">On track</em></div>
       <p>Every measured value is at or better than the cohort average.</p></div>`);

    const p = panel.querySelector('.panel-head p');
    if (p) p.textContent = `Top ${demo.factors.length} factors for student ${demo.id}, from the model`;
  }

  // ---------- provenance line ----------
  function paintBadge() {
    const note = document.querySelector('.responsible');
    if (note) note.innerHTML =
      `<b>ⓘ Real model output.</b> Risk scores and factors on this page come from ` +
      `<b>${esc(S.model)}</b>, trained on OULAD and validated by holding out whole module ` +
      `presentations: recall ${S.recall_mean.toFixed(3)} ± ${S.recall_sd.toFixed(3)}, ` +
      `decision threshold ${S.threshold}. Predictions are made at week ${S.prediction_week} and ` +
      `use no demographic data. Student names are placeholders; ids and scores are real. ` +
      (LIVE ? `Served live by <code>server.py</code>: every slider move is a real call to the model.`
            : `Served from precomputed files; run <code>python server.py</code> for live scoring.`);
  }

  // ---------- What-if simulator, driven by the model's own grid ----------
  const nearest = (arr, v) => arr.reduce((a, b) => Math.abs(b - v) < Math.abs(a - v) ? b : a);

  function lookup(score, clicks, share) {
    const k = `${nearest(WI.axes.score, score)}_${nearest(WI.axes.clicks, clicks)}` +
      `_${nearest(WI.axes.share, share).toFixed(1)}`;
    return WI.grid[k];
  }

  function wireSimulator() {
    const sc = $('scoreSlider'), hr = $('hoursSlider'), ot = $('ontimeSlider');
    if (!sc) return;

    // Re-label the sliders to the actual model features they drive.
    const ax = WI.axes, st = WI.demo_student.start;
    sc.min = ax.score[0]; sc.max = ax.score[ax.score.length - 1]; sc.step = 10; sc.value = st.score;
    hr.min = ax.clicks[0]; hr.max = ax.clicks[ax.clicks.length - 1]; hr.step = 5; hr.value = st.clicks;
    ot.min = 0; ot.max = 100; ot.step = 50; ot.value = st.share * 100;

    const labels = document.querySelectorAll('.simulator .slider');
    const text = [
      ['Average score so far', `<span id="scoreValue">${st.score}</span>`, '', '0', '100'],
      ['Average clicks per week', `<span id="hoursValue">${st.clicks}</span>`, '', '0', '40'],
      ['Assignments submitted', `<span id="ontimeValue">${st.share * 100}</span>`, '%', '0%', '100%'],
    ];
    labels.forEach((el, i) => {
      const [name, span, unit, lo, hi] = text[i];
      el.querySelector('label').innerHTML = `${name} <b>${span}${unit}</b>`;
      const ends = el.querySelectorAll('div:last-child small');
      if (ends.length === 2) { ends[0].textContent = lo; ends[1].textContent = hi; }
    });

    const head = document.querySelector('.sim-head p');
    if (head) head.textContent =
      'Move a value and the model re-scores this student. Real predictions, precomputed.';

    // With the backend up the sliders are continuous and every move is a real
    // call to the model. Without it they snap to the precomputed grid.
    if (LIVE) { sc.step = 1; hr.step = 1; ot.step = 1; }

    let pending = null;
    const askServer = (s, c, o) => {
      clearTimeout(pending);
      pending = setTimeout(() => {
        fetch('api/predict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            student_id: WI.demo_student.id,
            overrides: { mean_score: s, avg_weekly_clicks: c, submitted_share: o / 100 },
          }),
        }).then(r => r.json()).then(d => {
          show(d.risk);
          if (d.factors) { demo = Object.assign({}, demo, { factors: d.factors }); paintFactors(); }
        }).catch(() => { });
      }, 90);
    };

    const run = () => {
      const s = +sc.value, c = +hr.value, o = +ot.value;
      $('scoreValue').textContent = s;
      $('hoursValue').textContent = c;
      $('ontimeValue').textContent = o;
      if (LIVE) return askServer(s, c, o);

      const risk = lookup(s, c, o / 100);
      if (risk === undefined) return;
      show(risk);
    };

    const show = risk => {
      const pct = Math.round(risk * 100);
      const basePct = Math.round(WI.demo_student.base_risk * 100);
      $('simRisk').textContent = pct + '%';
      $('riskChange').textContent = pct === basePct ? 'same as the current estimate'
        : pct < basePct ? `↓ ${basePct - pct} points below current`
          : `↑ ${pct - basePct} points above current`;

      $('simGrade').textContent = risk >= WI.threshold ? 'AT RISK' : 'NOT FLAGGED';
      $('simPoints').textContent = `threshold ${Math.round(WI.threshold * 100)}%`;
      $('simInsight').textContent = risk >= WI.threshold
        ? 'The model still flags this student in this scenario. Submitted work moves the score most.'
        : 'In this scenario the model no longer flags the student.';

      $('riskPercent').textContent = pct + '%';
      $('riskStatus').textContent = band(risk).toUpperCase() + ' RISK';
      $('riskStatus').className = 'risk-pill ' + band(risk);
      $('gaugeArc').setAttribute('d', arcFor(risk));
      $('gaugeArc').setAttribute('stroke',
        risk < 0.30 ? '#22ad78' : risk < 0.55 ? '#e5a13a' : '#d9525a');
    };

    // app.js attached its own handlers first; ours run after and overwrite.
    [sc, hr, ot].forEach(el => el.addEventListener('input', run));
    $('resetSimulator').addEventListener('click', () => {
      sc.value = st.score; hr.value = st.clicks; ot.value = st.share * 100; run();
    });
    run();
  }
})();
