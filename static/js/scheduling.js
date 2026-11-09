/* ExamFlow AI · scheduling pages: generator wizard, timetable, conflicts, fairness, comparison */
(function () {
  const {
    h, api, toast, modal, confirmAction, field, select, inputEl, dataTable, pill, statusPill,
    chartBar, barList, kpi, card, pageHead, loadingBlock, downloadFile, toCsv, route, navigate,
    fmtDate, fmtDateTime, fmtNum, schoolName, icon,
  } = App;

  const meta = () => App.state.meta;

  async function runOptions() {
    const data = await api('/api/runs?page_size=50');
    return data.items;
  }

  function runPicker(runs, currentId, onChange, label = 'Scheduling run') {
    const el = select(runs.map((r) => ({
      value: r.id,
      label: `${r.run_name} · ${r.algorithm_name.split(' ')[0]} · ${fmtDateTime(r.created_at)}`,
    })), { value: currentId, style: 'max-width:420px' });
    el.addEventListener('change', () => onChange(el.value));
    return h('div', { class: 'row', style: 'gap:8px' }, h('span', { class: 'small muted', text: label }), el);
  }

  function publishBar(run, reload) {
    const bar = h('div', { class: 'row wrap', style: 'gap:8px' });
    const validate = h('button', {
      class: 'btn secondary', text: 'Run validation',
      onclick: async () => {
        try {
          const res = await api(`/api/runs/${run.id}/validate`);
          modal({
            title: res.feasible ? 'Validation passed' : 'Validation failed', wide: true,
            body: h('div', null,
              h('div', { class: `alert ${res.feasible ? 'ok' : 'err'}`, text: res.feasible
                ? 'All mandatory constraints are satisfied. This timetable can be published.'
                : `${res.hard.length} mandatory constraint violation(s) detected. Publishing is blocked.` }),
              res.conflicts.length
                ? h('div', { class: 'mt12' }, dataTable({
                  columns: [
                    { key: 'conflict_type', label: 'Type' },
                    { key: 'severity', label: 'Severity', render: (r) => statusPill(r.severity) },
                    { key: 'description', label: 'Description' },
                    { key: 'suggested_resolution', label: 'Suggested fix' },
                  ], rows: res.conflicts,
                }))
                : h('p', { class: 'small muted mt12', text: 'No conflicts were found by the independent validator.' })),
          });
        } catch (err) { toast(err.message, 'err'); }
      },
    });
    const approve = h('button', {
      class: 'btn secondary', text: 'Approve',
      onclick: async () => {
        try { await api(`/api/runs/${run.id}/approve`, { method: 'POST' }); toast('Timetable approved.', 'ok'); reload(); }
        catch (err) { toast(err.message, 'err'); }
      },
    });
    const publish = h('button', {
      class: 'btn', text: run.status === 'Published' ? 'Published' : 'Publish timetable',
      disabled: run.status === 'Published',
      onclick: async () => {
        try { await api(`/api/runs/${run.id}/publish`, { method: 'POST' }); toast('Timetable published.', 'ok'); reload(); }
        catch (err) { toast(err.message, 'err'); }
      },
    });
    bar.append(validate, approve, publish);
    return bar;
  }

  /* ------------------------------------------------------------ wizard page */
  route({
    id: 'generator',
    title: 'AI Timetable Generator',
    render: async (view) => {
      const STEPS = ['Schools', 'Session', 'Date range', 'Examinations', 'Rooms', 'Invigilators',
        'Constraints', 'Optimisation', 'Algorithm', 'Generate'];
      const state = {
        step: 0,
        school_ids: [], session: '2026-27',
        date_from: '2026-11-16', date_to: '2026-11-20',
        examination_ids: [], room_ids: [], invigilator_ids: [], policy_ids: [],
        algorithm: 'csp',
        options: { auto_repair: true, workload_balance: 5, avoid_consecutive: 3,
          preferred_dates: 2, room_utilisation: 1 },
        run_name: 'Timetable generation',
      };
      const config = { cpsat: meta().cpsat };

      view.appendChild(pageHead('AI Timetable Generator', 'A guided, constraint-based scheduling run. Every step writes to real data; nothing is hardcoded.'));
      const stepBar = h('div', { class: 'wizard-steps' });
      const body = h('div', null);
      const nav = h('div', { class: 'row mt16' });
      view.appendChild(stepBar);
      view.appendChild(body);
      view.appendChild(nav);

      const m = meta();
      const schools = m.schools;
      const exams = m.examinations;
      const rooms = m.rooms;
      const invs = m.invigilators;

      if (!state.school_ids.length && schools.length) state.school_ids = schools.map((s) => s.id);
      if (!state.examination_ids.length) state.examination_ids = exams.map((e) => e.id);
      if (!state.room_ids.length) state.room_ids = rooms.map((r) => r.id);
      if (!state.invigilator_ids.length) state.invigilator_ids = invs.map((i) => i.id);
      if (!state.policy_ids.length) state.policy_ids = m.policies.filter((p) => p.is_enabled).map((p) => p.id);

      function renderSteps() {
        stepBar.innerHTML = '';
        STEPS.forEach((label, i) => {
          stepBar.appendChild(h('div', { class: `step-pill ${i === state.step ? 'active' : i < state.step ? 'done' : ''}` },
            h('span', { class: 'step-num', text: i < state.step ? '✓' : String(i + 1) }), h('span', { text: label })));
        });
      }

      function checkGrid(items, selected, onToggle, help) {
        const wrap = h('div', { class: 'check-grid', style: 'max-height:280px;overflow:auto;padding:2px' });
        for (const item of items) {
          const cb = h('input', { type: 'checkbox', checked: selected.includes(item.value) });
          cb.addEventListener('change', () => onToggle(item.value, cb.checked));
          wrap.appendChild(h('label', { class: 'check' }, cb, h('span', { text: item.label })));
        }
        return h('div', null, wrap, help ? h('div', { class: 'tiny muted mt8', text: help }) : null);
      }

      function renderStep() {
        body.innerHTML = '';
        renderSteps();
        const s = state.step;
        if (s === 0) {
          body.appendChild(card('Which schools are in this run?',
            checkGrid(schools.map((x) => ({ value: x.id, label: x.school_name })), state.school_ids,
              (v, on) => { state.school_ids = on ? [...state.school_ids, v] : state.school_ids.filter((x) => x !== v); }),
            'Selecting a school includes its examinations, rooms and faculty. Multi-school runs honour inter-school policies.'));
        } else if (s === 1) {
          body.appendChild(card('Academic session', field('Session', select(m.sessions, { value: state.session }))));
        } else if (s === 2) {
          const from = inputEl({ type: 'date', value: state.date_from });
          const to = inputEl({ type: 'date', value: state.date_to });
          from.addEventListener('change', () => { state.date_from = from.value; });
          to.addEventListener('change', () => { state.date_to = to.value; });
          const slots = m.slots.filter((x) => (!state.date_from || x.examination_date >= state.date_from) && (!state.date_to || x.examination_date <= state.date_to));
          body.appendChild(card('Examination window', h('div', null,
            h('div', { class: 'grid two' }, field('From', from), field('To', to)),
            h('div', { class: 'alert info mt12', text: `${slots.length} time slot(s) fall inside this window. Slots outside it are excluded from the CSP domain.` }))));
        } else if (s === 3) {
          const list = exams.filter((e) => state.school_ids.includes(e.school_id));
          body.appendChild(card(`Examinations (${list.length} available)`,
            checkGrid(list.map((e) => ({ value: e.id, label: `${e.name} · ${e.priority}` })), state.examination_ids,
              (v, on) => { state.examination_ids = on ? [...state.examination_ids, v] : state.examination_ids.filter((x) => x !== v); })));
        } else if (s === 4) {
          const list = rooms.filter((r) => state.school_ids.includes(r.school_id));
          body.appendChild(card(`Rooms (${list.length} available)`,
            checkGrid(list.map((r) => ({ value: r.id, label: `${r.name} · ${r.capacity} seats` })), state.room_ids,
              (v, on) => { state.room_ids = on ? [...state.room_ids, v] : state.room_ids.filter((x) => x !== v); })));
        } else if (s === 5) {
          const list = invs.filter((i) => state.school_ids.includes(i.school_id));
          body.appendChild(card(`Invigilators (${list.length} available)`,
            checkGrid(list.map((i) => ({ value: i.id, label: `${i.name} · ${i.code}` })), state.invigilator_ids,
              (v, on) => { state.invigilator_ids = on ? [...state.invigilator_ids, v] : state.invigilator_ids.filter((x) => x !== v); })));
        } else if (s === 6) {
          const hard = m.policies.filter((p) => p.is_mandatory);
          const soft = m.policies.filter((p) => !p.is_mandatory);
          body.appendChild(card('Constraints and policies', h('div', null,
            h('h3', { style: 'font-size:13px;margin-bottom:8px', text: 'Mandatory constraints' }),
            checkGrid(hard.map((p) => ({ value: p.id, label: p.policy_name })), state.policy_ids,
              (v, on) => { state.policy_ids = on ? [...state.policy_ids, v] : state.policy_ids.filter((x) => x !== v); },
              'Mandatory rules are never relaxed. Disabling one is recorded in the run configuration.'),
            h('h3', { style: 'font-size:13px;margin:14px 0 8px', text: 'Soft objectives' }),
            checkGrid(soft.map((p) => ({ value: p.id, label: `${p.policy_name} (weight ${p.penalty_weight})` })), state.policy_ids,
              (v, on) => { state.policy_ids = on ? [...state.policy_ids, v] : state.policy_ids.filter((x) => x !== v); })),
            h('label', { class: 'check mt12' },
              h('input', {
                type: 'checkbox', checked: state.options.auto_repair,
                onchange: (e) => { state.options.auto_repair = e.target.checked; },
              }), h('span', { text: 'Attempt automatic conflict repair after solving' }))));
        } else if (s === 7) {
          const rows = [
            ['workload_balance', 'Balanced invigilator workload'],
            ['avoid_consecutive', 'Avoid consecutive duties'],
            ['preferred_dates', 'Respect preferred examination dates'],
            ['room_utilisation', 'Efficient room utilisation'],
          ];
          const grid = h('div', { class: 'grid two' });
          for (const [key, label] of rows) {
            const input = inputEl({ type: 'number', min: 0, step: 1, value: state.options[key] });
            input.addEventListener('input', () => { state.options[key] = Number(input.value || 0); });
            grid.appendChild(field(`${label} · weight`, input));
          }
          body.appendChild(card('Optimisation priorities', h('div', null, grid,
            h('div', { class: 'alert info mt12', text: 'Higher weights increase the soft penalty recorded for each violation. Hard constraints always dominate.' }))));
        } else if (s === 8) {
          const opts = [
            ['csp', 'CSP with heuristic search', 'Backtracking + MRV, degree heuristic, LCV, forward checking. Produces explanations for every placement.'],
            ['first_fit', 'First-Fit baseline', 'Deterministic greedy placement used as the comparison baseline. No look-ahead.'],
          ];
          const list = h('div', { class: 'grid two' });
          for (const [key, title, desc] of opts) {
            const box = h('div', { class: `radio-card ${state.algorithm === key ? 'selected' : ''}`, onclick: () => { state.algorithm = key; renderStep(); } },
              h('b', { text: title }), h('small', { text: desc }));
            list.appendChild(box);
          }
          const cpState = (config && config.cpsat) || { available: false, note: 'CP-SAT solver not configured.' };
          body.appendChild(card('Algorithm', h('div', null, list,
            h('div', { class: 'alert warn mt12', text: `CP-SAT optimisation: ${cpState.available ? 'available' : 'not installed in this deployment'}. ${cpState.note}` }))));
        } else {
          body.appendChild(card('Ready to generate', h('div', null,
            field('Run name', (() => {
              const i = inputEl({ value: state.run_name });
              i.addEventListener('input', () => { state.run_name = i.value; });
              return i;
            })()),
            h('dl', { class: 'kv mt12' },
              h('dt', { text: 'Schools' }), h('dd', { text: `${state.school_ids.length} selected` }),
              h('dt', { text: 'Examinations' }), h('dd', { text: `${state.examination_ids.length} selected` }),
              h('dt', { text: 'Rooms' }), h('dd', { text: `${state.room_ids.length} selected` }),
              h('dt', { text: 'Invigilators' }), h('dd', { text: `${state.invigilator_ids.length} selected` }),
              h('dt', { text: 'Window' }), h('dd', { text: `${fmtDate(state.date_from)} – ${fmtDate(state.date_to)}` }),
              h('dt', { text: 'Algorithm' }), h('dd', { text: state.algorithm === 'csp' ? 'CSP heuristic search' : 'First-Fit baseline' }),
              h('dt', { text: 'Policies' }), h('dd', { text: `${state.policy_ids.length} enabled` })))));
        }

        nav.innerHTML = '';
        if (s > 0) nav.appendChild(h('button', { class: 'btn secondary', text: 'Back', onclick: () => { state.step -= 1; renderStep(); } }));
        nav.appendChild(h('span', { class: 'spacer' }));
        if (s < STEPS.length - 1) {
          nav.appendChild(h('button', { class: 'btn', text: 'Continue', onclick: () => { state.step += 1; renderStep(); } }));
        } else {
          const go = h('button', { class: 'btn', text: 'Generate timetable' });
          go.addEventListener('click', () => generate(go));
          nav.appendChild(go);
        }
      }

      async function generate(button) {
        button.disabled = true;
        button.innerHTML = '<span class="spinner"></span> Solving';
        const resultBox = h('div', { class: 'mt16' });
        body.appendChild(resultBox);
        resultBox.appendChild(loadingBlock('Running the solver and validating the result'));
        try {
          const body = {
            algorithm: state.algorithm, run_name: state.run_name, session: state.session,
            school_ids: state.school_ids, examination_ids: state.examination_ids,
            room_ids: state.room_ids, invigilator_ids: state.invigilator_ids,
            policy_ids: state.policy_ids, date_from: state.date_from, date_to: state.date_to,
            options: { ...state.options, weights: { workload_balance: state.options.workload_balance } },
          };
          const run = await api('/api/scheduling/run', { method: 'POST', body });
          resultBox.innerHTML = '';
          resultBox.appendChild(resultCard(run));
        } catch (err) {
          resultBox.innerHTML = '';
          resultBox.appendChild(h('div', { class: 'alert err', text: err.message }));
        } finally {
          button.disabled = false;
          button.textContent = 'Generate timetable';
        }
      }

      function resultCard(run) {
        const feasible = run.hard_constraint_violations === 0 && run.unscheduled_examinations === 0;
        return card('Scheduling result', h('div', null,
          h('div', { class: 'status-hero' },
            h('div', null, h('div', { class: 'tiny muted', text: 'Solver status' }), h('div', { class: 'big-status' }, statusPill(run.solver_status))),
            h('div', null, h('div', { class: 'tiny muted', text: 'Scheduled' }), h('div', { class: 'big-status', text: `${run.scheduled_examinations} / ${run.total_examinations}` })),
            h('div', null, h('div', { class: 'tiny muted', text: 'Unscheduled' }), h('div', { class: 'big-status', text: String(run.unscheduled_examinations) })),
            h('div', null, h('div', { class: 'tiny muted', text: 'Hard violations' }), h('div', { class: 'big-status', text: String(run.hard_constraint_violations) })),
            h('div', null, h('div', { class: 'tiny muted', text: 'Soft penalty' }), h('div', { class: 'big-status', text: fmtNum(run.soft_constraint_penalty, 2) })),
            h('div', null, h('div', { class: 'tiny muted', text: 'Solve time' }), h('div', { class: 'big-status', text: `${fmtNum(run.execution_time, 3)}s` }))),
          h('div', { class: `alert ${feasible ? 'ok' : 'warn'} mt12`, text: feasible
            ? 'Every mandatory constraint is satisfied and every examination is placed. Optimality is not proven, so this is reported as feasible, not optimal.'
            : 'This run is not publishable. Open Conflict Management to see which rules are blocking placements.' }),
          h('div', { class: 'row wrap mt12' },
            h('button', { class: 'btn secondary', onclick: () => navigate('timetable', { run: run.id }) }, 'Preview timetable'),
            h('button', { class: 'btn secondary', onclick: () => navigate('conflicts', { run: run.id }) }, 'Review conflicts'),
            h('button', { class: 'btn secondary', onclick: () => navigate('fairness', { run: run.id }) }, 'Fairness analysis'),
            h('button', { class: 'btn secondary', onclick: () => navigate('comparison') }, 'Compare algorithms')),
          h('div', { class: 'mt12' }, publishBar(run, () => App.renderRoute()))));
      }

      renderStep();
    },
  });

  /* ------------------------------------------------------------ timetable page */
  route({
    id: 'timetable',
    title: 'Generated Timetable',
    render: async (view, params) => {
      const host = h('div', null);
      view.appendChild(pageHead('Generated Timetable', 'One published or preview run, seen from seven angles. Every edit is revalidated.'));
      view.appendChild(host);
      let runs;
      try { runs = await runOptions(); } catch (err) {
        host.appendChild(h('div', { class: 'alert err', text: err.message }));
        return;
      }
      if (!runs.length) {
        host.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'No timetable has been generated yet' }),
          h('div', { class: 'tiny', text: 'Run the AI generator to create the first schedule.' }),
          h('div', { class: 'mt12' }, h('button', { class: 'btn', text: 'Open generator', onclick: () => navigate('generator') }))));
        return;
      }
      const state = {
        runId: params.run || runs[0].id,
        view: 'calendar', q: '', school: '', date: '', assignment: null,
      };
      const toolbar = h('div', { class: 'toolbar' });
      const tabs = h('div', { class: 'tabs' });
      const content = h('div', null);
      const side = h('div', null);
      host.appendChild(h('div', { class: 'card tight' }, toolbar));
      host.appendChild(h('div', { class: 'mt12' }, tabs));
      host.appendChild(h('div', { class: 'grid', style: 'grid-template-columns:minmax(0,1fr) 320px;gap:14px;align-items:start' }, content, side));

      const VIEWS = [['calendar', 'Calendar'], ['daily', 'Daily'], ['weekly', 'Weekly'], ['school', 'School-wise'],
        ['room', 'Room-wise'], ['group', 'Group-wise'], ['invigilator', 'Invigilator-wise']];

      let run = null;
      let rows = [];

      function buildToolbar() {
        toolbar.innerHTML = '';
        toolbar.appendChild(runPicker(runs, state.runId, (id) => { state.runId = id; load(); }));
        const search = inputEl({ placeholder: 'Search subject, room, invigilator…', value: state.q, style: 'max-width:240px' });
        search.addEventListener('input', () => { state.q = search.value; render(); });
        toolbar.appendChild(search);
        const schoolSel = select([{ value: '', label: 'All schools' }, ...meta().schools.map((s) => ({ value: s.id, label: s.school_code }))], { value: state.school, style: 'max-width:130px' });
        schoolSel.addEventListener('change', () => { state.school = schoolSel.value; render(); });
        toolbar.appendChild(schoolSel);
        const dateSel = select([{ value: '', label: 'All dates' }, ...Array.from(new Set(rows.map((r) => r.examination_date))).sort().map((d) => ({ value: d, label: fmtDate(d) }))], { value: state.date, style: 'max-width:170px' });
        dateSel.addEventListener('change', () => { state.date = dateSel.value; render(); });
        toolbar.appendChild(dateSel);
        toolbar.appendChild(h('span', { class: 'spacer' }));
        toolbar.appendChild(h('button', { class: 'btn secondary sm', onclick: exportCsv }, icon('download', 14), 'Export CSV'));
        toolbar.appendChild(h('button', { class: 'btn secondary sm', onclick: () => window.print() }, icon('print', 14), 'Print'));
        if (run) toolbar.appendChild(h('button', {
          class: 'btn secondary sm', text: 'Repair conflicts',
          onclick: async () => {
            try {
              const res = await api(`/api/runs/${state.runId}/repair`, { method: 'POST' });
              toast(`${res.actions.length} repair action(s); ${res.hard.length} conflict(s) remain.`, res.hard.length ? 'info' : 'ok');
              await load();
            } catch (err) { toast(err.message, 'err'); }
          },
        }));
        if (run) toolbar.appendChild(h('button', {
          class: 'btn sm', text: run.status === 'Published' ? 'Published' : 'Publish',
          disabled: run.status === 'Published',
          onclick: async () => {
            try { await api(`/api/runs/${state.runId}/publish`, { method: 'POST' }); toast('Published.', 'ok'); await load(); }
            catch (err) { toast(err.message, 'err'); }
          },
        }));
      }

      function buildTabs() {
        tabs.innerHTML = '';
        for (const [key, label] of VIEWS) {
          tabs.appendChild(h('button', {
            class: `tab ${state.view === key ? 'active' : ''}`, text: label,
            onclick: () => { state.view = key; render(); },
          }));
        }
      }

      function filtered() {
        const q = state.q.toLowerCase();
        return rows.filter((r) => {
          if (state.school && r.school_id !== state.school) return false;
          if (state.date && r.examination_date !== state.date) return false;
          if (!q) return true;
          return [r.subject_name, r.subject_code, r.room_number, r.invigilator_names, r.school_code, r.session]
            .join(' ').toLowerCase().includes(q);
        });
      }

      function chip(row) {
        return h('div', { class: `exam-chip pri-${row.priority || 'Medium'}`, style: 'cursor:pointer', onclick: () => selectAssignment(row) },
          h('b', { text: `${row.subject_code} · ${row.subject_name}` }),
          h('small', { text: `${row.school_code} · ${row.room_number || 'no room'}` }),
          h('small', { text: `${row.required_seating_capacity} students · ${row.invigilator_names || 'no invigilator'}` }));
      }

      function groupBy(list, keyFn) {
        const map = new Map();
        for (const row of list) {
          const key = keyFn(row);
          if (!map.has(key)) map.set(key, []);
          map.get(key).push(row);
        }
        return map;
      }

      function renderGroups(keyFn, labelFn, chipFn) {
        const map = groupBy(filtered(), keyFn);
        if (!map.size) return h('div', { class: 'empty', text: 'Nothing matches these filters.' });
        const wrap = h('div', null);
        for (const [key, list] of [...map.entries()].sort((a, b) => String(a[0]).localeCompare(String(b[0])))) {
          wrap.appendChild(h('div', { class: 'day-block' },
            h('div', { class: 'day-head' }, h('span', { text: labelFn(key, list) }),
              h('span', { class: 'muted', text: `${list.length} examination(s)` })),
            h('div', { class: 'slot-line', style: 'grid-template-columns:1fr' },
              h('div', { class: 'slot-items' }, ...list.sort((a, b) => String(a.start_time).localeCompare(String(b.start_time))).map(chipFn || chip)))));
        }
        return wrap;
      }

      function render() {
        buildToolbar();
        buildTabs();
        content.innerHTML = '';
        const list = filtered();
        if (!list.length) {
          content.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'No examinations in this view' }), h('div', { class: 'tiny', text: 'Try another view or clear the filters.' })));
        } else if (state.view === 'calendar' || state.view === 'daily') {
          content.appendChild(renderGroups((r) => r.examination_date, (key, items) => `${fmtDate(key, true)} · ${items.length} examination(s)`));
        } else if (state.view === 'weekly') {
          content.appendChild(renderGroups((r) => r.examination_date,
            (key) => `Week of ${fmtDate(key, true)}`));
        } else if (state.view === 'school') {
          content.appendChild(renderGroups((r) => r.school_id, (key) => schoolName(key)));
        } else if (state.view === 'room') {
          content.appendChild(renderGroups((r) => r.room_number || 'Unassigned', (key, items) => `Room ${key} · ${items[0]?.room_capacity || 0} seats`));
        } else if (state.view === 'group') {
          content.appendChild(renderGroups((r) => r.subject_code, (key, items) => `${key} · student groups`));
          content.innerHTML = '';
          const map = groupBy(list, (r) => (r.student_group_ids || []).join(',') || 'none');
          const wrap = h('div', null);
          for (const [key, items] of map.entries()) {
            const names = key === 'none' ? 'No group' : key.split(',').map((id) => (meta().groups.find((g) => g.id === id) || {}).name || id).join(', ');
            wrap.appendChild(h('div', { class: 'day-block' },
              h('div', { class: 'day-head' }, h('span', { text: names }), h('span', { class: 'muted', text: `${items.length} examination(s)` })),
              h('div', { class: 'slot-line', style: 'grid-template-columns:1fr' },
                h('div', { class: 'slot-items' }, ...items.map(chip)))));
          }
          content.appendChild(wrap);
        } else if (state.view === 'invigilator') {
          const map = new Map();
          for (const row of list) {
            const invs = row.invigilators || [];
            if (!invs.length) {
              if (!map.has('Unassigned')) map.set('Unassigned', []);
              map.get('Unassigned').push(row);
            }
            for (const inv of invs) {
              if (!map.has(inv.name)) map.set(inv.name, []);
              map.get(inv.name).push(row);
            }
          }
          const wrap = h('div', null);
          for (const [name, items] of [...map.entries()].sort()) {
            wrap.appendChild(h('div', { class: 'day-block' },
              h('div', { class: 'day-head' }, h('span', { text: name }), h('span', { class: 'muted', text: `${items.length} duty(ies)` })),
              h('div', { class: 'slot-line', style: 'grid-template-columns:1fr' },
                h('div', { class: 'slot-items' }, ...items.sort((a, b) => `${a.examination_date}${a.start_time}`.localeCompare(`${b.examination_date}${b.start_time}`)).map((row) => h('div', { class: 'exam-chip', onclick: () => selectAssignment(row) },
                  h('b', { text: `${row.subject_code} · ${row.subject_name}` }),
                  h('small', { text: `${fmtDate(row.examination_date, true)} ${row.start_time} · ${row.room_number}` })))))));
          }
          content.appendChild(wrap);
        }

        if (state.view !== 'calendar' && state.view !== 'daily' && list.length) {
          content.appendChild(h('div', { class: 'mt12' }, card('Detailed view', dataTable({
            columns: [
              { key: 'examination_date', label: 'Date', render: (r) => fmtDate(r.examination_date, true) },
              { key: 'start_time', label: 'Time', render: (r) => `${r.start_time}–${r.end_time}` },
              { key: 'subject_code', label: 'Code' },
              { key: 'subject_name', label: 'Examination' },
              { key: 'school_code', label: 'School' },
              { key: 'room_number', label: 'Room' },
              { key: 'invigilator_names', label: 'Invigilators' },
              { key: 'assignment_status', label: 'Status', render: (r) => statusPill(r.assignment_status) },
              { key: 'actions', label: '', render: (r) => h('button', { class: 'link-btn', text: 'Details', onclick: () => selectAssignment(r) }) },
            ], rows: list,
          }))));
        }
      }

      function selectAssignment(row) {
        state.assignment = row;
        renderSide();
      }

      function renderSide() {
        side.innerHTML = '';
        if (!run) return;
        const summary = card('Run summary', h('div', null,
          h('dl', { class: 'kv' },
            h('dt', { text: 'Run' }), h('dd', { text: run.run_name }),
            h('dt', { text: 'Algorithm' }), h('dd', { text: run.algorithm_name }),
            h('dt', { text: 'Status' }), h('dd', null, statusPill(run.solver_status)),
            h('dt', { text: 'Run state' }), h('dd', null, statusPill(run.status)),
            h('dt', { text: 'Scheduled' }), h('dd', { text: `${run.scheduled_examinations} / ${run.total_examinations}` }),
            h('dt', { text: 'Hard violations' }), h('dd', { text: run.hard_constraint_violations }),
            h('dt', { text: 'Soft penalty' }), h('dd', { text: fmtNum(run.soft_constraint_penalty, 2) }),
            h('dt', { text: 'Fairness' }), h('dd', { text: `${fmtNum(run.fairness.summary.fairness_score, 1)} / 100` }),
            h('dt', { text: 'Version' }), h('dd', { text: String(run.version) }))));
        side.appendChild(summary);
        side.appendChild(h('div', { class: 'mt12' }, card('Publish controls', publishBar(run, () => load()))));
        if (state.assignment) {
          const a = state.assignment;
          const exp = a.explanation;
          const body = h('div', null,
            h('dl', { class: 'kv' },
              h('dt', { text: 'Examination' }), h('dd', { text: `${a.subject_code} · ${a.subject_name}` }),
              h('dt', { text: 'Date' }), h('dd', { text: fmtDate(a.examination_date, true) }),
              h('dt', { text: 'Time' }), h('dd', { text: `${a.start_time}–${a.end_time}` }),
              h('dt', { text: 'Room' }), h('dd', { text: `${a.room_number || '—'} (${a.room_capacity || 0} seats)` }),
              h('dt', { text: 'Students' }), h('dd', { text: a.required_seating_capacity }),
              h('dt', { text: 'Invigilators' }), h('dd', { text: a.invigilator_names || 'None assigned' })),
            h('h3', { class: 'mt16', style: 'font-size:13px', text: 'Explainable AI decision' }),
            exp ? h('div', null,
              h('p', { class: 'small mt8', text: exp.decision_reason || 'No explanation stored.' }),
              h('div', { class: 'tiny muted mt8', text: `Alternatives considered: ${exp.alternatives_considered}` }),
              (exp.constraints_satisfied || []).length ? h('div', { class: 'mt8' },
                h('div', { class: 'tiny muted', text: 'Constraints satisfied' }),
                h('ul', { class: 'small', style: 'margin:4px 0 0 16px' }, ...(exp.constraints_satisfied || []).map((c) => h('li', { text: c })))) : null,
              (exp.rejected_alternatives || []).length ? h('div', { class: 'mt8' },
                h('div', { class: 'tiny muted', text: 'Rejected alternatives' }),
                h('ul', { class: 'small', style: 'margin:4px 0 0 16px' }, ...(exp.rejected_alternatives || []).map((c) => h('li', { text: typeof c === 'string' ? c : c.reason || JSON.stringify(c) })))) : null)
              : h('p', { class: 'small muted mt8', text: 'This assignment was produced by the First-Fit baseline, which does not record explanations.' }),
            h('div', { class: 'row wrap mt16' },
              h('button', { class: 'btn secondary sm', text: 'Reschedule', onclick: () => openReschedule(a) }),
              h('button', { class: 'btn ghost sm', text: 'Close', onclick: () => { state.assignment = null; renderSide(); } })));
          side.appendChild(h('div', { class: 'mt12' }, card('Assignment detail', body)));
        }
      }

      function openReschedule(a) {
        const slotSel = select(meta().slots.map((s) => ({
          value: s.id, label: `${fmtDate(s.examination_date)} · ${s.start_time}–${s.end_time} (${s.session})`,
        })), { value: a.time_slot_id });
        const roomSel = select(meta().rooms.filter((r) => r.school_id === a.school_id)
          .map((r) => ({ value: r.id, label: `${r.name} · ${r.capacity} seats` })), { value: a.room_id });
        const body = h('div', null,
          h('div', { class: 'alert info', style: 'margin-bottom:12px', text: 'After saving, the run is revalidated immediately. Publishing stays blocked while any mandatory constraint fails.' }),
          field('Time slot', slotSel), field('Room', roomSel));
        const save = h('button', { class: 'btn', text: 'Move examination' });
        const m = modal({ title: `Reschedule ${a.subject_code}`, body, footer: [h('button', { class: 'btn secondary', text: 'Cancel', onclick: () => m.close() }), save] });
        save.addEventListener('click', async () => {
          save.disabled = true;
          try {
            const res = await api(`/api/assignments/${a.id}/reschedule`, { method: 'PUT', body: { time_slot_id: slotSel.value, room_id: roomSel.value } });
            m.close();
            if (res.feasible) toast('Moved and revalidated: no violations.', 'ok');
            else toast(`Moved, but ${res.hard.length} mandatory constraint(s) now fail. Publishing is blocked.`, 'err');
            state.assignment = null;
            await load();
          } catch (err) {
            toast(err.message, 'err');
            save.disabled = false;
          }
        });
      }

      function exportCsv() {
        const columns = [
          { key: 'examination_date', label: 'Date' }, { key: 'start_time', label: 'Start' },
          { key: 'end_time', label: 'End' }, { key: 'subject_code', label: 'Code' },
          { key: 'subject_name', label: 'Examination' }, { key: 'school_code', label: 'School' },
          { key: 'room_number', label: 'Room' },
          { key: 'required_seating_capacity', label: 'Students' },
          { key: 'invigilator_names', label: 'Invigilators' },
          { key: 'assignment_status', label: 'Status' },
        ];
        downloadFile(`timetable-${run.run_name.replace(/\s+/g, '-')}.csv`, toCsv(columns, filtered()));
      }

      async function load() {
        content.innerHTML = '';
        content.appendChild(loadingBlock('Loading timetable'));
        try {
          run = await api(`/api/runs/${state.runId}`);
          const report = await api(`/api/reports/timetable?run_id=${state.runId}`);
          rows = report.rows;
          content.innerHTML = '';
          render();
          renderSide();
        } catch (err) {
          content.innerHTML = '';
          content.appendChild(h('div', { class: 'alert err', text: err.message }));
        }
      }
      await load();
    },
  });

  /* -------------------------------------------------------------- conflicts */
  route({
    id: 'conflicts',
    title: 'Conflict Management',
    render: async (view, params) => {
      view.appendChild(pageHead('Conflict Management', 'Every hard-rule violation and blocked placement, with its suggested repair.'));
      const host = h('div', null);
      view.appendChild(host);
      let runs;
      try { runs = await runOptions(); } catch (err) { host.appendChild(h('div', { class: 'alert err', text: err.message })); return; }
      if (!runs.length) {
        host.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'No scheduling runs yet' }),
          h('div', { class: 'mt12' }, h('button', { class: 'btn', text: 'Open generator', onclick: () => navigate('generator') }))));
        return;
      }
      const state = { runId: params.run || runs[0].id, severity: '' };
      const toolbar = h('div', { class: 'toolbar' });
      const content = h('div', null);
      host.appendChild(h('div', { class: 'card tight' }, toolbar));
      host.appendChild(h('div', { class: 'mt12' }, content));

      async function load() {
        toolbar.innerHTML = '';
        toolbar.appendChild(runPicker(runs, state.runId, (id) => { state.runId = id; load(); }));
        const sev = select([{ value: '', label: 'All severities' }, 'Critical', 'High', 'Medium', 'Low'], { value: state.severity, style: 'max-width:150px' });
        sev.addEventListener('change', () => { state.severity = sev.value; load(); });
        toolbar.appendChild(sev);
        toolbar.appendChild(h('span', { class: 'spacer' }));
        toolbar.appendChild(h('button', {
          class: 'btn', text: 'Attempt automatic repair',
          onclick: async () => {
            try {
              const res = await api(`/api/runs/${state.runId}/repair`, { method: 'POST' });
              modal({
                title: 'Repair attempt', wide: true,
                body: h('div', null,
                  h('div', { class: `alert ${res.hard.length ? 'warn' : 'ok'}`, text: res.hard.length
                    ? `${res.hard.length} conflict(s) could not be resolved automatically. The blocking constraints are listed below.`
                    : 'All conflicts were resolved by reassigning rooms and slots.' }),
                  res.actions.length ? h('div', { class: 'mt12' }, dataTable({
                    columns: [{ key: 'action', label: 'Action' }, { key: 'detail', label: 'Detail' }],
                    rows: res.actions,
                  })) : h('p', { class: 'small muted mt12', text: 'No alternative placement was available to try.' }),
                  res.hard.length ? h('div', { class: 'mt12' }, dataTable({
                    columns: [{ key: 'conflict_type', label: 'Type' }, { key: 'description', label: 'Blocking constraint' }],
                    rows: res.hard,
                  })) : null),
              });
              await load();
            } catch (err) { toast(err.message, 'err'); }
          },
        }));
        content.innerHTML = '';
        content.appendChild(loadingBlock('Loading conflicts'));
        try {
          const query = new URLSearchParams({ scheduling_run_id: state.runId, page_size: 200 });
          if (state.severity) query.set('severity', state.severity);
          const data = await api(`/api/conflicts?${query}`);
          const open = data.items.filter((c) => c.resolution_status === 'Open').length;
          content.innerHTML = '';
          content.appendChild(h('div', { class: 'grid kpi' },
            kpi('Total conflicts', data.total),
            kpi('Open', open, 'Unresolved'),
            kpi('Critical', data.items.filter((c) => c.severity === 'Critical').length),
            kpi('Resolved', data.items.filter((c) => c.resolution_status === 'Resolved').length)));
          content.appendChild(h('div', { class: 'mt16' }, dataTable({
            columns: [
              { key: 'conflict_type', label: 'Type' },
              { key: 'severity', label: 'Severity', render: (r) => statusPill(r.severity) },
              { key: 'description', label: 'Description' },
              { key: 'suggested_resolution', label: 'Suggested resolution' },
              { key: 'resolution_status', label: 'Status', render: (r) => statusPill(r.resolution_status) },
              {
                key: 'actions', label: '', render: (r) => (r.resolution_status === 'Open'
                  ? h('button', {
                    class: 'link-btn', text: 'Mark resolved',
                    onclick: async () => {
                      try {
                        await api(`/api/conflicts/${r.id}`, { method: 'PUT', body: { resolution_status: 'Resolved' } });
                        toast('Conflict marked resolved.', 'ok');
                        await load();
                      } catch (err) { toast(err.message, 'err'); }
                    },
                  })
                  : h('span', { class: 'tiny muted', text: '—' })),
              },
            ], rows: data.items, empty: 'No conflicts recorded for this run.',
          })));
        } catch (err) {
          content.innerHTML = '';
          content.appendChild(h('div', { class: 'alert err', text: err.message }));
        }
      }
      await load();
    },
  });

  /* ---------------------------------------------------------------- fairness */
  route({
    id: 'fairness',
    title: 'Fairness Analysis',
    render: async (view, params) => {
      view.appendChild(pageHead('Fairness Analysis', 'Workload balance across eligible invigilators for a chosen run.'));
      const host = h('div', null);
      view.appendChild(host);
      let runs;
      try { runs = await runOptions(); } catch (err) { host.appendChild(h('div', { class: 'alert err', text: err.message })); return; }
      if (!runs.length) {
        host.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'No runs to analyse' }),
          h('div', { class: 'mt12' }, h('button', { class: 'btn', text: 'Open generator', onclick: () => navigate('generator') }))));
        return;
      }
      const state = { runId: params.run || runs[0].id };
      const toolbar = h('div', { class: 'toolbar' });
      const content = h('div', null);
      host.appendChild(h('div', { class: 'card tight' }, toolbar));
      host.appendChild(h('div', { class: 'mt12' }, content));

      async function load() {
        toolbar.innerHTML = '';
        toolbar.appendChild(runPicker(runs, state.runId, (id) => { state.runId = id; load(); }));
        content.innerHTML = '';
        content.appendChild(loadingBlock('Computing metrics'));
        try {
          const fair = await api(`/api/runs/${state.runId}/fairness`);
          const s = fair.summary || {};
          content.innerHTML = '';
          content.appendChild(h('div', { class: 'grid kpi' },
            kpi('Fairness score', fmtNum(s.fairness_score, 1), 'Project-defined balance indicator'),
            kpi('Average workload', fmtNum(s.average_workload, 2), 'Duties per invigilator'),
            kpi('Workload range', fmtNum(s.workload_range), `min ${fmtNum(s.minimum_workload)} · max ${fmtNum(s.maximum_workload)}`),
            kpi('Standard deviation', fmtNum(s.standard_deviation, 3), 'Lower is fairer'),
            kpi('Consecutive duties', fmtNum(s.consecutive_duties), 'Back-to-back pairs'),
            kpi('Availability compliance', `${fmtNum(s.availability_compliance, 1)}%`, 'Duties avoiding declared leave')));
          content.appendChild(h('div', { class: 'alert info mt16', text: 'Fairness score = 100 × (1 − SD / max(mean, 1)), clamped to 0–100. It is a project-defined workload balance indicator and should be read together with availability, eligibility and individual duty limits. Hard constraints are never relaxed to improve it.' }));

          const perInv = fair.per_invigilator || [];
          content.appendChild(h('div', { class: 'grid two mt16' },
            card('Duties per invigilator', perInv.length
              ? barList(perInv.map((p) => ({ label: p.name, value: p.duties })))
              : h('div', { class: 'empty', text: 'No duties recorded.' })),
            card('Distribution', perInv.length
              ? h('div', { html: chartBar(perInv.slice(0, 12).map((p) => ({ label: p.name.split(' ').slice(-1)[0], value: p.duties })), { height: 200, color: '#0ea5e9' }) })
              : h('div', { class: 'empty', text: 'No duties recorded.' }))));

          const over = fair.overloaded || [];
          const under = fair.underutilised || [];
          content.appendChild(h('div', { class: 'grid two mt16' },
            card('Above average', over.length
              ? h('div', { class: 'split-list' }, ...over.map((p) => h('div', { class: 'list-item' }, h('b', { text: p.name }), h('small', { text: `${p.duties} duties` }))))
              : h('div', { class: 'empty', text: 'Nobody is above average.' })),
            card('Below average', under.length
              ? h('div', { class: 'split-list' }, ...under.map((p) => h('div', { class: 'list-item' }, h('b', { text: p.name }), h('small', { text: `${p.duties} duties` }))))
              : h('div', { class: 'empty', text: 'Nobody is below average.' }))));

          const suggestions = [];
          if (s.standard_deviation > 0.5) suggestions.push('Standard deviation is above 0.5 duties; prefer the balanced allocator over First-Fit for the next run.');
          if ((s.consecutive_duties || 0) > 0) suggestions.push(`${fmtNum(s.consecutive_duties)} back-to-back duty pair(s) exist; raise the "avoid consecutive duties" weight.`);
          if ((s.availability_compliance || 100) < 100) suggestions.push('Some duties fall inside declared unavailability; check leave records before publishing.');
          if ((s.fairness_score || 0) >= 80) suggestions.push('Balance is strong for this run; no redistribution is required.');
          content.appendChild(h('div', { class: 'mt16' }, card('Suggested improvements',
            suggestions.length ? h('ul', { class: 'small', style: 'margin-left:16px' }, ...suggestions.map((t) => h('li', { text: t })))
              : h('div', { class: 'empty', text: 'No improvement needed.' }))));
        } catch (err) {
          content.innerHTML = '';
          content.appendChild(h('div', { class: 'alert err', text: err.message }));
        }
      }
      await load();
    },
  });

  /* -------------------------------------------------------------- comparison */
  route({
    id: 'comparison',
    title: 'Algorithm Comparison',
    render: async (view) => {
      view.appendChild(pageHead('Algorithm Comparison', 'The same dataset solved twice: deterministic First-Fit against the CSP search.', [
        h('button', {
          class: 'btn secondary', text: 'Run First-Fit baseline',
          onclick: async (e) => {
            const btn = e.target;
            btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running';
            try {
              await api('/api/scheduling/run', { method: 'POST', body: { algorithm: 'first_fit', run_name: 'First-Fit baseline', options: {} } });
              toast('Baseline completed.', 'ok');
              App.renderRoute();
            } catch (err) { toast(err.message, 'err'); btn.disabled = false; btn.textContent = 'Run First-Fit baseline'; }
          },
        }),
        h('button', {
          class: 'btn', text: 'Run AI search',
          onclick: async (e) => {
            const btn = e.target;
            btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Running';
            try {
              await api('/api/scheduling/run', { method: 'POST', body: { algorithm: 'csp', run_name: 'AI CSP run', options: { auto_repair: true } } });
              toast('AI run completed.', 'ok');
              App.renderRoute();
            } catch (err) { toast(err.message, 'err'); btn.disabled = false; btn.textContent = 'Run AI search'; }
          },
        }),
      ]));
      const host = h('div', null);
      view.appendChild(host);
      host.appendChild(loadingBlock('Loading comparison'));
      try {
        const cmp = await api('/api/comparison');
        const b = cmp.baseline; const c = cmp.candidate;
        host.innerHTML = '';
        const label = { baseline: 'Baseline', candidate: 'AI search' };
        const metricRows = [
          ['Scheduled examinations', b.scheduled_examinations, c.scheduled_examinations, 'higher'],
          ['Unscheduled examinations', b.unscheduled_examinations, c.unscheduled_examinations, 'lower'],
          ['Hard constraint violations', b.hard_constraint_violations, c.hard_constraint_violations, 'lower'],
          ['Soft constraint penalty', b.soft_constraint_penalty, c.soft_constraint_penalty, 'lower'],
          ['Workload standard deviation', b.workload_standard_deviation, c.workload_standard_deviation, 'lower'],
          ['Fairness score', b.fairness_score, c.fairness_score, 'higher'],
          ['Room utilisation (%)', b.room_utilization, c.room_utilization, 'higher'],
          ['Execution time (s)', b.execution_time, c.execution_time, 'neutral'],
        ];
        host.appendChild(h('div', { class: 'grid two' },
          card(`Baseline · ${b.algorithm}`, h('div', null,
            h('dl', { class: 'kv' },
              h('dt', { text: 'Status' }), h('dd', null, statusPill(b.solver_status)),
              h('dt', { text: 'Scheduled' }), h('dd', { text: `${b.scheduled_examinations} of ${b.scheduled_examinations + b.unscheduled_examinations}` }),
              h('dt', { text: 'Penalty' }), h('dd', { text: fmtNum(b.soft_constraint_penalty, 2) }),
              h('dt', { text: 'Fairness' }), h('dd', { text: fmtNum(b.fairness_score, 1) })))),
          card(`Candidate · ${c.algorithm}`, h('div', null,
            h('dl', { class: 'kv' },
              h('dt', { text: 'Status' }), h('dd', null, statusPill(c.solver_status)),
              h('dt', { text: 'Scheduled' }), h('dd', { text: `${c.scheduled_examinations} of ${c.scheduled_examinations + c.unscheduled_examinations}` }),
              h('dt', { text: 'Penalty' }), h('dd', { text: fmtNum(c.soft_constraint_penalty, 2) }),
              h('dt', { text: 'Fairness' }), h('dd', { text: fmtNum(c.fairness_score, 1) }))))));

        host.appendChild(h('div', { class: 'mt16' }, card('Metric comparison', dataTable({
          columns: [
            { key: 'metric', label: 'Metric' },
            { key: 'baseline', label: 'First-Fit', num: true },
            { key: 'candidate', label: 'AI search', num: true },
            {
              key: 'delta', label: 'Difference', num: true,
              render: (r) => {
                const delta = Number(r.candidate) - Number(r.baseline);
                if (!delta) return h('span', { class: 'tiny muted', text: 'no change' });
                const better = r.pref === 'higher' ? delta > 0 : delta < 0;
                return h('span', { style: `color:${better ? '#16a34a' : '#dc2626'};font-weight:600`, text: `${delta > 0 ? '+' : ''}${Math.round(delta * 100) / 100}` });
              },
            },
          ],
          rows: metricRows.map(([metric, base, cand, pref]) => ({ id: metric, metric, baseline: base, candidate: cand, pref })),
        }), 'Differences are candidate minus baseline')));

        host.appendChild(h('div', { class: 'grid two mt16' },
          card('Soft constraint penalty', h('div', { html: chartBar([
            { label: 'First-Fit', value: b.soft_constraint_penalty, color: '#94a3b8' },
            { label: 'AI search', value: c.soft_constraint_penalty, color: '#2563eb' },
          ], { height: 180, label: 'Penalty comparison' }) }), 'Lower is better'),
          card('Workload balance', h('div', { html: chartBar([
            { label: 'First-Fit SD', value: b.workload_standard_deviation, color: '#94a3b8' },
            { label: 'AI SD', value: c.workload_standard_deviation, color: '#16a34a' },
          ], { height: 180, label: 'Standard deviation comparison' }) }), 'Lower is fairer')));

        host.appendChild(h('div', { class: 'alert info mt16', text: 'A run is marked feasible only when every mandatory constraint holds. Neither algorithm claims optimality unless a proven optimiser (CP-SAT) reports it.' }));
      } catch (err) {
        host.innerHTML = '';
        host.appendChild(h('div', { class: 'alert warn', text: err.message }));
      }
    },
  });

  App.schedulingReady = true;
})();
