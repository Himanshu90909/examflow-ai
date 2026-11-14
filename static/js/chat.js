/* ExamFlow AI · the in-app assistant */
(function () {
  const {
    h, api, toast, route, icon, pageHead, loadingBlock,
  } = App;

  const STORE = 'examflow_assistant_thread';

  function loadThread() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORE) || '[]');
      return Array.isArray(saved) ? saved.slice(-40) : [];
    } catch (err) { return []; }
  }

  function saveThread(thread) {
    try { sessionStorage.setItem(STORE, JSON.stringify(thread.slice(-40))); } catch (err) { /* private mode */ }
  }

  function greeting() {
    const { user } = App.state;
    const role = (user && user.role) || 'Super Admin';
    const first = ((user && user.full_name) || '').split(' ')[0];
    if (role === 'Student') {
      return `Hi${first ? ' ' + first : ''} — ask me when and where your papers are held, or about your seat block. I answer from the published timetable only.`;
    }
    if (role === 'Invigilator') {
      return `Hi${first ? ' ' + first : ''} — ask me about your duties: the next one, this week, or how your workload compares with your cap.`;
    }
    return `Hi${first ? ' ' + first : ''} — ask me about the timetable, a date, a room, conflicts, unscheduled papers, invigilator workload or the scheduling rules. Every answer is read from the live run.`;
  }

  function renderLines(text) {
    const nodes = [];
    String(text || '').split('\n').forEach((line) => {
      if (!line.trim()) { nodes.push(h('div', { class: 'chat-gap' })); return; }
      if (line.trim().startsWith('· ')) {
        nodes.push(h('div', { class: 'chat-li', text: line.trim().slice(2) }));
      } else {
        nodes.push(h('div', { class: 'chat-p', text: line }));
      }
    });
    return nodes;
  }

  route({
    id: 'assistant',
    title: 'AI Assistant',
    render: async (view) => {
      let thread = loadThread();
      let busy = false;

      const status = await api('/api/assistant/status').catch(() => ({ mode: 'grounded' }));

      view.appendChild(pageHead('AI Assistant',
        'Ask the examination office a question in plain words. Answers are read from the live timetable and scoped to your role.',
        [h('button', {
          class: 'btn secondary',
          onclick: () => { thread = []; saveThread(thread); paint(); },
        }, 'New chat')]));

      const transcript = h('div', { class: 'chat-thread', id: 'chat-thread' });
      const composer = h('textarea', {
        class: 'chat-input', rows: '1', placeholder: 'Ask about a date, a room, a paper, your duties…',
        'aria-label': 'Message the assistant',
      });
      const sendBtn = h('button', { class: 'btn chat-send' }, icon('spark', 15), 'Send');
      const chips = h('div', { class: 'chat-chips' });

      const modeNote = status.mode === 'llm'
        ? `Language model: ${status.model || 'configured'} · grounded in the live run`
        : 'Grounded lookup · no external service, no key required';

      view.appendChild(h('div', { class: 'card chat-card' },
        h('div', { class: 'chat-head' },
          h('div', { class: 'chat-avatar' }, icon('spark', 16)),
          h('div', null,
            h('div', { class: 'chat-title' }, 'ExamFlow Assistant'),
            h('div', { class: 'chat-sub', text: modeNote })),
          h('div', { class: 'chat-badge', text: status.mode === 'llm' ? 'LLM' : 'Grounded' })),
        transcript,
        h('div', { class: 'chat-compose' }, composer, sendBtn),
        chips));

      function bubble(entry) {
        const mine = entry.role === 'user';
        return h('div', { class: `chat-row ${mine ? 'me' : 'bot'}` },
          !mine ? h('div', { class: 'chat-avatar sm' }, icon('spark', 13)) : null,
          h('div', { class: `chat-bubble ${mine ? 'me' : 'bot'}` },
            mine ? h('div', { class: 'chat-p', text: entry.text }) : renderLines(entry.text),
            entry.mode && entry.mode !== 'grounded'
              ? h('div', { class: 'chat-meta', text: entry.mode === 'llm' ? 'Answered by the language model' : 'Grounded answer (model unavailable)' })
              : null));
      }

      function thinking() {
        return h('div', { class: 'chat-row bot', id: 'chat-thinking' },
          h('div', { class: 'chat-avatar sm' }, icon('spark', 13)),
          h('div', { class: 'chat-bubble bot' },
            h('div', { class: 'chat-typing' }, h('span'), h('span'), h('span'))));
      }

      function paint() {
        transcript.innerHTML = '';
        if (!thread.length) {
          transcript.appendChild(h('div', { class: 'chat-row bot' },
            h('div', { class: 'chat-avatar sm' }, icon('spark', 13)),
            h('div', { class: 'chat-bubble bot' }, renderLines(greeting()))));
        }
        thread.forEach((entry) => transcript.appendChild(bubble(entry)));
        if (busy) transcript.appendChild(thinking());
        transcript.scrollTop = transcript.scrollHeight;
      }

      function chipRow(items) {
        chips.innerHTML = '';
        (items || []).slice(0, 4).forEach((text) => {
          chips.appendChild(h('button', {
            class: 'chip chat-chip',
            onclick: () => { composer.value = text; submit(); },
          }, text));
        });
      }

      async function submit() {
        const message = (composer.value || '').trim();
        if (!message || busy) return;
        composer.value = '';
        composer.style.height = 'auto';
        thread.push({ role: 'user', text: message });
        busy = true;
        paint();
        try {
          const data = await api('/api/assistant/chat', {
            method: 'POST',
            body: { message, history: thread.slice(-6).map((t) => ({ role: t.role, text: t.text })) },
          });
          thread.push({ role: 'assistant', text: data.reply, mode: data.mode });
          chipRow(data.suggestions);
        } catch (err) {
          toast(err.message || 'The assistant could not answer that.', 'error');
          thread.push({ role: 'assistant', text: 'That one did not go through. ' + (err.message || '') });
        } finally {
          busy = false;
          saveThread(thread);
          paint();
          composer.focus();
        }
      }

      sendBtn.addEventListener('click', submit);
      composer.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
      });
      composer.addEventListener('input', () => {
        composer.style.height = 'auto';
        composer.style.height = Math.min(composer.scrollHeight, 140) + 'px';
      });

      const last = thread.filter((t) => t.role === 'assistant').pop();
      chipRow(!last ? (App.state.user && App.state.user.role === 'Student'
        ? ['When is my next exam?', 'Where do I sit?', 'Show all my papers']
        : (App.state.user && App.state.user.role === 'Invigilator'
          ? ['What is my next duty?', 'How many duties do I have?']
          : ['What is scheduled tomorrow?', 'Any conflicts?', 'Which invigilators are overloaded?'])) : null);

      paint();
      setTimeout(() => composer.focus(), 60);
    },
  });
})();
