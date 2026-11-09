/* ExamFlow AI · administration pages (dashboard, masters, calendar, settings) */
(function () {
  const {
    h, api, toast, modal, confirmAction, field, select, inputEl, formModal, dataTable, pill,
    statusPill, chartBar, chartLine, chartDonut, barList, kpi, card, pageHead, loadingBlock,
    downloadFile, toCsv, route, navigate, fmtDate, fmtDateTime, fmtNum, schoolName, icon,
  } = App;

  const meta = () => App.state.meta;
  const optSchools = () => meta().schools.map((s) => ({ value: s.id, label: s.school_name }));
  const optDepts = (schoolId) => meta().departments
    .filter((d) => !schoolId || d.school_id === schoolId)
    .map((d) => ({ value: d.id, label: `${d.name} (${d.code})` }));
  const optGroups = (schoolId) => meta().groups
    .filter((g) => !schoolId || g.school_id === schoolId)
    .map((g) => ({ value: g.id, label: `${g.name}${g.section ? ` · ${g.section}` : ''} (${g.student_count})` }));
  const optInvs = (schoolId) => meta().invigilators
    .filter((i) => !schoolId || i.school_id === schoolId)
    .map((i) => ({ value: i.id, label: `${i.name} (${i.code})` }));
  const groupNames = (ids) => (ids || []).map((id) => (meta().groups.find((g) => g.id === id) || {}).name).filter(Boolean).join(', ');

  /* ----------------------------------------------------------- resource page */
  function resourcePage(cfg) {
    return {
      id: cfg.id,
      title: cfg.title,
      render: async (view, params) => {
        const state = { q: params.q || '', page: 1, filters: {} };
        const rowsBox = h('div', null);
        const pagerBox = h('div', { class: 'pager' });
        const filterBox = h('div', { class: 'toolbar' });

        const search = inputEl({ placeholder: cfg.searchPlaceholder || 'Search…', value: state.q, style: 'max-width:280px' });
        let timer;
        search.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(() => { state.q = search.value; state.page = 1; load(); }, 260);
        });
        filterBox.appendChild(search);

        for (const f of cfg.filters ? cfg.filters() : []) {
          const el = select([{ value: '', label: f.label }, ...f.options], { style: 'max-width:210px' });
          el.addEventListener('change', () => { state.filters[f.name] = el.value; state.page = 1; load(); });
          filterBox.appendChild(el);
        }
        filterBox.appendChild(h('span', { class: 'spacer' }));

        const actions = h('div', { class: 'row wrap' });
        if (cfg.canCreate !== false) {
          actions.appendChild(h('button', {
            class: 'btn', onclick: () => openForm(null),
          }, icon('check', 15), cfg.addLabel || 'Add record'));
        }
        if (cfg.importable) {
          actions.appendChild(h('button', { class: 'btn secondary', onclick: openImport }, icon('download', 15), 'Import CSV'));
        }
        actions.appendChild(h('button', { class: 'btn secondary', onclick: exportCsv }, icon('download', 15), 'Export CSV'));

        view.appendChild(pageHead(cfg.title, cfg.subtitle, actions));
        view.appendChild(h('div', { class: 'card tight' }, filterBox));
        view.appendChild(h('div', { class: 'mt12' }, rowsBox));
        view.appendChild(pagerBox);

        let lastRows = [];

        async function load() {
          rowsBox.innerHTML = '';
          rowsBox.appendChild(loadingBlock('Loading records'));
          const query = new URLSearchParams({ page: state.page, page_size: 15 });
          if (state.q) query.set('q', state.q);
          for (const [key, value] of Object.entries(state.filters)) if (value) query.set(key, value);
          try {
            const data = await api(`/api/${cfg.resource}?${query}`);
            lastRows = data.items;
            rowsBox.innerHTML = '';
            rowsBox.appendChild(dataTable({ columns: cfg.columns(data.items), rows: data.items, empty: cfg.empty }));
            pagerBox.innerHTML = '';
            pagerBox.append(
              h('span', { text: `${data.total} record${data.total === 1 ? '' : 's'} · page ${data.page} of ${data.pages}` }),
              h('span', { class: 'spacer' }),
              h('button', { class: 'btn secondary', text: 'Previous', disabled: data.page <= 1, onclick: () => { state.page -= 1; load(); } }),
              h('button', { class: 'btn secondary', text: 'Next', disabled: data.page >= data.pages, onclick: () => { state.page += 1; load(); } }));
          } catch (err) {
            rowsBox.innerHTML = '';
            rowsBox.appendChild(h('div', { class: 'alert err', text: err.message }));
          }
        }

        function openForm(record) {
          formModal({
            title: record ? `Edit ${cfg.singular}` : `New ${cfg.singular}`,
            wide: cfg.wideForm,
            intro: cfg.formIntro,
            values: record || {},
            fields: cfg.fields(record),
            submitLabel: record ? 'Save changes' : 'Create',
            onSubmit: async (payload) => {
              if (record) await api(`/api/${cfg.resource}/${record.id}`, { method: 'PUT', body: payload });
              else await api(`/api/${cfg.resource}`, { method: 'POST', body: payload });
              toast(`${cfg.singular} ${record ? 'updated' : 'created'}.`, 'ok');
              await reloadMeta();
              load();
            },
          });
        }

        function rowActions(row) {
          const box = h('div', { class: 'row', style: 'gap:4px' });
          box.appendChild(h('button', { class: 'link-btn', text: 'Edit', onclick: () => openForm(row) }));
          if (cfg.detail) box.appendChild(h('button', { class: 'link-btn', text: 'View', onclick: () => cfg.detail(row) }));
          if (cfg.canDelete !== false) {
            box.appendChild(h('button', {
              class: 'link-btn danger', text: 'Delete',
              onclick: async () => {
                const ok = await confirmAction({
                  title: `Delete ${cfg.singular.toLowerCase()}?`,
                  message: cfg.deleteMessage ? cfg.deleteMessage(row) : 'This cannot be undone. Dependent records will block the delete.',
                });
                if (!ok) return;
                try {
                  await api(`/api/${cfg.resource}/${row.id}`, { method: 'DELETE' });
                  toast(`${cfg.singular} deleted.`, 'ok');
                  await reloadMeta();
                  load();
                } catch (err) { toast(err.message, 'err'); }
              },
            }));
          }
          return box;
        }

        function openImport() {
          const area = h('textarea', { class: 'textarea', style: 'min-height:170px', placeholder: cfg.importSample });
          const body = h('div', null,
            h('div', { class: 'alert info', style: 'margin-bottom:10px', text: 'Paste CSV rows. The first line must be the header row.' }),
            h('div', { class: 'tiny muted', style: 'margin-bottom:6px', text: 'Expected header:' }),
            h('pre', { class: 'mono', style: 'background:#f8fafc;padding:8px;border-radius:8px;overflow:auto', text: cfg.importSample }),
            field('CSV content', area));
          const run = h('button', { class: 'btn', text: 'Import rows' });
          const m = modal({ title: `Import ${cfg.singular.toLowerCase()}s`, body, wide: true, footer: [h('button', { class: 'btn secondary', text: 'Cancel', onclick: () => m.close() }), run] });
          run.addEventListener('click', async () => {
            run.disabled = true;
            run.innerHTML = '<span class="spinner"></span> Importing';
            try {
              const res = await api(`/api/import/${cfg.resource}`, { method: 'POST', body: { csv: area.value } });
              m.close();
              if (res.errors.length) {
                modal({ title: 'Import finished with errors', wide: true, body: h('div', null,
                  h('div', { class: 'alert ok', style: 'margin-bottom:10px', text: `${res.created} row(s) imported.` }),
                  h('div', { class: 'alert warn', text: `${res.errors.length} row(s) were rejected.` }),
                  h('ul', { class: 'small', style: 'margin-top:10px' }, ...res.errors.map((e) => h('li', { text: e })))) });
              } else {
                toast(`${res.created} row(s) imported.`, 'ok');
              }
              await reloadMeta();
              load();
            } catch (err) {
              toast(err.message, 'err');
              run.disabled = false;
              run.textContent = 'Import rows';
            }
          });
        }

        function exportCsv() {
          const columns = cfg.columns(lastRows).filter((c) => c.key);
          downloadFile(`${cfg.resource}-export.csv`, toCsv(columns, lastRows));
        }

        cfg.openForm = openForm;
        cfg.rowActions = rowActions;
        cfg.reload = load;
        await load();
      },
    };
  }

  async function reloadMeta() {
    try { App.state.meta = await api('/api/meta'); } catch (err) { /* ignore */ }
  }

  const actionsCol = (cfg) => ({ key: 'actions', label: '', render: (row) => cfg.rowActions(row) });

  /* --------------------------------------------------------------- dashboard */
  route({
    id: 'dashboard',
    title: 'Dashboard',
    render: async (view) => {
      view.appendChild(pageHead('Dashboard', 'Live operational view of examinations, resources and scheduling health.',
        [
          h('button', { class: 'btn secondary', onclick: () => navigate('timetable') }, icon('grid', 15), 'View timetable'),
          h('button', { class: 'btn', onclick: () => navigate('generator') }, icon('spark', 15), 'Generate timetable'),
        ]));
      view.appendChild(loadingBlock('Loading live metrics'));
      let data;
      try { data = await api('/api/dashboard'); } catch (err) {
        view.innerHTML = '';
        view.appendChild(pageHead('Dashboard', 'Live operational view'));
        view.appendChild(h('div', { class: 'alert err', text: err.message }));
        return;
      }
      view.innerHTML = '';
      view.appendChild(pageHead('Dashboard', 'Live operational view of examinations, resources and scheduling health.',
        [
          h('button', { class: 'btn secondary', onclick: () => navigate('timetable') }, icon('grid', 15), 'View timetable'),
          h('button', { class: 'btn', onclick: () => navigate('generator') }, icon('spark', 15), 'Generate timetable'),
        ]));

      const c = data.counts;
      view.appendChild(h('div', { class: 'grid kpi' },
        kpi('Schools', c.schools, `${c.departments} departments`),
        kpi('Examinations', c.examinations, `${c.pending} pending`),
        kpi('Student groups', c.student_groups, `${fmtNum(c.students)} students`),
        kpi('Rooms', c.rooms, 'Active rooms'),
        kpi('Invigilators', c.invigilators, 'Faculty available'),
        kpi('Scheduled', c.scheduled, `${c.scheduled ? Math.round(100 * c.scheduled / Math.max(c.examinations, 1)) : 0}% of examinations`),
        kpi('Open conflicts', c.conflicts, 'Unresolved'),
        kpi('Scheduling runs', c.runs, `${c.published} published`)));

      const latest = data.latest_run;
      view.appendChild(h('div', { class: 'grid two mt16' },
        card('Examinations by school', data.exams_by_school.length
          ? h('div', { html: chartBar(data.exams_by_school, { height: 200, label: 'Examinations per school' }) })
          : h('div', { class: 'empty', text: 'No examinations yet.' }), 'Live counts'),
        card('Scheduled vs pending', h('div', { html: chartDonut(data.scheduled_split, {
          centerValue: c.examinations, centerLabel: 'examinations', size: 170,
        }) }), latest ? latest.algorithm_name.split(' ')[0] : 'No run yet')));

      view.appendChild(h('div', { class: 'grid two mt16' },
        card('Daily examination load', data.daily.length
          ? h('div', { html: chartBar(data.daily.map((d) => ({ label: String(d.label).slice(5), value: d.value })), { height: 200, color: '#0ea5e9', label: 'Examinations per day' }) })
          : h('div', { class: 'empty', text: 'Generate a timetable to see daily load.' }), 'Latest run'),
        card('Invigilator workload', data.workload.length
          ? barList(data.workload.slice(0, 9))
          : h('div', { class: 'empty', text: 'No duties allocated yet.' }), 'Duties per invigilator')));

      view.appendChild(h('div', { class: 'grid two mt16' },
        card('Room utilisation', data.room_usage.length
          ? barList(data.room_usage.map((r) => ({ label: r.label, value: r.capacity ? Math.round(100 * (r.capacity || 0)) : r.bookings, color: '#16a34a' })))
          : h('div', { class: 'empty', text: 'No room bookings yet.' }), 'Seat utilisation per room'),
        card('AI scheduling performance', latest
          ? h('div', null,
            h('dl', { class: 'kv' },
              h('dt', { text: 'Algorithm' }), h('dd', { text: latest.algorithm_name }),
              h('dt', { text: 'Solver status' }), h('dd', null, statusPill(latest.solver_status)),
              h('dt', { text: 'Hard violations' }), h('dd', { text: latest.hard_constraint_violations }),
              h('dt', { text: 'Soft penalty' }), h('dd', { text: fmtNum(latest.soft_constraint_penalty, 2) }),
              h('dt', { text: 'Execution time' }), h('dd', { text: `${fmtNum(latest.execution_time, 3)} s` }),
              h('dt', { text: 'Fairness score' }), h('dd', { text: `${fmtNum(data.fairness?.fairness_score, 1)} / 100` })))
          : h('div', { class: 'empty', text: 'No scheduling run has been executed yet.' }), 'Latest run')));

      if (data.comparison) {
        const b = data.comparison.baseline; const cand = data.comparison.candidate;
        view.appendChild(h('div', { class: 'mt16' }, card('First-Fit vs AI comparison',
          h('div', { class: 'grid two' },
            h('div', null, h('div', { class: 'small muted', text: `First-Fit penalty ${fmtNum(b.soft_constraint_penalty, 2)} · fairness ${fmtNum(b.fairness_score, 1)}` }),
              h('div', { html: chartBar([
                { label: 'First-Fit', value: b.soft_constraint_penalty, color: '#94a3b8' },
                { label: 'CSP AI', value: cand.soft_constraint_penalty, color: '#2563eb' },
              ], { height: 170, label: 'Soft constraint penalty' }) })),
            h('div', null, h('div', { class: 'small muted', text: `CSP soft penalty ${fmtNum(cand.soft_constraint_penalty, 2)} · fairness ${fmtNum(cand.fairness_score, 1)}` }),
              h('div', { html: chartBar([
                { label: 'First-Fit', value: b.workload_standard_deviation, color: '#94a3b8' },
                { label: 'CSP AI', value: cand.workload_standard_deviation, color: '#16a34a' },
              ], { height: 170, label: 'Workload standard deviation' }) }))),
          'Lower penalty and deviation is better')));
      }

      view.appendChild(h('div', { class: 'grid two mt16' },
        card('Upcoming examinations', data.upcoming.length
          ? dataTable({
            columns: [
              { key: 'examination_date', label: 'Date', render: (r) => fmtDate(r.examination_date, true) },
              { key: 'start_time', label: 'Time', render: (r) => `${r.start_time}–${r.end_time}` },
              { key: 'subject_code', label: 'Code' },
              { key: 'subject_name', label: 'Examination' },
              { key: 'room_number', label: 'Room' },
            ], rows: data.upcoming.map((r) => ({ ...r, id: `${r.subject_code}${r.start_time}` })),
          })
          : h('div', { class: 'empty', text: 'No scheduled examinations yet.' })),
        card('Recent activity', data.recent.length
          ? h('div', { class: 'split-list' }, ...data.recent.map((r) => h('div', { class: 'list-item' },
            h('b', { text: r.action }), h('small', { text: `${r.entity_type || ''} · ${fmtDateTime(r.created_at)}` }))))
          : h('div', { class: 'empty', text: 'No activity recorded yet.' }))));

      if (data.conflicts.length) {
        view.appendChild(h('div', { class: 'mt16' }, card('Unresolved conflicts',
          h('div', { class: 'split-list' }, ...data.conflicts.map((cf) => h('div', { class: 'list-item' },
            h('b', { text: cf.conflict_type }, ' ', statusPill(cf.severity)),
            h('small', { text: cf.description })))),
          'Open issues from the latest runs')));
      }
    },
  });

  /* ----------------------------------------------------------------- schools */
  route(resourcePage({
    id: 'schools', resource: 'schools', singular: 'School', title: 'Schools',
    subtitle: 'Institutions managed by the platform. School codes must be unique.',
    searchPlaceholder: 'Search name, code or email',
    columns: () => [
      { key: 'school_name', label: 'School' },
      { key: 'school_code', label: 'Code' },
      { key: 'contact_email', label: 'Contact' },
      { key: 'contact_number', label: 'Phone' },
      { key: 'status', label: 'Status', render: (r) => statusPill(r.status) },
      actionsCol({ rowActions: rowsActionProxy('schools') }),
    ],
    fields: () => [
      { name: 'school_name', label: 'School name', full: true },
      { name: 'school_code', label: 'School code', help: 'Unique short code, e.g. NIT' },
      { name: 'status', label: 'Status', type: 'select', options: ['Active', 'Inactive'] },
      { name: 'address', label: 'Address', full: true },
      { name: 'contact_email', label: 'Contact email', type: 'email' },
      { name: 'contact_number', label: 'Contact number' },
    ],
    detail: (row) => schoolDetail(row),
  }));

  function rowsActionProxy(resource) {
    return (row) => {
      const page = App.routes[resource];
      return page && page.rowActions ? page.rowActions(row) : h('span');
    };
  }

  function schoolDetail(row) {
    const m = meta();
    const depts = m.departments.filter((d) => d.school_id === row.id);
    const groups = m.groups.filter((g) => g.school_id === row.id);
    const rooms = m.rooms.filter((r) => r.school_id === row.id);
    const invs = m.invigilators.filter((i) => i.school_id === row.id);
    const exams = m.examinations.filter((e) => e.school_id === row.id);
    modal({
      title: row.school_name, wide: true,
      body: h('div', null,
        h('dl', { class: 'kv' },
          h('dt', { text: 'Code' }), h('dd', { text: row.school_code }),
          h('dt', { text: 'Address' }), h('dd', { text: row.address || '—' }),
          h('dt', { text: 'Contact' }), h('dd', { text: `${row.contact_email || '—'} · ${row.contact_number || '—'}` })),
        h('div', { class: 'grid four mt16' },
          kpi('Departments', depts.length), kpi('Student groups', groups.length),
          kpi('Rooms', rooms.length), kpi('Invigilators', invs.length)),
        h('div', { class: 'mt16 small' },
          h('strong', { text: 'Sharing the timetable: ' }),
          `${exams.length} examination(s), ${groups.reduce((s, g) => s + (g.student_count || 0), 0)} students enrolled.`)),
    });
  }

  /* ------------------------------------------------------------- departments */
  route(resourcePage({
    id: 'departments', resource: 'departments', singular: 'Department', title: 'Departments',
    subtitle: 'Departments belong to a school and own student groups and examinations.',
    columns: () => [
      { key: 'department_name', label: 'Department' },
      { key: 'department_code', label: 'Code' },
      { key: 'school_id', label: 'School', render: (r) => schoolName(r.school_id) },
      actionsCol({ rowActions: rowsActionProxy('departments') }),
    ],
    filters: () => [{ name: 'school_id', label: 'All schools', options: optSchools() }],
    fields: () => [
      { name: 'school_id', label: 'School', type: 'select', options: optSchools() },
      { name: 'department_name', label: 'Department name' },
      { name: 'department_code', label: 'Department code' },
    ],
  }));

  /* ---------------------------------------------------------- student groups */
  route(resourcePage({
    id: 'student-groups', resource: 'student-groups', singular: 'Student group', title: 'Student Groups',
    subtitle: 'Cohorts that sit examinations together. Overlapping examinations for one group are blocked.',
    searchPlaceholder: 'Search group name or section',
    importable: true,
    importSample: 'school_code,department_code,group_name,semester,section,student_count,academic_year\nNIT,CSE,B.Tech CSE Sem 7,7,A,52,2026-27',
    columns: () => [
      { key: 'group_name', label: 'Group' },
      { key: 'section', label: 'Section' },
      { key: 'semester', label: 'Semester', num: true },
      { key: 'student_count', label: 'Students', num: true },
      { key: 'academic_year', label: 'Year' },
      { key: 'school_id', label: 'School', render: (r) => schoolName(r.school_id) },
      actionsCol({ rowActions: rowsActionProxy('student-groups') }),
    ],
    filters: () => [
      { name: 'school_id', label: 'All schools', options: optSchools() },
      { name: 'semester', label: 'All semesters', options: [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ value: n, label: `Semester ${n}` })) },
    ],
    fields: () => [
      { name: 'school_id', label: 'School', type: 'select', options: optSchools() },
      { name: 'department_id', label: 'Department', type: 'select', options: optDepts() },
      { name: 'group_name', label: 'Group name', full: true, placeholder: 'e.g. B.Tech CSE Sem 5' },
      { name: 'semester', label: 'Semester', type: 'number', min: 1, max: 8 },
      { name: 'section', label: 'Section', placeholder: 'A' },
      { name: 'student_count', label: 'Number of students', type: 'number', min: 1 },
      { name: 'academic_year', label: 'Academic year', placeholder: '2026-27' },
    ],
  }));

  /* ------------------------------------------------------------ examinations */
  route(resourcePage({
    id: 'examinations', resource: 'examinations', singular: 'Examination', title: 'Examinations',
    subtitle: 'Every examination is a scheduling variable. Seating capacity is derived from its student groups.',
    searchPlaceholder: 'Search subject or code',
    wideForm: true,
    importable: true,
    importSample: 'school_code,subject_name,subject_code,examination_type,group_codes,duration_minutes,priority,preferred_date,facilities\nNIT,Compiler Design,CS401,Written,B.Tech CSE Sem 5,180,High,2026-11-18,computer lab',
    columns: () => [
      { key: 'subject_code', label: 'Code' },
      { key: 'subject_name', label: 'Examination' },
      { key: 'school_id', label: 'School', render: (r) => schoolName(r.school_id) },
      { key: 'student_group_ids', label: 'Groups', render: (r) => h('span', { class: 'tiny', text: groupNames(r.student_group_ids) || '—' }) },
      { key: 'required_seating_capacity', label: 'Students', num: true },
      { key: 'duration_minutes', label: 'Minutes', num: true },
      { key: 'priority', label: 'Priority', render: (r) => statusPill(r.priority) },
      { key: 'status', label: 'Status', render: (r) => statusPill(r.status) },
      actionsCol({ rowActions: rowsActionProxy('examinations') }),
    ],
    filters: () => [
      { name: 'school_id', label: 'All schools', options: optSchools() },
      { name: 'priority', label: 'All priorities', options: meta().priorities },
      { name: 'status', label: 'All statuses', options: ['Pending', 'Scheduled', 'Cancelled'] },
    ],
    fields: (record) => [
      { name: 'school_id', label: 'School', type: 'select', options: optSchools(),
        onChange: (value, getters) => { /* dependent selects are rebuilt on save */ } },
      { name: 'department_id', label: 'Department', type: 'select', options: optDepts(record && record.school_id) },
      { name: 'subject_name', label: 'Subject name', full: true },
      { name: 'subject_code', label: 'Subject code' },
      { name: 'examination_type', label: 'Type', type: 'select', options: ['Written', 'Practical', 'Viva', 'Online'] },
      { name: 'student_group_ids', label: 'Student groups', type: 'multi', full: true, options: optGroups(record && record.school_id),
        help: 'Capacity is calculated automatically from the selected groups.' },
      { name: 'duration_minutes', label: 'Duration (minutes)', type: 'number', min: 15, step: 15 },
      { name: 'priority', label: 'Priority', type: 'select', options: meta().priorities },
      { name: 'preferred_dates', label: 'Preferred date', type: 'date', help: 'Soft preference only; hard limits are never broken for it.' },
      { name: 'required_facilities', label: 'Required facilities', placeholder: 'computer lab, projector' },
      { name: 'special_requirements', label: 'Special requirements', type: 'textarea', full: true },
    ],
    detail: (row) => {
      modal({
        title: `${row.subject_code} · ${row.subject_name}`, wide: true,
        body: h('div', null,
          h('dl', { class: 'kv' },
            h('dt', { text: 'School' }), h('dd', { text: schoolName(row.school_id) }),
            h('dt', { text: 'Student groups' }), h('dd', { text: groupNames(row.student_group_ids) || '—' }),
            h('dt', { text: 'Students' }), h('dd', { text: row.required_seating_capacity }),
            h('dt', { text: 'Duration' }), h('dd', { text: `${row.duration_minutes} minutes` }),
            h('dt', { text: 'Priority' }), h('dd', null, statusPill(row.priority)),
            h('dt', { text: 'Status' }), h('dd', null, statusPill(row.status)),
            h('dt', { text: 'Preferred dates' }), h('dd', { text: (row.preferred_dates || []).join(', ') || '—' }),
            h('dt', { text: 'Facilities' }), h('dd', { text: (row.required_facilities || []).join(', ') || 'None' }),
            h('dt', { text: 'Special requirements' }), h('dd', { text: row.special_requirements || '—' }))),
      });
    },
  }));

  /* ------------------------------------------------------------------- rooms */
  route(resourcePage({
    id: 'rooms', resource: 'rooms', singular: 'Room', title: 'Rooms Management',
    subtitle: 'Capacity, facilities and availability drive which rooms the solver can use.',
    columns: () => [
      { key: 'room_number', label: 'Room' },
      { key: 'building', label: 'Building' },
      { key: 'floor', label: 'Floor', num: true },
      { key: 'capacity', label: 'Capacity', num: true },
      { key: 'room_type', label: 'Type' },
      { key: 'facilities', label: 'Facilities', render: (r) => h('span', { class: 'tiny', text: (r.facilities || []).join(', ') || '—' }) },
      { key: 'is_active', label: 'Active', render: (r) => statusPill(r.is_active ? 'Active' : 'Inactive') },
      actionsCol({ rowActions: rowsActionProxy('rooms') }),
    ],
    filters: () => [{ name: 'school_id', label: 'All schools', options: optSchools() }],
    fields: () => [
      { name: 'school_id', label: 'School', type: 'select', options: optSchools() },
      { name: 'room_number', label: 'Room number' },
      { name: 'building', label: 'Building' },
      { name: 'floor', label: 'Floor', type: 'number', min: 0 },
      { name: 'capacity', label: 'Seating capacity', type: 'number', min: 1 },
      { name: 'room_type', label: 'Room type', type: 'select', options: ['Classroom', 'Exam Hall', 'Computer Lab', 'Seminar Room', 'Laboratory'] },
      { name: 'facilities', label: 'Facilities', placeholder: 'computer lab, projector', full: true },
      { name: 'is_accessible', label: 'Accessible room', type: 'checkbox', checkLabel: 'Wheelchair accessible' },
      { name: 'is_active', label: 'Available for scheduling', type: 'checkbox', checkLabel: 'Room is active' },
    ],
  }));

  /* ------------------------------------------------------------ invigilators */
  route(resourcePage({
    id: 'invigilators', resource: 'invigilators', singular: 'Invigilator', title: 'Invigilators',
    subtitle: 'Faculty available for invigilation duty, with individual daily and total limits.',
    searchPlaceholder: 'Search name, code or email',
    importable: true,
    importSample: 'school_code,name,employee_code,email,maximum_daily_duties,maximum_total_duties\nNIT,Dr. Neha Kulkarni,NIT-F13,neha@example.edu,2,8',
    columns: () => [
      { key: 'name', label: 'Invigilator' },
      { key: 'employee_code', label: 'Code' },
      { key: 'school_id', label: 'School', render: (r) => schoolName(r.school_id) },
      { key: 'maximum_daily_duties', label: 'Max/day', num: true },
      { key: 'maximum_total_duties', label: 'Max total', num: true },
      { key: 'status', label: 'Status', render: (r) => statusPill(r.status) },
      actionsCol({ rowActions: rowsActionProxy('invigilators') }),
    ],
    filters: () => [
      { name: 'school_id', label: 'All schools', options: optSchools() },
      { name: 'status', label: 'All statuses', options: ['Active', 'Inactive', 'On Leave'] },
    ],
    fields: () => [
      { name: 'school_id', label: 'School', type: 'select', options: optSchools() },
      { name: 'department_id', label: 'Department', type: 'select', options: optDepts() },
      { name: 'name', label: 'Full name' },
      { name: 'employee_code', label: 'Employee code' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'qualification', label: 'Qualification / subject' },
      { name: 'maximum_daily_duties', label: 'Maximum duties per day', type: 'number', min: 1 },
      { name: 'maximum_total_duties', label: 'Maximum total duties', type: 'number', min: 1 },
      { name: 'preferred_duties', label: 'Preferred duties in run', type: 'number', min: 0 },
      { name: 'status', label: 'Status', type: 'select', options: ['Active', 'Inactive', 'On Leave'] },
    ],
  }));

  /* ------------------------------------------------------------- availability */
  route(resourcePage({
    id: 'availability', resource: 'availability', singular: 'Date restriction', title: 'Faculty Availability',
    subtitle: 'Declared leave and unavailability windows. The solver and validator both respect these.',
    columns: () => [
      { key: 'invigilator_id', label: 'Invigilator', render: (r) => (meta().invigilators.find((i) => i.id === r.invigilator_id) || {}).name || '—' },
      { key: 'date', label: 'Date', render: (r) => fmtDate(r.date, true) },
      { key: 'start_time', label: 'From' },
      { key: 'end_time', label: 'To' },
      { key: 'availability_status', label: 'Status', render: (r) => statusPill(r.availability_status) },
      { key: 'reason', label: 'Reason' },
      actionsCol({ rowActions: rowsActionProxy('availability') }),
    ],
    fields: () => [
      { name: 'invigilator_id', label: 'Invigilator', type: 'select', options: optInvs() },
      { name: 'date', label: 'Date', type: 'date' },
      { name: 'start_time', label: 'From', type: 'time', value: '09:00' },
      { name: 'end_time', label: 'To', type: 'time', value: '17:00' },
      { name: 'availability_status', label: 'Status', type: 'select', options: ['Unavailable', 'Leave', 'Available'] },
      { name: 'reason', label: 'Reason', full: true },
    ],
  }));

  /* --------------------------------------------------------------- time slots */
  route(resourcePage({
    id: 'time-slots', resource: 'time-slots', singular: 'Time slot', title: 'Time Slots',
    subtitle: 'The examination period. Slots are shared across schools so sessions stay aligned.',
    columns: () => [
      { key: 'examination_date', label: 'Date', render: (r) => fmtDate(r.examination_date, true) },
      { key: 'start_time', label: 'Start' },
      { key: 'end_time', label: 'End' },
      { key: 'session', label: 'Session', render: (r) => pill(r.session, r.session === 'Morning' ? 'blue' : r.session === 'Afternoon' ? 'amber' : 'grey') },
      { key: 'is_active', label: 'Active', render: (r) => statusPill(r.is_active ? 'Active' : 'Inactive') },
      actionsCol({ rowActions: rowsActionProxy('time-slots') }),
    ],
    filters: () => [{ name: 'session', label: 'All sessions', options: ['Morning', 'Afternoon', 'Evening'] }],
    fields: () => [
      { name: 'examination_date', label: 'Date', type: 'date' },
      { name: 'start_time', label: 'Start time', type: 'time' },
      { name: 'end_time', label: 'End time', type: 'time' },
      { name: 'session', label: 'Session', type: 'select', options: ['Morning', 'Afternoon', 'Evening'] },
      { name: 'is_active', label: 'Slot enabled', type: 'checkbox', checkLabel: 'Available for scheduling' },
    ],
  }));

  /* ---------------------------------------------------------------- policies */
  route(resourcePage({
    id: 'policies', resource: 'policies', singular: 'Constraint policy', title: 'Constraints & Policies',
    subtitle: 'Mandatory rules are hard constraints. Soft rules add weighted penalties to the objective.',
    columns: () => [
      { key: 'policy_name', label: 'Policy' },
      { key: 'constraint_type', label: 'Type', render: (r) => pill(r.constraint_type, r.constraint_type === 'Hard' ? 'red' : 'blue') },
      { key: 'rule_code', label: 'Rule', render: (r) => h('span', { class: 'mono', text: r.rule_code || '—' }) },
      { key: 'penalty_weight', label: 'Weight', num: true },
      { key: 'is_enabled', label: 'Enabled', render: (r) => statusPill(r.is_enabled ? 'Active' : 'Inactive') },
      { key: 'is_mandatory', label: 'Mandatory', render: (r) => (r.is_mandatory ? 'Yes' : 'No') },
      actionsCol({ rowActions: rowsActionProxy('policies') }),
    ],
    fields: () => [
      { name: 'policy_name', label: 'Policy name', full: true },
      { name: 'constraint_type', label: 'Type', type: 'select', options: ['Hard', 'Soft'] },
      { name: 'penalty_weight', label: 'Penalty weight', type: 'number', step: '0.5', min: 0 },
      { name: 'description', label: 'Description', type: 'textarea', full: true },
      { name: 'is_mandatory', label: 'Mandatory', type: 'checkbox', checkLabel: 'Mandatory hard constraint' },
      { name: 'is_enabled', label: 'Enabled', type: 'checkbox', checkLabel: 'Enabled in scheduling runs' },
    ],
  }));

  /* ---------------------------------------------------------------- calendar */
  route({
    id: 'calendar',
    title: 'Examination Calendar',
    render: async (view) => {
      view.appendChild(pageHead('Examination Calendar', 'Examination period, sessions and what is currently placed in each slot.',
        [h('button', { class: 'btn secondary', onclick: () => navigate('time-slots') }, 'Manage time slots'),
          h('button', { class: 'btn', onclick: () => navigate('generator') }, icon('spark', 15), 'Generate timetable')]));
      view.appendChild(loadingBlock('Loading calendar'));
      let slots, report;
      try {
        const slotData = await api('/api/time-slots?page_size=200');
        slots = slotData.items;
        const run = await api('/api/runs?page_size=1');
        report = run.items.length ? await api(`/api/reports/timetable?run_id=${run.items[0].id}`) : { rows: [] };
      } catch (err) {
        view.innerHTML = '';
        view.appendChild(h('div', { class: 'alert err', text: err.message }));
        return;
      }
      view.innerHTML = '';
      view.appendChild(pageHead('Examination Calendar', 'Examination period, sessions and what is currently placed in each slot.',
        [h('button', { class: 'btn secondary', onclick: () => navigate('time-slots') }, 'Manage time slots'),
          h('button', { class: 'btn', onclick: () => navigate('generator') }, icon('spark', 15), 'Generate timetable')]));

      const byDate = {};
      for (const slot of slots) {
        byDate[slot.examination_date] = byDate[slot.examination_date] || [];
        byDate[slot.examination_date].push(slot);
      }
      const examBySlot = {};
      for (const row of report.rows || []) {
        const key = `${row.examination_date}|${row.start_time}`;
        (examBySlot[key] = examBySlot[key] || []).push(row);
      }
      const dates = Object.keys(byDate).sort();
      if (!dates.length) {
        view.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'No time slots configured' }), h('div', { class: 'tiny', text: 'Add slots to define the examination period.' })));
        return;
      }
      for (const date of dates) {
        const daySlot = byDate[date].sort((a, b) => a.start_time.localeCompare(b.start_time));
        const total = daySlot.reduce((sum, s) => sum + (examBySlot[`${date}|${s.start_time}`] || []).length, 0);
        view.appendChild(h('div', { class: 'day-block' },
          h('div', { class: 'day-head' }, h('span', { text: fmtDate(date, true) }),
            h('span', { class: 'muted', text: `${daySlot.length} session(s) · ${total} examination(s)` })),
          ...daySlot.map((slot) => {
            const items = examBySlot[`${date}|${slot.start_time}`] || [];
            return h('div', { class: 'slot-line' },
              h('div', { class: 'slot-time' }, h('div', { text: `${slot.start_time}–${slot.end_time}` }), h('div', { class: 'tiny muted', text: slot.session })),
              items.length
                ? h('div', { class: 'slot-items' }, ...items.map((it) => h('div', { class: `exam-chip pri-${it.priority || 'Medium'}` },
                  h('b', { text: `${it.subject_code} · ${it.subject_name}` }),
                  h('small', { text: `${it.school_code} · ${it.room_number || 'no room'} · ${it.required_seating_capacity} students` }))))
                : h('div', { class: 'tiny muted', text: 'No examination scheduled in this session.' }));
          })));
      }
    },
  });

  /* ----------------------------------------------------------- notifications */
  route({
    id: 'notifications',
    title: 'Notifications',
    render: async (view) => {
      const box = h('div', null);
      const head = pageHead('Notifications', 'Workflow events for your account: generations, approvals, publications and conflict changes.',
        [h('button', {
          class: 'btn secondary', text: 'Mark all read',
          onclick: async () => {
            try { await api('/api/notifications/read-all', { method: 'POST' }); await load(); } catch (err) { toast(err.message, 'err'); }
          },
        })]);
      view.appendChild(head);
      view.appendChild(box);

      async function load() {
        box.innerHTML = '';
        box.appendChild(loadingBlock('Loading notifications'));
        try {
          const data = await api('/api/notifications?page_size=60');
          box.innerHTML = '';
          if (!data.items.length) {
            box.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'Nothing yet' }), h('div', { class: 'tiny', text: 'Notifications appear after scheduling activity.' })));
            return;
          }
          box.appendChild(h('div', { class: 'split-list' }, ...data.items.map((n) => h('div', { class: 'list-item', style: n.is_read ? 'opacity:.72' : 'border-left:3px solid var(--primary)' },
            h('div', { class: 'row' }, h('b', { text: n.title }),
              h('span', { class: 'spacer' }),
              h('span', { class: 'tiny muted', text: fmtDateTime(n.created_at) })),
            h('small', { text: n.message }),
            n.is_read ? null : h('button', {
              class: 'link-btn', text: 'Mark read',
              onclick: async () => { await api(`/api/notifications/${n.id}/read`, { method: 'POST' }); await load(); App.refreshUnread(); },
            })))));
          App.refreshUnread();
        } catch (err) {
          box.innerHTML = '';
          box.appendChild(h('div', { class: 'alert err', text: err.message }));
        }
      }
      await load();
    },
  });

  /* --------------------------------------------------------------- audit logs */
  route(resourcePage({
    id: 'audit', resource: 'audit-logs', singular: 'Audit entry', title: 'Audit Logs',
    subtitle: 'Immutable record of administrative actions. Read-only for accountability.',
    canCreate: false, canDelete: false,
    searchPlaceholder: 'Search action or details',
    columns: () => [
      { key: 'timestamp', label: 'When', render: (r) => fmtDateTime(r.timestamp) },
      { key: 'action', label: 'Action' },
      { key: 'entity_type', label: 'Entity' },
      { key: 'details', label: 'Details', render: (r) => h('span', { class: 'tiny', text: r.details || '—' }) },
    ],
    filters: () => [{ name: 'entity_type', label: 'All entities', options: ['scheduling_run', 'examinations', 'rooms', 'schools', 'invigilators', 'user'] }],
    fields: () => [],
  }));

  /* ------------------------------------------------------------ user management */
  route(resourcePage({
    id: 'users', resource: 'users', singular: 'User', title: 'User Management',
    subtitle: 'Accounts and roles. Only a Super Administrator can manage users.',
    searchPlaceholder: 'Search name, email or role',
    columns: () => [
      { key: 'full_name', label: 'Name' },
      { key: 'email', label: 'Email' },
      { key: 'role', label: 'Role', render: (r) => pill(r.role, r.role === 'Super Admin' ? 'blue' : r.role === 'School Admin' ? 'green' : 'grey') },
      { key: 'school_id', label: 'School', render: (r) => (r.school_id ? schoolName(r.school_id) : 'All schools') },
      { key: 'is_active', label: 'Active', render: (r) => statusPill(r.is_active ? 'Active' : 'Inactive') },
      actionsCol({ rowActions: rowsActionProxy('users') }),
    ],
    filters: () => [{ name: 'role', label: 'All roles', options: meta().roles }],
    fields: (record) => [
      { name: 'full_name', label: 'Full name' },
      { name: 'email', label: 'Email', type: 'email' },
      { name: 'role', label: 'Role', type: 'select', options: meta().roles },
      { name: 'school_id', label: 'School', type: 'select', options: [{ value: '', label: 'All schools (Super Admin)' }, ...optSchools()] },
      { name: 'department_id', label: 'Department', type: 'select', options: [{ value: '', label: 'None' }, ...optDepts()] },
      { name: 'password', label: record ? 'Reset password' : 'Temporary password', type: 'password', help: record ? 'Leave blank to keep the current password.' : 'Defaults to Examflow@123' },
      { name: 'is_active', label: 'Account active', type: 'checkbox', checkLabel: 'User can sign in' },
    ],
  }));

  /* ---------------------------------------------------------------- my duties */
  route({
    id: 'my-duties',
    title: 'My Duties',
    render: async (view) => {
      view.appendChild(pageHead('My duties', 'Your assigned invigilation duties, workload and availability.'));
      view.appendChild(loadingBlock('Loading your duties'));
      let data;
      try { data = await api('/api/my-duties'); } catch (err) {
        view.innerHTML = '';
        view.appendChild(h('div', { class: 'alert err', text: err.message }));
        return;
      }
      view.innerHTML = '';
      view.appendChild(pageHead('My duties', 'Your assigned invigilation duties, workload and availability.',
        [h('button', { class: 'btn secondary', onclick: () => reportIssue() }, icon('warn', 15), 'Report availability issue')]));

      if (!data.invigilator) {
        view.appendChild(h('div', { class: 'alert warn', text: 'No invigilator profile is linked to your account yet. Ask a school administrator to link your profile.' }));
        return;
      }
      view.appendChild(h('div', { class: 'grid kpi' },
        kpi('Invigilator', data.invigilator.name, data.invigilator.employee_code),
        kpi('Total duties', data.workload.total, `Limit ${data.workload.maximum_total}`),
        kpi('Duty days', data.workload.days, `Max ${data.workload.maximum_daily} per day`),
        kpi('School', schoolName(data.invigilator.school_id), data.invigilator.qualification || '')));

      view.appendChild(h('div', { class: 'mt16' }, card('Duty schedule',
        dataTable({
          columns: [
            { key: 'examination_date', label: 'Date', render: (r) => fmtDate(r.examination_date, true) },
            { key: 'start_time', label: 'Time', render: (r) => `${r.start_time}–${r.end_time}` },
            { key: 'subject_code', label: 'Code' },
            { key: 'subject_name', label: 'Examination' },
            { key: 'school_name', label: 'School' },
            { key: 'room_number', label: 'Room' },
          ], rows: data.duties, empty: 'No duties assigned yet.',
        }))));

      view.appendChild(h('div', { class: 'mt16' }, card('Declared availability',
        dataTable({
          columns: [
            { key: 'date', label: 'Date', render: (r) => fmtDate(r.date, true) },
            { key: 'start_time', label: 'From' },
            { key: 'end_time', label: 'To' },
            { key: 'availability_status', label: 'Status', render: (r) => statusPill(r.availability_status) },
            { key: 'reason', label: 'Reason' },
          ], rows: data.availability, empty: 'No restrictions declared.',
        }))));

      function reportIssue() {
        const date = inputEl({ type: 'date' });
        const reason = inputEl({ placeholder: 'e.g. medical appointment' });
        const start = inputEl({ type: 'time', value: '09:00' });
        const end = inputEl({ type: 'time', value: '17:00' });
        const body = h('div', null,
          h('div', { class: 'alert info', style: 'margin-bottom:12px', text: 'Reported issues are stored as unavailability and notify your school administrator.' }),
          field('Date', date), h('div', { class: 'grid two' }, field('From', start), field('To', end)), field('Reason', reason));
        const save = h('button', { class: 'btn', text: 'Submit report' });
        const m = modal({ title: 'Report an availability issue', body, footer: [h('button', { class: 'btn secondary', text: 'Cancel', onclick: () => m.close() }), save] });
        save.addEventListener('click', async () => {
          try {
            await api('/api/my-duties/report-issue', { method: 'POST', body: { date: date.value, start_time: start.value, end_time: end.value, reason: reason.value } });
            m.close();
            toast('Reported. Your administrator has been notified.', 'ok');
            App.renderRoute();
          } catch (err) { toast(err.message, 'err'); }
        });
      }
    },
  });

  /* ----------------------------------------------------------------- settings */
  route({
    id: 'settings',
    title: 'Settings',
    render: async (view) => {
      const user = App.state.user;
      const m = meta();
      let dash = {};
      try { dash = await api('/api/dashboard'); } catch (err) { /* ignore */ }
      view.appendChild(pageHead('Settings', 'Account, engine configuration and deployment information.'));
      view.appendChild(h('div', { class: 'grid two' },
        card('Your account', h('dl', { class: 'kv' },
          h('dt', { text: 'Name' }), h('dd', { text: user.full_name }),
          h('dt', { text: 'Email' }), h('dd', { text: user.email }),
          h('dt', { text: 'Role' }), h('dd', { text: user.role }),
          h('dt', { text: 'School' }), h('dd', { text: user.school_id ? schoolName(user.school_id) : 'All schools' }),
          h('dt', { text: 'Session' }), h('dd', { text: '2026-27' }))),
        card('Scheduling engine', h('div', null,
          h('dl', { class: 'kv' },
            h('dt', { text: 'Search' }), h('dd', { text: 'Backtracking with MRV, degree heuristic, LCV' }),
            h('dt', { text: 'Propagation' }), h('dd', { text: 'Forward checking + constraint propagation' }),
            h('dt', { text: 'Baseline' }), h('dd', { text: 'Deterministic First-Fit greedy' }),
            h('dt', { text: 'Invigilators' }), h('dd', { text: '1 per 75 candidates, minimum 1, maximum 2' }),
            h('dt', { text: 'Fairness score' }), h('dd', { text: '100 × (1 − SD / max(mean, 1)), clamped 0–100' })),
          h('div', { class: 'alert info mt12', text: m.cpsat.note })))));

      view.appendChild(h('div', { class: 'grid two mt16' },
        card('Data in this workspace', h('div', { class: 'grid two' },
          kpi('Schools', dash.counts?.schools || 0), kpi('Examinations', dash.counts?.examinations || 0),
          kpi('Rooms', dash.counts?.rooms || 0), kpi('Invigilators', dash.counts?.invigilators || 0))),
        card('Demonstration data', h('div', null,
          h('p', { class: 'small muted', text: 'Every school, faculty member and student group in this build is fictional demonstration data, seeded so the conflict detection and optimisation behaviour can be exercised.' }),
          h('div', { class: 'mt12 row wrap' },
            h('button', { class: 'btn secondary sm', text: 'Review policies', onclick: () => navigate('policies') }),
            h('button', { class: 'btn secondary sm', text: 'Review audit log', onclick: () => navigate('audit') }))))));

      view.appendChild(h('div', { class: 'mt16' }, card('Session',
        h('div', { class: 'row wrap' },
          h('button', { class: 'btn secondary', text: 'Sign out', onclick: () => App.logout(true) }),
          h('span', { class: 'tiny muted', text: 'Signing out clears the stored token on this device.' })))));
    },
  });

  App.pagesReady = true;
})();
