/* ExamFlow AI · reports and analytics */
(function () {
  const {
    h, api, toast, select, inputEl, dataTable, pill, card, pageHead, loadingBlock, downloadFile,
    toCsv, route, navigate, fmtDate, fmtNum, schoolName, icon, statusPill,
  } = App;

  const TYPES = [
    ['timetable', 'Complete examination timetable', 'Every scheduled examination with room, slot and invigilators.'],
    ['school', 'School-wise examination report', 'The same timetable grouped for a single school.'],
    ['invigilator', 'Invigilator duty report', 'Duties per faculty member with dates.'],
    ['room', 'Room utilisation report', 'Bookings and seat utilisation per room.'],
    ['group', 'Student group examination report', 'Examinations by cohort.'],
    ['conflict', 'Conflict report', 'All conflicts recorded for the run with suggested fixes.'],
    ['fairness', 'Fairness report', 'Duty distribution per invigilator.'],
    ['comparison', 'AI vs First-Fit comparison', 'Metric-by-metric comparison of the two algorithms.'],
    ['performance', 'Scheduling performance report', 'Recent solver runs with status and timings.'],
  ];

  route({
    id: 'reports',
    title: 'Reports & Analytics',
    render: async (view, params) => {
      const state = { kind: params.kind || 'timetable', school_id: '', run_id: '' };
      view.appendChild(pageHead('Reports & Analytics', 'Operational reports generated from stored scheduling data. Export as CSV or print.',
        [h('button', { class: 'btn secondary', onclick: () => window.print() }, icon('print', 15), 'Print view')]));

      const toolbar = h('div', { class: 'toolbar' });
      const content = h('div', null);
      view.appendChild(h('div', { class: 'card tight' }, toolbar));
      view.appendChild(h('div', { class: 'mt12' }, content));

      let runs = [];
      try {
        const data = await api('/api/runs?page_size=40');
        runs = data.items;
      } catch (err) { runs = []; }

      async function load() {
        toolbar.innerHTML = '';
        const typeSel = select(TYPES.map(([key, label]) => ({ value: key, label })), { value: state.kind, style: 'max-width:290px' });
        typeSel.addEventListener('change', () => { state.kind = typeSel.value; state.run_id = ''; load(); });
        toolbar.appendChild(typeSel);

        const schoolSel = select([{ value: '', label: 'All schools' },
          ...App.state.meta.schools.map((s) => ({ value: s.id, label: s.school_name }))], { value: state.school_id, style: 'max-width:190px' });
        schoolSel.addEventListener('change', () => { state.school_id = schoolSel.value; load(); });
        toolbar.appendChild(schoolSel);

        if (!['comparison', 'performance'].includes(state.kind) && runs.length) {
          const runSel = select([{ value: '', label: 'Latest run' },
            ...runs.map((r) => ({ value: r.id, label: `${r.run_name} · ${fmtDate(r.created_at)}` }))], { value: state.run_id, style: 'max-width:260px' });
          runSel.addEventListener('change', () => { state.run_id = runSel.value; load(); });
          toolbar.appendChild(runSel);
        }

        toolbar.appendChild(h('span', { class: 'spacer' }));
        toolbar.appendChild(h('button', {
          class: 'btn secondary sm', onclick: exportCsv,
        }, icon('download', 14), 'Download CSV'));

        content.innerHTML = '';
        content.appendChild(loadingBlock('Building report'));
        const query = new URLSearchParams();
        if (state.school_id) query.set('school_id', state.school_id);
        if (state.run_id) query.set('run_id', state.run_id);
        try {
          const report = await api(`/api/reports/${state.kind}?${query}`);
          content.innerHTML = '';
          const selectedType = TYPES.find(([key]) => key === state.kind);
          content.appendChild(h('div', { class: 'row', style: 'margin-bottom:10px' },
            h('div', null,
              h('h2', { text: report.title || selectedType[1] }),
              h('div', { class: 'tiny muted', text: selectedType[2] })),
            h('span', { class: 'spacer' }),
            pill(`${report.count} row${report.count === 1 ? '' : 's'}`, 'blue')));

          if (report.summary) {
            content.appendChild(h('div', { class: 'grid kpi', style: 'margin-bottom:14px' },
              Object.entries(report.summary).slice(0, 8).map(([key, value]) =>
                h('div', { class: 'kpi-card' },
                  h('div', { class: 'label', text: key.replace(/_/g, ' ') }),
                  h('div', { class: 'value', text: fmtNum(value, 2) })))));
          }

          const columns = (report.columns || []).map(([key, label]) => ({
            key, label,
            num: typeof report.rows[0]?.[key] === 'number',
            render: (row) => {
              const value = row[key];
              if (key === 'examination_date' || key === 'timestamp' || key === 'created_at') return fmtDate(value, true);
              if (key === 'severity' || key === 'status' || key === 'resolution_status' || key === 'solver_status') return statusPill(value);
              if (key === 'priority') return statusPill(value);
              if (key === 'school_code' || key === 'school_id') return schoolCode(value);
              return typeof value === 'number' ? fmtNum(value, 2) : (value === null || value === undefined || value === '' ? '—' : String(value));
            },
          }));
          content.appendChild(dataTable({ columns, rows: report.rows, empty: 'This report has no rows for the current filters.' }));
        } catch (err) {
          content.innerHTML = '';
          content.appendChild(h('div', { class: 'alert warn', text: err.message }));
        }
      }

      function schoolCode(value) {
        const school = App.state.meta.schools.find((s) => s.id === value || s.school_code === value);
        return school ? (school.school_code || school.school_name) : (value || '—');
      }

      function exportCsv() {
        const query = new URLSearchParams();
        if (state.school_id) query.set('school_id', state.school_id);
        if (state.run_id) query.set('run_id', state.run_id);
        window.open(`/api/reports/${state.kind}.csv?${query}`, '_blank');
        toast('CSV download started.', 'ok');
      }

      await load();

      /* analytics strip */
      try {
        const dash = await api('/api/dashboard');
        const strip = h('div', { class: 'mt24' },
          h('h2', { style: 'margin-bottom:10px', text: 'Operational analytics' }),
          h('div', { class: 'grid two' },
            card('Examinations by school', h('div', { html: App.chartBar(dash.exams_by_school, { height: 180 }) })),
            card('Duties per invigilator', dash.workload.length
              ? App.barList(dash.workload.slice(0, 8))
              : h('div', { class: 'empty', text: 'No duties allocated yet.' }))),
          h('div', { class: 'grid two mt16' },
            card('Daily examination load', dash.daily.length
              ? h('div', { html: App.chartLine(dash.daily.map((d) => ({ label: String(d.label), value: d.value })), { height: 180 }) })
              : h('div', { class: 'empty', text: 'Generate a timetable first.' })),
            card('Scheduling health', h('dl', { class: 'kv' },
              h('dt', { text: 'Scheduled examinations' }), h('dd', { text: dash.counts.scheduled }),
              h('dt', { text: 'Pending examinations' }), h('dd', { text: dash.counts.pending }),
              h('dt', { text: 'Open conflicts' }), h('dd', { text: dash.counts.conflicts }),
              h('dt', { text: 'Runs executed' }), h('dd', { text: dash.counts.runs }),
              h('dt', { text: 'Published timetables' }), h('dd', { text: dash.counts.published })))));
        view.appendChild(strip);
      } catch (err) { /* analytics is optional */ }
    },
  });

  App.reportsReady = true;
})();
