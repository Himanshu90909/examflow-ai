/* ExamFlow AI · core: state, API client, router, UI primitives, charts */
(function () {
  const ICONS = {
    dashboard: 'M3 13h8V3H3v10zm10 8h8V11h-8v10zM3 21h8v-6H3v6zM13 3v6h8V3h-8z',
    school: 'M12 3 2 8l10 5 10-5-10-5zm-6 8v5l6 3 6-3v-5',
    layers: 'M12 3 2 8l10 5 10-5-10-5zM2 14l10 5 10-5',
    users: 'M17 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9.5 7a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM22 21v-2a4 4 0 0 0-3-3.87',
    file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM14 2v6h6',
    calendar: 'M3 5h18v16H3V5zm5-3v4m8-4v4M3 11h18',
    door: 'M4 21h16M6 21V4h12v17M10 12h1',
    badgem: 'M12 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM8 21l4-2 4 2',
    clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 5v5l3 2',
    shield: 'M12 2 4 5v6c0 5 3.5 9 8 11 4.5-2 8-6 8-11V5l-8-3z',
    spark: 'M12 3v4m0 10v4M3 12h4m10 0h4M5.6 5.6l2.8 2.8m7.2 7.2 2.8 2.8m0-12.8-2.8 2.8M8.4 15.6l-2.8 2.8',
    grid: 'M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z',
    warn: 'M12 3 2 20h20L12 3zm0 6v5m0 3v.5',
    scale: 'M12 3v18M6 7l-4 8h8L6 7zm12 0-4 8h8l-4-8z',
    chart: 'M4 20V10m6 10V4m6 16v-7',
    history: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5',
    user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1',
    gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 0 0-1.7-1L14.5 3h-4l-.4 2.1a7 7 0 0 0-1.7 1l-2.3-1-2 3.4L6 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 1.7 1l.4 2.1h4l.4-2.1a7 7 0 0 0 1.7-1l2.3 1 2-3.4L19 13z',
    bell: 'M18 21H6m12-4V11a6 6 0 1 0-12 0v6l-2 3h16l-2-3z',
    search: 'M21 21l-4.3-4.3M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0z',
    menu: 'M3 6h18M3 12h18M3 18h18',
    download: 'M12 3v12m0 0-4-4m4 4 4-4M4 21h16',
    print: 'M6 9V3h12v6M6 18H4v-6h16v6h-2M8 21h8v-6H8v6z',
    refresh: 'M20 11a8 8 0 1 0-2 6.3M20 5v6h-6',
    check: 'M4 12l5 5L20 6',
  };

  const NAV = [
    ['Overview', [
      { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', role: ['Super Admin', 'School Admin', 'Invigilator'] },
      { id: 'my-exams', label: 'My Exams', icon: 'file', role: ['Student'] },
    ]],
    ['Institution', [
      { id: 'schools', label: 'Schools', icon: 'school', role: ['Super Admin'] },
      { id: 'departments', label: 'Departments', icon: 'layers', role: ['Super Admin', 'School Admin'] },
      { id: 'student-groups', label: 'Student Groups', icon: 'users', role: ['Super Admin', 'School Admin'] },
      { id: 'examinations', label: 'Examinations', icon: 'file', role: ['Super Admin', 'School Admin'] },
      { id: 'calendar', label: 'Examination Calendar', icon: 'calendar', role: ['Super Admin', 'School Admin'] },
    ]],
    ['Resources', [
      { id: 'rooms', label: 'Rooms Management', icon: 'door', role: ['Super Admin', 'School Admin'] },
      { id: 'invigilators', label: 'Invigilators', icon: 'badgem', role: ['Super Admin', 'School Admin'] },
      { id: 'availability', label: 'Faculty Availability', icon: 'clock', role: ['Super Admin', 'School Admin'] },
      { id: 'time-slots', label: 'Time Slots', icon: 'clock', role: ['Super Admin', 'School Admin'] },
      { id: 'policies', label: 'Constraints & Policies', icon: 'shield', role: ['Super Admin', 'School Admin'] },
    ]],
    ['Scheduling', [
      { id: 'generator', label: 'AI Timetable Generator', icon: 'spark', role: ['Super Admin', 'School Admin'] },
      { id: 'timetable', label: 'Generated Timetable', icon: 'grid', role: ['Super Admin', 'School Admin', 'Invigilator'] },
      { id: 'conflicts', label: 'Conflict Management', icon: 'warn', role: ['Super Admin', 'School Admin'] },
      { id: 'fairness', label: 'Fairness Analysis', icon: 'scale', role: ['Super Admin', 'School Admin'] },
      { id: 'comparison', label: 'Algorithm Comparison', icon: 'chart', role: ['Super Admin', 'School Admin'] },
      { id: 'my-duties', label: 'My Duties', icon: 'badgem', role: ['Invigilator'] },
    ]],
    ['Administration', [
      { id: 'reports', label: 'Reports & Analytics', icon: 'chart', role: ['Super Admin', 'School Admin'] },
      { id: 'notifications', label: 'Notifications', icon: 'bell', role: ['Super Admin', 'School Admin', 'Invigilator'] },
      { id: 'audit', label: 'Audit Logs', icon: 'history', role: ['Super Admin', 'School Admin'] },
      { id: 'users', label: 'User Management', icon: 'user', role: ['Super Admin'] },
      { id: 'settings', label: 'Settings', icon: 'gear', role: ['Super Admin', 'School Admin', 'Invigilator'] },
    ]],
  ];

  const App = {
    state: { token: localStorage.getItem('examflow_token'), user: null, meta: null, unread: 0 },
    routes: {},
    nav: NAV,
    icons: ICONS,
  };

  /* --------------------------------------------------------------- helpers */
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') el.className = value;
        else if (key === 'text') el.textContent = value;
        else if (key === 'html') el.innerHTML = value;
        else if (key === 'style') el.setAttribute('style', value);
        else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
        else if (key === 'dataset') Object.assign(el.dataset, value);
        else if (['checked', 'disabled', 'selected', 'multiple', 'required', 'readOnly'].includes(key)) el[key] = !!value;
        else if (key === 'value') el.value = value;
        else el.setAttribute(key, value);
      }
    }
    for (const child of children.flat(4)) {
      if (child === null || child === undefined || child === false) continue;
      el.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  function icon(name, size = 16) {
    const path = ICONS[name] || ICONS.grid;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', size); svg.setAttribute('height', size);
    svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.7'); svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round'); svg.setAttribute('class', 'ico');
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', path);
    svg.appendChild(p);
    return svg;
  }

  const esc = (v) => String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  function fmtDate(value, withDay) {
    if (!value) return '—';
    const d = new Date(String(value).length <= 10 ? `${value}T00:00:00` : value);
    if (Number.isNaN(d.getTime())) return String(value);
    const base = `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
    return withDay ? `${DAYS[d.getDay()]} ${base}` : base;
  }
  function fmtDateTime(value) {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  const fmtNum = (n, digits = 0) => Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 });

  /* ------------------------------------------------------------------- API */
  async function api(path, options = {}) {
    const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
    if (App.state.token) headers.Authorization = `Bearer ${App.state.token}`;
    const response = await fetch(path.startsWith('/') ? path : `/api/${path}`, {
      method: options.method || 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    if (response.status === 401 || response.status === 403) {
      const data = await response.json().catch(() => ({}));
      if (response.status === 401) { logout(false); }
      throw new Error(data.error || 'You do not have permission for this action.');
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Request failed (${response.status})`);
    }
    if (response.status === 204) return {};
    return response.json();
  }

  /* ----------------------------------------------------------------- toasts */
  function toast(message, kind = 'info', ms = 4200) {
    const node = h('div', { class: `toast ${kind}`, text: message });
    document.getElementById('toasts').appendChild(node);
    setTimeout(() => { node.style.opacity = '0'; node.style.transition = 'opacity .3s'; }, ms);
    setTimeout(() => node.remove(), ms + 320);
  }

  /* ------------------------------------------------------------------ modal */
  function modal({ title, body, footer, wide }) {
    const root = document.getElementById('modal-root');
    const closeX = h('button', { class: 'close-x', 'aria-label': 'Close', text: '×' });
    const box = h('div', { class: `modal ${wide ? 'wide' : ''}` },
      h('div', { class: 'modal-head' }, h('h2', { text: title }), closeX),
      h('div', { class: 'modal-body' }, body),
      footer === null ? null : h('div', { class: 'modal-foot' }, footer || ''));
    const backdrop = h('div', { class: 'modal-backdrop' }, box);
    const close = () => { backdrop.remove(); document.removeEventListener('keydown', onKey); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    closeX.addEventListener('click', close);
    backdrop.addEventListener('mousedown', (e) => { if (e.target === backdrop) close(); });
    document.addEventListener('keydown', onKey);
    root.appendChild(backdrop);
    return { close, box };
  }

  function confirmAction({ title = 'Are you sure?', message, confirmLabel = 'Delete', danger = true }) {
    return new Promise((resolve) => {
      const cancel = h('button', { class: 'btn secondary', text: 'Cancel', onclick: () => { m.close(); resolve(false); } });
      const ok = h('button', { class: `btn ${danger ? 'danger' : ''}`, text: confirmLabel, onclick: () => { m.close(); resolve(true); } });
      const m = modal({
        title,
        body: h('p', { class: 'small', text: message || '' }),
        footer: [cancel, ok],
      });
      ok.focus();
    });
  }

  /* ----------------------------------------------------------------- inputs */
  function field(label, control, help) {
    return h('div', { class: 'field' },
      h('label', { text: label }), control, help ? h('span', { class: 'help', text: help }) : null);
  }

  function select(options, attrs = {}) {
    const el = h('select', Object.assign({ class: 'select' }, attrs));
    for (const opt of options) {
      const value = typeof opt === 'object' ? opt.value : opt;
      const label = typeof opt === 'object' ? opt.label : String(opt);
      el.appendChild(h('option', { value, text: label, selected: attrs.value === value }));
    }
    return el;
  }

  function inputEl(attrs = {}) {
    return h('input', Object.assign({ class: 'input' }, attrs));
  }

  function formModal({ title, fields, values = {}, submitLabel = 'Save', onSubmit, wide, intro }) {
    const getters = {};
    const body = h('div', null);
    if (intro) body.appendChild(h('div', { class: 'alert info mt8', style: 'margin-bottom:14px', text: intro }));
    const grid = h('div', { class: 'grid two' });
    for (const spec of fields) {
      if (spec.type === 'section') {
        body.appendChild(h('h3', { class: 'mt16', style: 'margin-bottom:8px;font-size:13px', text: spec.label }));
        continue;
      }
      const name = spec.name;
      let control;
      const current = values[name] !== undefined && values[name] !== null ? values[name] : (spec.value || '');
      if (spec.type === 'select') {
        const opts = typeof spec.options === 'function' ? spec.options() : spec.options;
        control = select(opts, { value: current });
        if (spec.onChange) control.addEventListener('change', () => spec.onChange(control.value, getters, body));
      } else if (spec.type === 'textarea') {
        control = h('textarea', { class: 'textarea' });
        control.value = current || '';
      } else if (spec.type === 'checkbox') {
        control = h('label', { class: 'check' },
          h('input', { type: 'checkbox', checked: !!current }), h('span', { text: spec.checkLabel || spec.label }));
      } else if (spec.type === 'multi') {
        const opts = typeof spec.options === 'function' ? spec.options() : spec.options;
        const wrapper = h('div', { class: 'check-grid', style: 'max-height:190px;overflow:auto;padding:2px' });
        const chosen = new Set(Array.isArray(current) ? current : (current ? String(current).split(',') : []));
        for (const opt of opts) {
          const cb = h('input', { type: 'checkbox', value: opt.value, checked: chosen.has(opt.value) });
          cb.addEventListener('change', () => { cb.checked ? chosen.add(opt.value) : chosen.delete(opt.value); });
          wrapper.appendChild(h('label', { class: 'check' }, cb, h('span', { text: opt.label })));
        }
        control = wrapper;
        getters[name] = () => Array.from(chosen);
        body.appendChild(h('div', { class: 'field', style: 'grid-column:1/-1' }, h('label', { text: spec.label }), wrapper,
          spec.help ? h('span', { class: 'help', text: spec.help }) : null));
        continue;
      } else if (spec.type === 'static') {
        control = h('div', { class: 'small muted', text: current || spec.help || '' });
      } else {
        control = inputEl({ type: spec.type || 'text', value: current, placeholder: spec.placeholder || '', step: spec.step, min: spec.min, max: spec.max });
      }
      if (!getters[name]) {
        getters[name] = () => {
          if (spec.type === 'checkbox') return control.querySelector('input').checked ? 1 : 0;
          if (spec.type === 'number') return control.value === '' ? null : Number(control.value);
          return control.value;
        };
      }
      const node = spec.type === 'checkbox'
        ? h('div', { class: 'field', style: 'grid-column:1/-1' }, control)
        : field(spec.label, control, spec.help);
      node.dataset.name = name;
      if (spec.full) node.style.gridColumn = '1/-1';
      grid.appendChild(node);
      if (spec.type === 'select' && spec.onChange) {
        control.dataset.dependent = '1';
      }
    }
    body.appendChild(grid);

    const submit = h('button', { class: 'btn', text: submitLabel });
    const cancel = h('button', { class: 'btn secondary', text: 'Cancel' });
    const m = modal({ title, body, wide, footer: [cancel, submit] });
    cancel.addEventListener('click', m.close);
    submit.addEventListener('click', async () => {
      const payload = {};
      for (const [name, get] of Object.entries(getters)) payload[name] = get();
      submit.disabled = true;
      const original = submit.textContent;
      submit.innerHTML = '<span class="spinner"></span> Saving';
      try {
        await onSubmit(payload);
        m.close();
      } catch (err) {
        toast(err.message, 'err');
        submit.disabled = false;
        submit.textContent = original;
      }
    });
    return m;
  }

  /* ------------------------------------------------------------------ table */
  function dataTable({ columns, rows, empty = 'Nothing to show yet.', rowClass }) {
    if (!rows || !rows.length) {
      return h('div', { class: 'empty' }, h('strong', { text: empty }), h('div', { class: 'tiny', text: 'Adjust filters or add a new record.' }));
    }
    const thead = h('thead', null, h('tr', null, ...columns.map((c) => h('th', { class: c.num ? 'num' : '', text: c.label }))));
    const tbody = h('tbody', null, ...rows.map((row) => h('tr', { class: rowClass ? rowClass(row) : '' },
      ...columns.map((c) => {
        const value = c.render ? c.render(row) : row[c.key];
        return h('td', { class: c.num ? 'num' : '' }, value instanceof Node ? value : String(value === null || value === undefined || value === '' ? '—' : value));
      }))));
    return h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, thead, tbody));
  }

  function pill(label, tone = 'grey') {
    return h('span', { class: `pill ${tone}`, text: label });
  }

  function statusPill(status) {
    const map = {
      'FEASIBLE_BUT_NOT_PROVEN_OPTIMAL': ['green', 'Feasible (not proven optimal)'],
      FEASIBLE: ['green', 'Feasible'], INFEASIBLE: ['red', 'Infeasible'],
      TIME_LIMIT_REACHED: ['amber', 'Time limit reached'], UNKNOWN: ['grey', 'Unknown'],
      Scheduled: ['green', 'Scheduled'], Pending: ['amber', 'Pending'], Published: ['green', 'Published'],
      Approved: ['blue', 'Approved'], Completed: ['blue', 'Completed'], Active: ['green', 'Active'],
      Inactive: ['grey', 'Inactive'], Cancelled: ['red', 'Cancelled'], Critical: ['red', 'Critical'],
      High: ['amber', 'High'], Medium: ['blue', 'Medium'], Low: ['grey', 'Low'],
      Open: ['red', 'Open'], Resolved: ['green', 'Resolved'], Leave: ['red', 'Leave'],
      Unavailable: ['amber', 'Unavailable'], Available: ['green', 'Available'],
      Understaffed: ['amber', 'Understaffed'], 'Manually rescheduled': ['blue', 'Rescheduled'],
      'On Leave': ['red', 'On leave'],
    };
    const [tone, label] = map[status] || ['grey', status || '—'];
    return pill(label, tone);
  }

  /* ----------------------------------------------------------------- charts */
  function chartBar(data, opts = {}) {
    const width = 640, height = opts.height || 200, pad = { t: 14, r: 10, b: 30, l: 34 };
    const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));
    const innerW = width - pad.l - pad.r, innerH = height - pad.t - pad.b;
    const barW = Math.max(6, (innerW / Math.max(data.length, 1)) * 0.58);
    const step = innerW / Math.max(data.length, 1);
    const color = opts.color || '#2563eb';
    const ticks = 4;
    let svg = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(opts.label || 'Bar chart')}" preserveAspectRatio="none">`;
    for (let i = 0; i <= ticks; i += 1) {
      const y = pad.t + innerH - (innerH * i / ticks);
      svg += `<line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="#eef2f7"/>`;
      svg += `<text x="${pad.l - 6}" y="${y + 3}" font-size="9.5" fill="#94a3b8" text-anchor="end">${Math.round(max * i / ticks)}</text>`;
    }
    data.forEach((d, i) => {
      const value = Number(d.value) || 0;
      const barH = (value / max) * innerH;
      const x = pad.l + i * step + (step - barW) / 2;
      const y = pad.t + innerH - barH;
      const fill = d.color || color;
      svg += `<rect x="${x}" y="${y}" width="${barW}" height="${Math.max(barH, 1)}" rx="4" fill="${fill}"><title>${esc(d.label)}: ${value}</title></rect>`;
      svg += `<text x="${x + barW / 2}" y="${height - 10}" font-size="9.5" fill="#64748b" text-anchor="middle">${esc(String(d.label).slice(0, 12))}</text>`;
      if (value) svg += `<text x="${x + barW / 2}" y="${y - 4}" font-size="9.5" fill="#475569" text-anchor="middle">${value}</text>`;
    });
    return `${svg}</svg>`;
  }

  function chartLine(data, opts = {}) {
    const width = 640, height = opts.height || 190, pad = { t: 14, r: 12, b: 28, l: 32 };
    const max = Math.max(1, ...data.map((d) => Number(d.value) || 0));
    const innerW = width - pad.l - pad.r, innerH = height - pad.t - pad.b;
    const step = innerW / Math.max(data.length - 1, 1);
    const points = data.map((d, i) => {
      const x = pad.l + i * step;
      const y = pad.t + innerH - ((Number(d.value) || 0) / max) * innerH;
      return [x, y];
    });
    let svg = `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(opts.label || 'Trend')}" preserveAspectRatio="none">`;
    for (let i = 0; i <= 3; i += 1) {
      const y = pad.t + innerH - (innerH * i / 3);
      svg += `<line x1="${pad.l}" y1="${y}" x2="${width - pad.r}" y2="${y}" stroke="#eef2f7"/>`;
      svg += `<text x="${pad.l - 6}" y="${y + 3}" font-size="9.5" fill="#94a3b8" text-anchor="end">${Math.round(max * i / 3)}</text>`;
    }
    const path = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    svg += `<path d="${path}" fill="none" stroke="${opts.color || '#2563eb'}" stroke-width="2.2" stroke-linejoin="round"/>`;
    points.forEach(([x, y], i) => {
      svg += `<circle cx="${x}" cy="${y}" r="3.4" fill="#fff" stroke="${opts.color || '#2563eb'}" stroke-width="2"><title>${esc(data[i].label)}: ${data[i].value}</title></circle>`;
      svg += `<text x="${x}" y="${height - 8}" font-size="9.5" fill="#64748b" text-anchor="middle">${esc(String(data[i].label).slice(5, 11))}</text>`;
    });
    return `${svg}</svg>`;
  }

  function chartDonut(data, opts = {}) {
    const size = opts.size || 168, r = size / 2 - 12, cx = size / 2, cy = size / 2;
    const total = data.reduce((sum, d) => sum + (Number(d.value) || 0), 0) || 1;
    const colors = opts.colors || ['#2563eb', '#0ea5e9', '#16a34a', '#f59e0b', '#dc2626', '#8b5cf6'];
    let angle = -Math.PI / 2, svg = `<svg class="chart" viewBox="0 0 ${size} ${size}" role="img" aria-label="${esc(opts.label || 'Distribution')}">`;
    data.forEach((d, i) => {
      const slice = (Number(d.value) || 0) / total * Math.PI * 2;
      const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
      const x2 = cx + r * Math.cos(angle + slice), y2 = cy + r * Math.sin(angle + slice);
      const large = slice > Math.PI ? 1 : 0;
      if (slice > 0.0001) {
        svg += `<path d="M${cx},${cy} L${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z" fill="${colors[i % colors.length]}" opacity=".92"><title>${esc(d.label)}: ${d.value}</title></path>`;
      }
      angle += slice;
    });
    svg += `<circle cx="${cx}" cy="${cy}" r="${r * 0.58}" fill="#fff"/>`;
    svg += `<text x="${cx}" y="${cy - 2}" text-anchor="middle" font-size="19" font-weight="700" fill="#1e293b">${esc(String(opts.centerValue !== undefined ? opts.centerValue : total))}</text>`;
    svg += `<text x="${cx}" y="${cy + 14}" text-anchor="middle" font-size="9.5" fill="#64748b">${esc(opts.centerLabel || 'total')}</text>`;
    const legend = `<div class="legend">${data.map((d, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(d.label)} · ${d.value}</span>`).join('')}</div>`;
    return `<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap"><div style="width:${size}px;flex:none">${svg}</svg></div><div style="flex:1;min-width:130px">${legend}</div></div>`;
  }

  function barList(rows, opts = {}) {
    const wrap = h('div', null);
    const max = Math.max(1, ...rows.map((r) => Number(r.value) || 0));
    for (const row of rows) {
      const pct = Math.round((Number(row.value) || 0) / max * 100);
      wrap.appendChild(h('div', { class: 'bar-row' },
        h('span', { class: 'truncate', text: row.label, title: row.label }),
        h('div', { class: 'bar-track' },
          h('div', { class: 'bar-fill', style: `width:${pct}%;background:${row.color || opts.color || '#2563eb'}` })),
        h('span', { class: 'mono', style: 'text-align:right', text: fmtNum(row.value, 2) })));
    }
    return wrap;
  }

  function kpi(label, value, foot) {
    return h('div', { class: 'kpi-card' },
      h('div', { class: 'label', text: label }),
      h('div', { class: 'value', text: typeof value === 'number' ? fmtNum(value) : value }),
      foot ? h('div', { class: 'foot', text: foot }) : null);
  }

  function card(title, content, hint) {
    return h('div', { class: 'card' },
      title ? h('div', { class: 'card-head' }, h('h3', { text: title }), hint ? h('span', { class: 'hint', text: hint }) : null) : null,
      content instanceof Node ? content : h('div', { html: content || '' }));
  }

  function pageHead(title, subtitle, actions) {
    return h('div', { class: 'page-head' },
      h('div', null, h('h1', { text: title }), subtitle ? h('div', { class: 'sub', text: subtitle }) : null),
      actions ? h('div', { class: 'actions' }, actions) : null);
  }

  function loadingBlock(text = 'Loading') {
    return h('div', { class: 'card' },
      h('div', { class: 'row', style: 'margin-bottom:10px' }, h('span', { class: 'spinner dark' }), h('span', { class: 'small muted', text })),
      h('div', { class: 'skeleton', style: 'width:92%' }), h('div', { class: 'skeleton', style: 'width:78%' }),
      h('div', { class: 'skeleton', style: 'width:86%' }), h('div', { class: 'skeleton', style: 'width:64%' }));
  }

  /* -------------------------------------------------------------- download */
  function downloadFile(filename, content, mime = 'text/csv;charset=utf-8') {
    const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = h('a', { href: url, download: filename });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1200);
  }

  function toCsv(columns, rows) {
    const head = columns.map((c) => `"${String(c.label || c.key).replace(/"/g, '""')}"`).join(',');
    const body = rows.map((row) => columns.map((c) => {
      const value = c.csv ? c.csv(row) : row[c.key];
      return `"${String(value === null || value === undefined ? '' : value).replace(/"/g, '""')}"`;
    }).join(',')).join('\n');
    return `${head}\n${body}`;
  }

  /* --------------------------------------------------------------- routing */
  function route(def) {
    App.routes[def.id] = def;
  }

  function parseHash() {
    const raw = (location.hash || '#/dashboard').replace(/^#\/?/, '');
    const [id, qs] = raw.split('?');
    const params = {};
    new URLSearchParams(qs || '').forEach((value, key) => { params[key] = value; });
    return { id: id || 'dashboard', params };
  }

  function navigate(id, params) {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    location.hash = `#/${id}${qs}`;
  }

  function visibleNav(role) {
    return NAV.map(([group, items]) => [group, items.filter((i) => !i.role || i.role.includes(role))])
      .filter(([, items]) => items.length);
  }

  /* Branding comes from the server so one build can serve any university. */
  function inst() {
    const published = (App.state.providers && App.state.providers.institution) || {};
    return {
      product: published.product || 'ExamFlow AI',
      name: published.name || 'Lovely Professional University',
      short: published.short || 'LPU',
      office: published.office || 'Division of Examination',
      address: published.address || '',
      phone: published.phone || '',
      email: published.email || '',
      term: published.term || 'Term End Examination',
      session: published.session || '2026-27',
    };
  }

  function buildShell() {
    const root = document.getElementById('root');
    root.innerHTML = '';
    const sidebar = h('aside', { class: 'sidebar', id: 'sidebar' },
      h('div', { class: 'brand' },
        h('div', { class: 'brand-mark', text: inst().short }),
        h('div', null,
          h('div', { class: 'brand-name', text: inst().product }),
          h('div', { class: 'brand-sub', text: inst().name }))),
      h('nav', { class: 'nav', id: 'nav' }),
      h('div', { class: 'sidebar-foot' },
        h('div', { text: 'Academic session ' + inst().session }),
        h('div', { style: 'margin-top:4px', text: inst().office })));

    const searchInput = inputEl({ placeholder: 'Search examinations, rooms, faculty…', 'aria-label': 'Global search' });
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && searchInput.value.trim()) {
        navigate('examinations', { q: searchInput.value.trim() });
      }
    });
    const bell = h('button', { class: 'icon-btn', title: 'Notifications', onclick: () => navigate('notifications') }, icon('bell', 17));
    const dot = h('span', { class: 'dot', style: 'display:none' });
    bell.appendChild(dot);
    App.refreshUnread = async () => {
      try {
        const data = await api('/api/notifications?unread=1&page_size=1');
        const count = data.items.filter((i) => !i.is_read).length ? data.total : 0;
        const res = await api('/api/notifications?page_size=100');
        App.state.unread = res.items.filter((i) => !i.is_read).length;
        dot.style.display = App.state.unread ? 'grid' : 'none';
        dot.textContent = App.state.unread > 9 ? '9+' : String(App.state.unread || '');
      } catch (err) { /* silent */ }
    };

    const topbar = h('header', { class: 'topbar' },
      h('button', { class: 'icon-btn hamburger', 'aria-label': 'Toggle menu', onclick: () => sidebar.classList.toggle('open') }, icon('menu', 18)),
      h('div', { class: 'search' }, icon('search', 15), searchInput),
      h('div', { class: 'topbar-right' },
        h('span', { class: 'chip', text: '2026-27' }),
        bell,
        h('button', { class: 'userbox', onclick: toggleUserMenu },
          h('div', { class: 'avatar', text: initials(App.state.user.full_name) }),
          h('div', { style: 'text-align:left' },
            h('strong', { text: App.state.user.full_name }),
            h('small', { text: App.state.user.role })))));

    const view = h('main', { class: 'view', id: 'view' });
    root.appendChild(h('div', { class: 'shell' }, sidebar, h('div', { class: 'main' }, topbar, view)));
    renderNav();
    App.refreshUnread();
    return view;
  }

  function toggleUserMenu() {
    const menu = modal({
      title: 'Account',
      body: h('div', null,
        h('dl', { class: 'kv' },
          h('dt', { text: 'Name' }), h('dd', { text: App.state.user.full_name }),
          h('dt', { text: 'Email' }), h('dd', { text: App.state.user.email }),
          h('dt', { text: 'Role' }), h('dd', { text: App.state.user.role }),
          h('dt', { text: 'School' }), h('dd', { text: App.state.user.school_id ? schoolName(App.state.user.school_id) : 'All schools' }))),
      footer: [
        h('button', { class: 'btn secondary', text: 'Settings', onclick: () => { menu.close(); navigate('settings'); } }),
        h('button', { class: 'btn danger', text: 'Logout', onclick: () => { menu.close(); logout(true); } }),
      ],
    });
  }

  function initials(name) {
    return String(name || 'U').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
  }

  function schoolName(id) {
    const school = (App.state.meta?.schools || []).find((s) => s.id === id);
    return school ? school.school_name : '—';
  }

  function renderNav() {
    const nav = document.getElementById('nav');
    if (!nav) return;
    const current = parseHash().id;
    nav.innerHTML = '';
    for (const [group, items] of visibleNav(App.state.user.role)) {
      const box = h('div', { class: 'nav-group' }, h('div', { class: 'nav-title', text: group }));
      for (const item of items) {
        const btn = h('button', { class: `nav-link ${current === item.id ? 'active' : ''}`, onclick: () => { navigate(item.id); document.getElementById('sidebar').classList.remove('open'); } },
          icon(item.icon), h('span', { text: item.label }));
        if (item.id === 'notifications' && App.state.unread) btn.appendChild(h('span', { class: 'nav-badge', text: App.state.unread }));
        box.appendChild(btn);
      }
      nav.appendChild(box);
    }
  }

  function navRoles(id) {
    for (const [, items] of NAV) {
      const item = items.find((entry) => entry.id === id);
      if (item) return item.role || null;
    }
    return null;
  }

  function homeRoute() {
    const role = App.state.user && App.state.user.role;
    if (role === 'Invigilator') return 'my-duties';
    if (role === 'Student') return 'my-exams';
    return 'dashboard';
  }

  async function renderRoute() {
    const { id, params } = parseHash();
    const allowed = navRoles(id);
    if (allowed && App.state.user && !allowed.includes(App.state.user.role) && id !== homeRoute()) {
      location.hash = '#/' + homeRoute();
      return;
    }
    const def = App.routes[id] || App.routes.dashboard;
    const view = document.getElementById('view');
    if (!view) return;
    renderNav();
    view.innerHTML = '';
    if (!def) {
      view.appendChild(h('div', { class: 'empty' }, h('strong', { text: 'Page not found' })));
      return;
    }
    document.title = `${def.title} · ${inst().product}`;
    try {
      await def.render(view, params);
    } catch (err) {
      view.appendChild(h('div', { class: 'alert err', text: err.message || 'Unable to load this page.' }));
    }
    window.scrollTo({ top: 0 });
  }

  /* ------------------------------------------------------------------- auth */
  const PORTALS = {
    admin: {
      badge: 'Administrator',
      heading: 'Administrator sign in',
      intro: 'Plan examinations, allocate rooms and invigilators, then publish approved timetables.',
      lead: 'The timetable office, end to end.',
      body: 'Build a conflict-free plan, inspect the solver reasoning and release it only when every hard rule passes.',
      points: ['CSP search with MRV, degree and LCV heuristics',
               'Backtracking with forward checking, never random',
               'Publishing blocked until the rule engine passes'],
      demo: [['Super Admin', 'admin@examflow.ai', 'Admin@123'],
             ['School Admin', 'rita@examflow.ai', 'Examflow@123']],
      otherHref: '#/login/user',
      otherText: 'Invigilator? Open the invigilator portal',
    },
    user: {
      badge: 'Invigilator',
      heading: 'Invigilator sign in',
      intro: 'Check your duty roster and room allocation, and report availability problems to the exam office.',
      lead: 'Your duties, clearly laid out.',
      body: 'Only the duties assigned to you, with room, session and seat count for each examination.',
      points: ['Published duties for your own account only',
               'Room, session and student count for every duty',
               'Report a clash or availability issue in one click'],
      demo: [['Invigilator', 'ananya@examflow.ai', 'Examflow@123']],
      otherHref: '#/login/admin',
      otherText: 'Administrator? Open the admin portal',
    },
    student: {
      key: 'student',
      badge: 'Student',
      heading: 'Student sign in',
      intro: 'See when and where your examinations are held, and which seat block to report to.',
      lead: 'Your examinations, without the guesswork.',
      body: 'Every paper your batch sits, with the date, session and room the examination office has published.',
      demo: [['Student', 'student@examflow.ai', 'Student@123']],
      points: ['Only your own subjects and groups',
               'Date, session, room and seat count for each paper',
               'No access to rosters, invigilation or scheduling'],
      otherHref: '#/login/user',
      otherText: 'Invigilator or staff? Open the staff portals',
    },
  };

  function loginPortal() {
    const hash = location.hash || '';
    if (hash.indexOf('#/login/user') === 0) return 'user';
    if (hash.indexOf('#/login/admin') === 0) return 'admin';
    if (hash.indexOf('#/login/student') === 0) return 'student';
    return 'chooser';
  }

  function brandHead() {
    return h('div', { class: 'brand', style: 'padding:0;border:0' },
      h('div', { class: 'brand-mark', text: inst().short }),
      h('div', null, h('div', { class: 'brand-name', text: inst().name }),
        h('div', { class: 'brand-sub', text: inst().office + ' \u00B7 ' + inst().product })));
  }

  /* The university's own contact block, shown under the sign-in masthead. */
  function institutionFoot() {
    const parts = [inst().address, inst().phone, inst().email].filter(Boolean);
    return h('div', { class: 'inst-foot' },
      h('div', { class: 'inst-term', text: inst().term + ' \u00B7 Session ' + inst().session }),
      parts.length ? h('div', { text: parts.join(' \u00B7 ') }) : null);
  }

  function renderLogin(message) {
    document.title = 'Sign in · ' + inst().short;
    if (loginPortal() === 'chooser') return renderPortalChooser(message);
    return renderPortalLogin(loginPortal(), message);
  }

  function renderPortalChooser(message) {
    const root = document.getElementById('root');
    const err = h('div', { class: 'alert err', style: message ? 'display:flex' : 'display:none', text: message || '' });
    root.innerHTML = '';
    root.appendChild(h('div', { class: 'login' },
      h('div', { class: 'login-aside' },
        brandHead(),
        h('h2', { text: 'Two portals, one examination plan.' }),
        h('p', { text: 'Administrators build and publish the timetable. Invigilators follow their duties. Each portal has its own sign-in page and its own view of the data.' }),
        h('div', { class: 'login-points' },
          point('Separate sign-in pages for administration and staff'),
          point('Role separation enforced on the server, not just the menu'),
          point('Every decision stored for audit')),
        institutionFoot()),
      h('div', { class: 'login-form-wrap' },
        h('div', { class: 'login-form' },
          h('h1', { text: 'Choose your portal' }),
          h('p', { class: 'muted small', style: 'margin-bottom:16px', text: 'Sign in where you belong. Credentials are refused on the wrong portal.' }),
          err,
          h('div', { class: 'portal-grid' },
            portalCard('admin', 'Administrator portal', 'Super Admin · School Admin', 'Plan, validate and publish timetables.'),
            portalCard('user', 'Invigilator portal', 'Invigilator', 'See your duties and report issues.'),
            portalCard('student', 'Student portal', 'Student', 'Check your examination dates and rooms.'))))));
  }

  const GOOGLE_ERRORS = {
    cancelled: 'Google sign-in was cancelled.',
    expired: 'That sign-in attempt expired. Please try again.',
    google: 'Google could not confirm that account. Please try again.',
    no_account: 'No ExamFlow account uses that Google address. Ask the examination office to create one.',
    inactive: 'This account is deactivated. Contact the examination office.',
    wrong_portal: 'That Google account belongs to a different portal. Use the correct sign-in page.',
    not_configured: 'Google sign-in is not configured on this deployment yet.',
  };

  function loadGoogleButton(slot, portal) {
    fetch('/api/auth/providers')
      .then((response) => (response.ok ? response.json() : { google: false }))
      .then((providers) => {
        if (!providers || !providers.google) return;
        const primary = providers.password === false;
        if (!primary) slot.appendChild(h('div', { class: 'auth-divider', text: 'or' }));
        slot.appendChild(h('a', {
          class: 'btn block google-btn' + (primary ? '' : ' ghost'),
          href: '/api/auth/google/start?portal=' + portal,
        }, h('span', { class: 'google-g', text: 'G' }), 'Continue with Google'));
      })
      .catch(() => {});
  }

  /* --------------------------------------------------- branch, course, semester */
  /* A student signs up by narrowing down: LPU school (branch) -> course -> semester.
     The lists come from /api/catalog so the form can never offer a branch the office
     does not recognise. */
  let catalogCache = null;
  function loadCatalog() {
    if (catalogCache) return Promise.resolve(catalogCache);
    return fetch('/api/catalog')
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data && data.schools && data.schools.length) catalogCache = data;
        return catalogCache;
      })
      .catch(() => null);
  }

  function enrolmentBlock(note) {
    const school = select([{ value: '', label: 'Select your branch' }], { disabled: 'disabled' });
    const course = select([{ value: '', label: 'Pick a branch first' }], { disabled: 'disabled' });
    const semester = select([{ value: '', label: 'Pick a course first' }], { disabled: 'disabled' });
    const section = select([{ value: 'A', label: 'Section A' }]);
    const status = h('div', { class: 'small muted', style: 'margin-top:4px', text: '' });
    const node = h('div', { class: 'enrolment' },
      note ? h('div', { class: 'small muted', style: 'margin-bottom:8px', text: note }) : null,
      field('Branch (school)', school),
      field('Course (programme)', course),
      h('div', { class: 'grid two' }, field('Semester', semester), field('Section', section)),
      status);

    const fill = (el, options, placeholder) => {
      el.innerHTML = '';
      el.appendChild(h('option', { value: '', text: placeholder }));
      options.forEach((option) => el.appendChild(
        h('option', { value: option.value, text: option.label })));
    };

    let schools = [];
    loadCatalog().then((data) => {
      if (!data) {
        status.textContent = 'The branch list could not load. Check the connection and try again.';
        return;
      }
      schools = data.schools;
      fill(school, schools.map((s) => ({ value: s.code, label: s.name + ' (' + s.code + ')' })),
        'Select your branch');
      school.disabled = false;
      if (data.sections && data.sections.length) {
        section.innerHTML = '';
        data.sections.forEach((code) => section.appendChild(
          h('option', { value: code, text: 'Section ' + code })));
      }
    });

    school.addEventListener('change', () => {
      const chosen = schools.filter((s) => s.code === school.value)[0];
      course.disabled = !chosen;
      semester.disabled = true;
      fill(course, chosen
        ? chosen.programmes.map((p) => ({ value: p.code, label: p.name + ' (' + p.level + ')' }))
        : [], 'Pick a branch first');
      fill(semester, [], 'Pick a course first');
      status.textContent = chosen ? 'Examinations for ' + chosen.name + '.' : '';
    });

    course.addEventListener('change', () => {
      const chosenSchool = schools.filter((s) => s.code === school.value)[0];
      const chosen = chosenSchool && chosenSchool.programmes
        .filter((p) => p.code === course.value)[0];
      semester.disabled = !chosen;
      fill(semester, chosen
        ? Array.from({ length: chosen.semesters }, (unused, i) => ({ value: String(i + 1), label: 'Semester ' + (i + 1) }))
        : [], 'Pick a course first');
    });

    const read = () => ({
      school: school.value, programme: course.value, semester: semester.value,
      section: section.value,
    });
    const problem = () => {
      if (!school.value) return 'Choose your branch (school).';
      if (!course.value) return 'Choose your course.';
      if (!semester.value) return 'Choose your semester.';
      return '';
    };

    return { node, read, problem };
  }

  function takeGoogleToken() {
    const hash = location.hash || '';
    const marker = '#google_token=';
    if (hash.indexOf(marker) !== 0) return false;
    /* The callback appends where the account belongs when the visitor opened another
       portal's page, so the shell can say why it opened a different workspace. */
    const params = new URLSearchParams(hash.slice(1));
    App.state.token = params.get('google_token') || '';
    App.state.googlePortal = params.get('portal') || null;
    App.state.googleAsked = params.get('asked') || null;
    localStorage.setItem('examflow_token', App.state.token);
    history.replaceState(null, '', location.pathname + location.search + '#/login');
    return true;
  }

  const PORTAL_LABEL = { admin: 'administrator', user: 'invigilator', student: 'student' };

  function announceGooglePortal() {
    const home = App.state.googlePortal;
    const asked = App.state.googleAsked;
    App.state.googlePortal = null;
    App.state.googleAsked = null;
    if (!home || !asked || asked === home) return;
    const role = (App.state.user && App.state.user.role) || '';
    toast('Signed in as ' + (role || PORTAL_LABEL[home]) + '. Your account belongs to the '
          + PORTAL_LABEL[home] + ' portal, so that is where we opened.', 'info', 7000);
  }

  function portalCard(portal, title, subtitle, text) {
    return h('a', { class: 'portal-card ' + portal, href: '#/login/' + portal },
      h('div', { class: 'portal-icon', text: portal === 'admin' ? '\u25C6' : '\u25CF' }),
      h('div', { class: 'portal-copy' },
        h('div', { class: 'portal-title', text: title }),
        h('div', { class: 'portal-sub', text: subtitle }),
        h('div', { class: 'portal-text', text: text })),
      h('span', { class: 'portal-go', text: '\u2192' }));
  }

  /* Email-a-code sign-in: request a 6 digit code, then verify it. */
  function buildCodeFlow(portal, cfg, onDone) {
    const email = inputEl({ type: 'email', placeholder: 'you@university.edu', autocomplete: 'username' });
    const code = inputEl({ type: 'text', placeholder: '6 digit code', autocomplete: 'one-time-code', maxlength: '6' });
    const note = h('div', { class: 'alert info', style: 'display:none;margin-bottom:12px' });
    const error = h('div', { class: 'alert err', style: 'display:none' });
    const sendBtn = h('button', { class: 'btn ghost block', type: 'button', text: 'Email me a sign-in code' });
    const verifyBtn = h('button', { class: 'btn block', type: 'button', style: 'display:none', text: 'Verify and sign in' });
    const codeRow = h('div', { style: 'display:none' }, field('Sign-in code', code), verifyBtn);

    const show = (el, text, kind) => {
      el.className = 'alert ' + (kind || 'info');
      el.textContent = text;
      el.style.display = 'flex';
    };
    const hide = (el) => { el.style.display = 'none'; };

    sendBtn.addEventListener('click', async () => {
      hide(error);
      if (!email.value.trim()) { show(error, 'Enter the email address on your account.', 'err'); return; }
      sendBtn.disabled = true;
      sendBtn.innerHTML = '<span class="spinner"></span> Sending';
      try {
        const data = await api('/api/auth/request-code', {
          method: 'POST',
          body: { email: email.value.trim(), portal: portal },
        });
        hide(error);
        if (data.delivered) {
          show(note, 'If that address belongs to an account here, a 6 digit code is on its way. It expires in 10 minutes.', 'ok');
          codeRow.style.display = '';
          code.focus();
        } else {
          show(note, 'Email delivery is not configured on this deployment yet.', 'warn');
        }
      } catch (err) {
        show(error, err.message, 'err');
      } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Email me a sign-in code';
      }
    });

    verifyBtn.addEventListener('click', async () => {
      hide(error);
      const value = code.value.replace(/\D/g, '');
      if (value.length !== 6) { show(error, 'Enter the 6 digit code from the email.', 'err'); return; }
      verifyBtn.disabled = true;
      verifyBtn.innerHTML = '<span class="spinner"></span> Verifying';
      try {
        const data = await api('/api/auth/verify-code', {
          method: 'POST',
          body: { email: email.value.trim(), code: value, portal: portal },
        });
        App.state.token = data.token;
        App.state.user = data.user;
        localStorage.setItem('examflow_token', data.token);
        await onDone();
      } catch (err) {
        show(error, err.message, 'err');
        verifyBtn.disabled = false;
        verifyBtn.textContent = 'Verify and sign in';
      }
    });

    code.addEventListener('input', () => { code.value = code.value.replace(/\D/g, '').slice(0, 6); });
    code.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); verifyBtn.click(); } });

    return h('div', { class: 'code-flow' },
      h('div', { class: 'portal-badge ' + portal, text: cfg.badge + ' portal' }),
      h('h1', { text: cfg.heading.replace('sign in', 'sign in with a code') }),
      h('p', { class: 'muted small', style: 'margin-bottom:16px',
        text: 'We email a one-time code to the address on your account. No password needed.' }),
      note, error,
      field('Email address', email),
      sendBtn,
      codeRow,
      h('a', { class: 'portal-switch', href: cfg.otherHref, text: cfg.otherText }));
  }

  /* Phone-number sign-in: send a 6 digit code by SMS, then verify it. Students may
     create their account here; staff portals need a number the office already has. */
  function buildPhoneFlow(portal, cfg, onDone) {
    const phone = inputEl({ type: 'tel', placeholder: '90000 00001', autocomplete: 'tel' });
    const code = inputEl({ type: 'text', placeholder: '6 digit code', autocomplete: 'one-time-code', maxlength: '6' });
    const note = h('div', { class: 'alert info', style: 'display:none;margin-bottom:12px' });
    const error = h('div', { class: 'alert err', style: 'display:none' });
    const sendBtn = h('button', { class: 'btn ghost block', type: 'button', text: 'Text me a sign-in code' });
    const verifyBtn = h('button', { class: 'btn block', type: 'button', style: 'display:none', text: 'Verify and sign in' });
    const codeRow = h('div', { style: 'display:none' }, field('Sign-in code', code), verifyBtn);
    const providers = App.state.providers || {};
    /* Optional until we know whether this number is new: the account is created on the
       first code, and that is the moment the branch and course are needed. */
    const enrolment = portal === 'student' ? enrolmentBlock(
      'Signing in for the first time? Choose your branch and course so your account opens '
      + 'with your own timetable.') : null;

    const show = (el, text, kind) => {
      el.className = 'alert ' + (kind || 'info');
      el.textContent = text;
      el.style.display = 'flex';
    };
    const hide = (el) => { el.style.display = 'none'; };

    if (providers.phone_demo) {
      note.className = 'alert warn';
      note.textContent = 'Demonstration mode: no SMS gateway is configured on this deployment, '
        + 'so the code is shown here after you ask for it.';
      note.style.display = 'flex';
    }

    sendBtn.addEventListener('click', async () => {
      hide(error);
      if (!phone.value.trim()) { show(error, 'Enter your phone number.', 'err'); return; }
      sendBtn.disabled = true;
      sendBtn.innerHTML = '<span class="spinner"></span> Sending';
      try {
        const data = await api('/api/auth/request-phone-code', {
          method: 'POST',
          body: { phone: phone.value.trim(), portal: portal },
        });
        hide(error);
        codeRow.style.display = '';
        code.focus();
        if (data.demo_code) {
          code.value = data.demo_code;
          code.select();
          show(note, 'Demonstration code for ' + data.phone + ': ' + data.demo_code
            + '. No text message is sent on this deployment, so it is filled in for you '
            + 'already — press "Verify and sign in". It expires in 10 minutes.', 'warn');
        } else if (data.delivered) {
          show(note, 'A 6 digit code is on its way to ' + data.phone
            + '. It expires in 10 minutes.', 'ok');
        } else {
          show(note, 'SMS delivery is not configured on this deployment yet.', 'warn');
        }
        if (data.hint) {
          show(error, data.hint, 'info');
        }
        if (data.delivery_error) {
          show(error, data.demo_code
            ? 'The SMS gateway is not active on this deployment yet, so the code is filled '
              + 'in below. Gateway said: ' + data.delivery_error
            : 'The SMS could not be sent: ' + data.delivery_error,
          data.demo_code ? 'info' : 'err');
        }
      } catch (err) {
        show(error, err.message, 'err');
      } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Text me a sign-in code';
      }
    });

    verifyBtn.addEventListener('click', async () => {
      hide(error);
      const value = code.value.replace(/\D/g, '');
      if (value.length !== 6) { show(error, 'Enter the 6 digit code from the SMS.', 'err'); return; }
      verifyBtn.disabled = true;
      if (enrolment) {
        const picked = enrolment.read();
        const partial = (picked.school || picked.programme || picked.semester)
          && enrolment.problem();
        if (partial) { show(error, partial, 'err'); return; }
      }
      verifyBtn.innerHTML = '<span class="spinner"></span> Verifying';
      try {
        const body = { phone: phone.value.trim(), code: value, portal: portal };
        if (enrolment) Object.assign(body, enrolment.read());
        const data = await api('/api/auth/verify-phone-code', {
          method: 'POST',
          body: body,
        });
        App.state.token = data.token;
        App.state.user = data.user;
        localStorage.setItem('examflow_token', data.token);
        await onDone();
      } catch (err) {
        show(error, err.message, 'err');
        verifyBtn.disabled = false;
        verifyBtn.textContent = 'Verify and sign in';
      }
    });

    code.addEventListener('input', () => { code.value = code.value.replace(/\D/g, '').slice(0, 6); });
    code.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); verifyBtn.click(); } });

    return h('div', { class: 'code-flow' },
      h('div', { class: 'portal-badge ' + portal, text: cfg.badge + ' portal' }),
      h('h1', { text: cfg.heading.replace('sign in', 'sign in by phone') }),
      h('p', { class: 'muted small', style: 'margin-bottom:16px',
        text: 'We text a one-time code to your number. No password needed.' }),
      note, error,
      field('Phone number', phone),
      h('div', { class: 'small muted', style: 'margin:-6px 0 10px', text: 'Include the country code, e.g. +91 90000 00001.' }),
      enrolment ? h('div', { style: 'margin-bottom:12px' }, enrolment.node) : null,
      sendBtn,
      codeRow,
      h('a', { class: 'portal-switch', href: cfg.otherHref, text: cfg.otherText }));
  }

  function renderPortalLogin(portal, message) {
    const cfg = PORTALS[portal];
    const root = document.getElementById('root');
    const email = inputEl({ type: 'email', placeholder: 'you@university.edu', autocomplete: 'username' });
    const password = inputEl({ type: 'password', placeholder: '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022', autocomplete: 'current-password' });
    const error = h('div', { class: 'alert err', style: message ? 'display:flex' : 'display:none', text: message || '' });
    const submit = h('button', { class: 'btn block', style: 'margin-top:6px', text: 'Sign in' });
    let createMode = false;
    const roleName = { admin: 'a school administrator', user: 'an invigilator', student: 'a student' }[portal];
    const modeNote = h('div', { class: 'alert info', style: 'display:none;margin-top:10px' });
    /* Students choose their branch and course while creating access, so the account
       lands in the right school instead of the first one that was seeded. */
    const enrolment = portal === 'student' ? enrolmentBlock() : null;
    const enrolmentWrap = enrolment
      ? h('div', { style: 'display:none;margin-top:12px' }, enrolment.node) : null;
    const switchMode = h('button', { class: 'btn ghost block', type: 'button', style: 'margin-top:8px',
      text: 'New here? Get access with your Gmail' });
    const googleSlot = h('div', { class: 'google-slot' });
    const providers = App.state.providers || { password: true, google: false };
    const passwordOn = providers.password !== false;
    const form = h('form', { class: 'login-form' },
      h('div', { class: 'portal-badge ' + portal, text: cfg.badge + ' portal' }),
      h('h1', { text: cfg.heading }),
      h('p', { class: 'muted small', style: 'margin-bottom:18px', text: cfg.intro }),
      error,
      passwordOn ? field('Email address', email) : null,
      passwordOn ? field('Password', password) : null,
      passwordOn ? submit : null,
      passwordOn ? switchMode : null,
      passwordOn ? enrolmentWrap : null,
      passwordOn ? modeNote : null,
      googleSlot,
      providers.otp ? h('div', { class: 'mt12', style: 'margin-top:10px' },
        h('button', { class: 'btn ghost block', type: 'button', text: 'Email me a sign-in code',
          onclick: () => {
            const next = buildCodeFlow(portal, cfg, async () => { await start(); });
            form.replaceWith(next);
            const first = next.querySelector('input');
            if (first) first.focus();
          } })) : null,
      providers.phone ? h('div', { class: 'mt12', style: 'margin-top:10px' },
        h('button', { class: 'btn ghost block', type: 'button', text: 'Continue with phone number',
          onclick: () => {
            const next = buildPhoneFlow(portal, cfg, async () => { await start(); });
            form.replaceWith(next);
            const first = next.querySelector('input');
            if (first) first.focus();
          } })) : null,
      passwordOn ? null : h('div', { class: 'alert info', style: 'margin-top:12px',
        text: providers.google ? 'Sign in with your Google account or a code sent to your phone.'
                              : (providers.phone ? 'Sign in with a one-time code sent to your phone.'
                                                 : (providers.otp ? 'Sign in with a one-time code sent to your email.'
                                                                  : 'Sign-in is unavailable until a provider is configured.')) }),
      h('a', { class: 'portal-switch', href: cfg.otherHref, text: cfg.otherText }),
      passwordOn ? h('div', { class: 'demo-box' },
        h('div', { style: 'margin-bottom:6px;font-weight:600;color:#334155', text: 'Demonstration accounts' }),
        h('div', null, cfg.demo.map((row) => demoChip(row[0], row[1], row[2], email, password))),
        h('div', { style: 'margin-top:8px', text: 'Seeded demonstration data \u2014 fictional schools and faculty.' })) : null);

    loadGoogleButton(googleSlot, portal);
    const googleError = new URLSearchParams(location.search).get('google_error');
    if (googleError) {
      error.textContent = GOOGLE_ERRORS[googleError] || 'Google sign-in did not complete. Please try again.';
      error.style.display = 'flex';
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      error.style.display = 'none';
      submit.disabled = true;
      if (createMode && enrolment) {
        const problem = enrolment.problem();
        if (problem) {
          error.textContent = problem;
          error.style.display = 'flex';
          submit.disabled = false;
          submit.textContent = 'Get access with Gmail';
          return;
        }
      }
      submit.innerHTML = '<span class="spinner"></span> ' + (createMode ? 'Creating access' : 'Signing in');
      try {
        const body = { email: email.value.trim(), password: password.value, portal: portal };
        if (createMode && enrolment) Object.assign(body, enrolment.read());
        const data = await api(createMode ? '/api/auth/gmail' : '/api/auth/login', {
          method: 'POST',
          body: body,
        });
        App.state.token = data.token;
        App.state.user = data.user;
        localStorage.setItem('examflow_token', data.token);
        await start();
      } catch (err) {
        error.textContent = err.message;
        error.style.display = 'flex';
        submit.disabled = false;
        submit.textContent = createMode ? 'Get access with Gmail' : 'Sign in';
      } finally {
        submit.disabled = false;
        if (document.body.contains(submit)) {
          submit.textContent = createMode ? 'Get access with Gmail' : 'Sign in';
        }
      }
    });

    switchMode.addEventListener('click', () => {
      createMode = !createMode;
      submit.textContent = createMode ? 'Get access with Gmail' : 'Sign in';
      switchMode.textContent = createMode ? 'Back to sign in' : 'New here? Get access with your Gmail';
      modeNote.style.display = createMode ? 'flex' : 'none';
      if (enrolmentWrap) enrolmentWrap.style.display = createMode ? '' : 'none';
      modeNote.textContent = 'Enter your Gmail address and pick a password (8 or more characters). '
        + 'Access is created instantly \u2014 no email or verification code needed \u2014 as ' + roleName + '.';
      error.style.display = 'none';
      if (createMode) password.setAttribute('autocomplete', 'new-password');
      else password.setAttribute('autocomplete', 'current-password');
    });

    root.innerHTML = '';
    root.appendChild(h('div', { class: 'login' },
      h('div', { class: 'login-aside' },
        brandHead(),
        h('h2', { text: cfg.lead }),
        h('p', { text: cfg.body }),
        h('div', { class: 'login-points' }, cfg.points.map(point)),
        institutionFoot()),
      h('div', { class: 'login-form-wrap' }, form)));
  }

  function point(text) {
    return h('div', { class: 'login-point' }, h('span', { class: 'tick', text: '\u2713' }), h('span', null, h('b', { text: text.split(' ').slice(0, 2).join(' ') }), ' ' + text.split(' ').slice(2).join(' ')));
  }

  function demoChip(label, mail, pass, emailEl, passEl) {
    return h('button', {
      type: 'button', class: 'demo-chip', text: label + ' \u00b7 ' + mail,
      onclick: () => { emailEl.value = mail; passEl.value = pass; },
    });
  }

  function logout(callServer) {
    if (callServer && App.state.token) {
      api('/api/auth/logout', { method: 'POST' }).catch(() => {});
    }
    App.state.token = null;
    App.state.user = null;
    App.state.meta = null;
    localStorage.removeItem('examflow_token');
    location.hash = '#/login';
    renderLogin();
  }

  async function start() {
    if (!App.state.token) { renderLogin(); return; }
    try {
      const me = await api('/api/auth/me');
      App.state.user = me.user;
      App.state.meta = await api('/api/meta');
    } catch (err) {
      App.state.token = null;
      localStorage.removeItem('examflow_token');
      renderLogin(err.message);
      return;
    }
    const onLoginPage = (location.hash || '').indexOf('#/login') === 0;
    if (!location.hash || onLoginPage) {
      location.hash = '#/' + homeRoute();
    }
    buildShell();
    await renderRoute();
    announceGooglePortal();
  }

  async function boot() {
    /* Show something instantly: the first API call can take a few seconds on a
       cold serverless instance, and a blank screen looks like a broken site. */
    const splashHost = document.getElementById('root');
    if (splashHost && !splashHost.childElementCount) {
      splashHost.innerHTML =
        '<div style="min-height:70vh;display:flex;flex-direction:column;align-items:center;' +
        'justify-content:center;gap:14px;font-family:system-ui,-apple-system,Segoe UI,sans-serif">' +
        '<div style="width:38px;height:38px;border-radius:10px;background:#2563eb;color:#fff;' +
        'display:flex;align-items:center;justify-content:center;font-weight:700;font-size:19px">E</div>' +
        '<div style="color:#0f172a;font-weight:600">ExamFlow AI</div>' +
        '<div style="color:#64748b;font-size:13px">Starting up, one moment…</div></div>';
    }
    takeGoogleToken();
    try {
      const response = await fetch('/api/auth/providers');
      if (response.ok) App.state.providers = await response.json();
    } catch (err) { /* fall back to the password form */ }
    window.addEventListener('hashchange', () => {
      if (App.state.user) renderRoute();
      else renderLogin();
    });
    await start();
  }

  /* ---------------------------------------------------------------- exports */
  Object.assign(App, {
    h, icon, esc, api, toast, modal, confirmAction, field, select, inputEl, formModal,
    dataTable, pill, statusPill, chartBar, chartLine, chartDonut, barList, kpi, card,
    pageHead, loadingBlock, downloadFile, toCsv, route, navigate, boot, logout,
    fmtDate, fmtDateTime, fmtNum, schoolName, initials, renderRoute, parseHash,
  });
  window.App = App;
  window.h = h;
})();
