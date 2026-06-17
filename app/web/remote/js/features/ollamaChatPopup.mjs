import {
  DEFAULT_MODEL,
  fetchOllamaConnection,
  fetchOllamaStatus,
  postOllamaConnectionModel,
  setOllamaModelSelectOptions,
} from './ollamaModelSelect.mjs?v=20260617-modelsel';

export function createOllamaChatPopup({
  document,
  window: win = window,
  showToast = () => {},
  escHtml = value => String(value ?? ''),
  getContext = () => ({}),
  lookupTagInfo = null,
  hideTagInfo = null,
}) {
  let popup = null;
  let onResize = null;
  let busy = false;
  let serverReady = false;
  let eventChecked = false;
  let eventPollTimer = null;
  let connModel = DEFAULT_MODEL;
  let connEndpointBase = '';
  let canConfigure = false;
  let installedModels = [];
  const messages = [];

  function pick(selector) {
    return popup ? popup.querySelector(selector) : null;
  }

  function close() {
    if (typeof hideTagInfo === 'function') hideTagInfo();
    stopEventDatasetPolling();
    if (onResize) {
      win.removeEventListener('resize', onResize);
      onResize = null;
    }
    if (popup) popup.style.display = 'none';
  }

  function isOpen() {
    return !!popup && popup.style.display !== 'none';
  }

  function position() {
    if (!popup) return;
    const pw = popup.offsetWidth;
    const ph = popup.offsetHeight;
    const margin = 8;
    const resultViewer = document.getElementById('resultViewer');
    const activePane = document.querySelector('.right-tab-pane.active')
      || document.getElementById('rightTabResult');
    const target = resultViewer || activePane;
    const targetRect = target ? target.getBoundingClientRect() : null;
    if (
      targetRect
      && win.innerWidth >= 768
      && targetRect.width >= pw + 32
      && targetRect.height >= Math.min(ph, 360) + 32
    ) {
      const left = Math.max(margin, Math.min(targetRect.left + 16, win.innerWidth - pw - margin));
      const preferredTop = targetRect.bottom - ph - 16;
      const lowerTop = targetRect.top + 16;
      const upperTop = Math.min(targetRect.bottom - ph - 16, win.innerHeight - ph - margin);
      const top = Math.max(
        margin,
        upperTop >= lowerTop
          ? Math.min(Math.max(preferredTop, lowerTop), upperTop)
          : lowerTop
      );
      popup.style.left = `${Math.round(left)}px`;
      popup.style.top = `${Math.round(top)}px`;
      return;
    }
    const btn = document.getElementById('ollamaChatBtn');
    const rect = btn ? btn.getBoundingClientRect() : null;
    let left = rect ? (rect.right - pw) : (win.innerWidth - pw - 16);
    left = Math.max(margin, Math.min(left, win.innerWidth - pw - margin));
    let top = rect ? (rect.bottom + margin) : 48;
    if (top + ph > win.innerHeight - margin && rect) top = rect.top - ph - margin;
    top = Math.max(margin, Math.min(top, win.innerHeight - ph - margin));
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  function setStatus(text, type = '') {
    const el = pick('.ollama-chat-status');
    if (!el) return;
    el.className = 'ollama-chat-status' + (type ? ' ' + type : '');
    el.textContent = text || '';
  }

  function eventMainAvailability(payload) {
    const availability = payload?.availability || payload?.dataAvailability || {};
    return String(availability.main || payload?.main || '').toLowerCase();
  }

  function stopEventDatasetPolling() {
    if (eventPollTimer) {
      win.clearInterval(eventPollTimer);
      eventPollTimer = null;
    }
  }

  function renderDatasetState(html) {
    const el = pick('.ollama-chat-dataset');
    if (!el) return;
    if (!html) {
      el.hidden = true;
      el.innerHTML = '';
      return;
    }
    el.hidden = false;
    el.innerHTML = html;
    el.querySelectorAll('[data-dataset-act]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.datasetAct === 'download') void startEventDatasetDownload();
        else void checkEventDatasetOnce({force: true});
      });
    });
  }

  function renderDatasetDownload(payload) {
    const percent = Math.max(0, Math.min(100, Number(payload?.percent) || 0));
    const mb = payload?.total_mb
      ? `${Number(payload.downloaded_mb || 0).toFixed(1)} / ${Number(payload.total_mb || 0).toFixed(1)} MB`
      : `${Number(payload?.downloaded_mb || 0).toFixed(1)} MB`;
    const msg = escHtml(String(payload?.message || '이벤트 데이터를 받는 중입니다.'));
    renderDatasetState(`
      <span class="ollama-chat-ready-msg">${msg}</span>
      <span class="ollama-chat-dataset-meter"><span style="width:${percent}%"></span></span>
      <span class="ollama-chat-dataset-mb">${escHtml(mb)}</span>`);
  }

  function updateModelSelect() {
    setOllamaModelSelectOptions(pick('.ollama-chat-model-select'), {
      models: installedModels,
      currentModel: connModel,
      disabled: !canConfigure,
    });
  }

  async function refreshConnection() {
    try {
      const {status, payload} = await fetchOllamaConnection(win);
      if (status === 403 || !payload || payload.ok === false) {
        canConfigure = false;
        updateModelSelect();
        return;
      }
      canConfigure = true;
      connEndpointBase = String(payload.endpoint || '');
      connModel = String(payload.model || '') || connModel || DEFAULT_MODEL;
    } catch (_) {
      canConfigure = false;
    }
    updateModelSelect();
  }

  async function saveSelectedModel(model) {
    const selected = String(model || '').trim();
    if (!selected || !canConfigure) {
      updateModelSelect();
      return;
    }
    const select = pick('.ollama-chat-model-select');
    if (select) select.disabled = true;
    try {
      const {status, payload} = await postOllamaConnectionModel(win, {
        endpoint: connEndpointBase,
        model: selected,
      });
      if (status === 403) {
        showToast(payload.error || 'NAIA가 실행 중인 PC에서만 가능합니다.', 'error');
        return;
      }
      if (!payload || payload.ok === false) {
        showToast(payload?.error || '모델 설정 저장 실패', 'error');
        return;
      }
      connEndpointBase = String(payload.endpoint || '');
      connModel = String(payload.model || '') || selected || DEFAULT_MODEL;
      canConfigure = true;
      updateModelSelect();
      showToast('Ollama 모델 설정을 저장했습니다.', 'success');
      void refreshReadiness(true);
    } catch (_) {
      showToast('모델 설정 요청 실패', 'error');
    } finally {
      updateModelSelect();
    }
  }

  function makeChip(tag, meta) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'generation-info-tag ollama-chat-chip';
    btn.dataset.tag = tag;
    btn.dataset.copyTag = tag;
    const parts = [];
    if (meta && meta.count) parts.push(`count: ${meta.count}`);
    if (meta && meta.match) parts.push(String(meta.match));
    btn.title = parts.length ? `${tag} · ${parts.join(' · ')}` : tag;
    btn.textContent = tag;
    btn.addEventListener('mouseenter', () => {
      if (typeof lookupTagInfo === 'function') lookupTagInfo(tag, {anchor: btn});
    });
    btn.addEventListener('mouseleave', () => {
      if (typeof hideTagInfo === 'function') hideTagInfo();
    });
    btn.addEventListener('click', () => { void copyChip(tag); });
    return btn;
  }

  function makePanelHead(index, label) {
    const header = document.createElement('div');
    header.className = 'ollama-chat-chip-head';
    const title = document.createElement('span');
    title.className = 'ollama-chat-chip-title';
    title.textContent = label;
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'ollama-chat-chip-dismiss';
    dismiss.dataset.dismissIndex = String(index);
    dismiss.setAttribute('aria-label', 'Dismiss');
    dismiss.textContent = '×';
    header.appendChild(title);
    header.appendChild(dismiss);
    return header;
  }

  function makeCopyAllRow(tags) {
    const list = (Array.isArray(tags) ? tags : []).map(t => String(t || '').trim()).filter(Boolean);
    const seen = new Set();
    const uniq = list.filter(t => (seen.has(t) ? false : seen.add(t)));
    const row = document.createElement('div');
    row.className = 'ollama-chat-copyall-row';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ollama-chat-copyall-btn';
    btn.textContent = `\u{1F4CB} Copy All (${uniq.length})`;
    btn.disabled = !uniq.length;
    btn.addEventListener('click', () => { void copyChip(uniq.join(', ')); });
    row.appendChild(btn);
    return row;
  }

  function renderMessages() {
    if (typeof hideTagInfo === 'function') hideTagInfo();
    const log = pick('.ollama-chat-log');
    if (!log) return;
    log.textContent = '';
    if (!messages.length) {
      const empty = document.createElement('div');
      empty.className = 'ollama-chat-empty';
      empty.textContent = '현재 프롬프트와 선택된 결과를 컨텍스트로 사용합니다.';
      log.appendChild(empty);
      return;
    }
    messages.forEach((msg, index) => {
      const item = document.createElement('div');
      item.className = `ollama-chat-msg ${msg.role === 'assistant' ? 'assistant' : 'user'}${msg.type === 'blocked' ? ' blocked' : ''}`;
      const role = document.createElement('div');
      role.className = 'ollama-chat-role';
      role.textContent = msg.role === 'assistant' ? 'Ollama' : 'You';
      const body = document.createElement('div');
      body.className = 'ollama-chat-body';
      body.textContent = msg.content || '';
      item.appendChild(role);
      item.appendChild(body);
      if (msg.role === 'assistant' && msg.type === 'chips' && Array.isArray(msg.chips) && msg.chips.length && !msg.dismissed) {
        const panel = document.createElement('div');
        panel.className = 'ollama-chat-chip-panel';
        const header = document.createElement('div');
        header.className = 'ollama-chat-chip-head';
        const title = document.createElement('span');
        title.className = 'ollama-chat-chip-title';
        title.textContent = `results for: ${String(msg.anchor || '').slice(0, 80)}`;
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'ollama-chat-chip-dismiss';
        dismiss.dataset.dismissIndex = String(index);
        dismiss.setAttribute('aria-label', 'Dismiss chip results');
        dismiss.textContent = '×';
        header.appendChild(title);
        header.appendChild(dismiss);
        const chips = document.createElement('div');
        chips.className = 'ollama-chat-chips';
        msg.chips.forEach(chip => {
          const tag = String(chip?.tag || '').trim();
          if (!tag) return;
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'generation-info-tag ollama-chat-chip';
          btn.dataset.tag = tag;
          btn.dataset.copyTag = tag;
          const meta = [
            chip?.reason ? String(chip.reason) : '',
            chip?.role ? `role: ${chip.role}` : '',
            chip?.count ? `count: ${chip.count}` : '',
          ].filter(Boolean).join(' · ');
          btn.title = meta ? `${tag} · ${meta}` : tag;
          btn.textContent = tag;
          btn.addEventListener('mouseenter', () => {
            if (typeof lookupTagInfo === 'function') lookupTagInfo(tag, {anchor: btn});
          });
          btn.addEventListener('mouseleave', () => {
            if (typeof hideTagInfo === 'function') hideTagInfo();
          });
          btn.addEventListener('click', () => {
            void copyChip(tag);
          });
          chips.appendChild(btn);
        });
        panel.appendChild(header);
        panel.appendChild(chips);
        panel.appendChild(makeCopyAllRow(msg.chips.map(c => c?.tag).filter(Boolean)));
        item.appendChild(panel);
      }
      if (msg.role === 'assistant' && msg.type === 'scene' && Array.isArray(msg.segments) && msg.segments.length && !msg.dismissed) {
        const panel = document.createElement('div');
        panel.className = 'ollama-chat-chip-panel';
        panel.appendChild(makePanelHead(index, `scene: ${String(msg.anchor || '').slice(0, 64)}`));
        if (msg.note) {
          const note = document.createElement('div');
          note.className = 'ollama-chat-scene-note';
          note.textContent = msg.note;
          panel.appendChild(note);
        }
        if (msg.cleanEnglish) {
          const ce = document.createElement('div');
          ce.className = 'ollama-chat-scene-note ollama-chat-scene-en';
          ce.textContent = '→ ' + msg.cleanEnglish;
          panel.appendChild(ce);
        }
        msg.segments.forEach(seg => {
          const row = document.createElement('div');
          row.className = 'ollama-chat-scene-seg';
          const lbl = document.createElement('div');
          lbl.className = 'ollama-chat-scene-label';
          lbl.textContent = `${seg.axis || 'general'} · ${String(seg.phrase || '').slice(0, 22)}`;
          const chips = document.createElement('div');
          chips.className = 'ollama-chat-chips';
          (Array.isArray(seg.tags) ? seg.tags : []).forEach(t => {
            const tag = String(t?.tag || '').trim();
            if (tag) chips.appendChild(makeChip(tag, t));
          });
          row.appendChild(lbl);
          row.appendChild(chips);
          panel.appendChild(row);
        });
        const sceneFlat = (Array.isArray(msg.flatTags) && msg.flatTags.length)
          ? msg.flatTags
          : msg.segments.flatMap(s => (Array.isArray(s.tags) ? s.tags : []).map(t => t?.tag));
        const eventTags = Array.isArray(msg.eventTags) ? msg.eventTags : [];
        if (eventTags.length) {
          const ev = document.createElement('div');
          ev.className = 'ollama-chat-event-section';
          const evTitle = document.createElement('div');
          evTitle.className = 'ollama-chat-event-title';
          evTitle.textContent = '관련 이벤트';
          ev.appendChild(evTitle);
          if (Array.isArray(msg.eventLabels) && msg.eventLabels.length) {
            const cap = document.createElement('div');
            cap.className = 'ollama-chat-event-caption';
            cap.textContent = msg.eventLabels.slice(0, 4).join(' · ');
            ev.appendChild(cap);
          }
          const chips = document.createElement('div');
          chips.className = 'ollama-chat-chips';
          eventTags.forEach(t => {
            const tag = String(t?.tag || '').trim();
            if (tag) chips.appendChild(makeChip(tag, {count: t.count, match: 'event'}));
          });
          ev.appendChild(chips);
          panel.appendChild(ev);
        }
        const copyTags = (Array.isArray(msg.finalTags) && msg.finalTags.length)
          ? msg.finalTags
          : sceneFlat.concat(eventTags.map(t => t?.tag).filter(Boolean));
        panel.appendChild(makeCopyAllRow(copyTags));
        item.appendChild(panel);
      }
      if (msg.role === 'assistant' && msg.type === 'combos' && Array.isArray(msg.combos) && msg.combos.length && !msg.dismissed) {
        const panel = document.createElement('div');
        panel.className = 'ollama-chat-chip-panel';
        panel.appendChild(makePanelHead(index, `combos: ${String(msg.subject || '').slice(0, 40)}`));
        msg.combos.forEach(combo => {
          const card = document.createElement('div');
          card.className = 'ollama-chat-combo';
          const chips = document.createElement('div');
          chips.className = 'ollama-chat-chips';
          (Array.isArray(combo?.tags) ? combo.tags : []).forEach(tg => {
            const tag = String(tg || '').trim();
            if (tag) chips.appendChild(makeChip(tag, {count: combo.count}));
          });
          const copyAll = document.createElement('button');
          copyAll.type = 'button';
          copyAll.className = 'ollama-chat-combo-copy';
          copyAll.textContent = `복사 (${combo?.count || 0})`;
          copyAll.addEventListener('click', () => { void copyChip((combo?.tags || []).join(', ')); });
          card.appendChild(chips);
          card.appendChild(copyAll);
          panel.appendChild(card);
        });
        item.appendChild(panel);
      }
      if (msg.role === 'assistant' && msg.type === 'clarification' && Array.isArray(msg.examples) && msg.examples.length) {
        const ex = document.createElement('div');
        ex.className = 'ollama-chat-clarify-examples';
        msg.examples.forEach(q => {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 'ollama-chat-clarify-example';
          b.textContent = q;
          b.addEventListener('click', () => {
            const inputEl = pick('.ollama-chat-input');
            if (inputEl) { inputEl.value = q; inputEl.focus(); }
          });
          ex.appendChild(b);
        });
        item.appendChild(ex);
      }
      log.appendChild(item);
    });
    log.querySelectorAll('[data-dismiss-index]').forEach(button => {
      button.addEventListener('click', () => {
        const idx = Number(button.dataset.dismissIndex);
        if (Number.isInteger(idx) && messages[idx]) {
          messages[idx].dismissed = true;
          renderMessages();
        }
      });
    });
    log.scrollTop = log.scrollHeight;
  }

  async function copyChip(tag) {
    const text = String(tag || '').trim();
    if (!text) return;
    try {
      await win.navigator.clipboard.writeText(text);
      showToast('태그를 복사했습니다.', 'success');
    } catch (_) {
      showToast('클립보드 복사에 실패했습니다.', 'error');
    }
  }

  async function send() {
    if (busy) return;
    const input = pick('.ollama-chat-input');
    const sendBtn = pick('.ollama-chat-send');
    const text = String(input?.value || '').trim();
    if (!text) {
      showToast('Chat 메시지를 입력하세요.', 'info');
      return;
    }
    if (!serverReady) {
      showToast('Ollama 서버를 먼저 시작하세요.', 'info');
      void refreshReadiness();
      return;
    }
    messages.push({role: 'user', content: text});
    if (input) input.value = '';
    renderMessages();
    busy = true;
    if (sendBtn) { sendBtn.disabled = true; sendBtn.textContent = 'Sending'; }
    setStatus('Ollama 응답을 기다리는 중입니다.', 'info');
    let progressTimer = null;
    try {
      progressTimer = win.setInterval(async () => {
        if (!busy) return;
        try {
          const pr = await (await win.fetch('/api/ollama/chat/progress')).json();
          if (pr && pr.active && pr.label && busy) setStatus(`${pr.label} … (${pr.step}/${pr.total})`, 'info');
        } catch (_) {}
      }, 700);
      const response = await win.fetch('/api/ollama/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          messages: messages.slice(-12),
          context: getContext() || {},
          temperature: 0.35,
          num_predict: 512,
        }),
      });
      let payload = {};
      try { payload = await response.json(); } catch (_) { payload = {}; }
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      if (payload.type === 'chips') {
        messages.push({
          role: 'assistant',
          type: 'chips',
          content: String(payload.message || ''),
          anchor: String(payload.anchor || text),
          chips: Array.isArray(payload.chips) ? payload.chips : [],
        });
      } else if (payload.type === 'blocked') {
        messages.push({
          role: 'assistant',
          type: 'blocked',
          content: String(payload.message || '요청을 처리할 수 없습니다.'),
          anchor: String(payload.anchor || text),
        });
      } else if (payload.type === 'scene') {
        messages.push({
          role: 'assistant',
          type: 'scene',
          content: String(payload.message || ''),
          anchor: String(payload.anchor || text),
          segments: Array.isArray(payload.segments) ? payload.segments : [],
          flatTags: Array.isArray(payload.flatTags) ? payload.flatTags : [],
          eventTags: Array.isArray(payload.eventTags) ? payload.eventTags : [],
          eventLabels: Array.isArray(payload.eventLabels) ? payload.eventLabels : [],
        });
      } else if (payload.type === 'combos') {
        messages.push({
          role: 'assistant',
          type: 'combos',
          content: String(payload.message || ''),
          subject: String(payload.subject || ''),
          combos: Array.isArray(payload.combos) ? payload.combos : [],
        });
      } else if (payload.type === 'scene_pipeline') {
        messages.push({
          role: 'assistant',
          type: 'scene',
          content: String(payload.message || ''),
          anchor: String((payload.translation && payload.translation.source) || payload.anchor || text),
          segments: Array.isArray(payload.segments) ? payload.segments : [],
          eventTags: Array.isArray(payload.eventTags) ? payload.eventTags : [],
          eventLabels: Array.isArray(payload.eventLabels) ? payload.eventLabels : [],
          finalTags: Array.isArray(payload.finalTags) ? payload.finalTags : [],
          note: String((payload.intent && payload.intent.interpretation_note) || ''),
          cleanEnglish: String((payload.translation && payload.translation.cleanEnglish) || ''),
        });
      } else if (payload.type === 'clarification') {
        messages.push({
          role: 'assistant',
          type: 'clarification',
          content: String(payload.question || '조금 더 구체적으로 알려주실 수 있나요?'),
          examples: Array.isArray(payload.examples)
            ? payload.examples.map(e => String(e || '').trim()).filter(Boolean)
            : [],
        });
      } else {
        messages.push({role: 'assistant', type: 'chat', content: String(payload.message || '')});
      }
      renderMessages();
      if (payload.model) {
        connModel = String(payload.model);
        updateModelSelect();
      }
      setStatus(payload.model ? `model: ${payload.model}` : '', payload.model ? 'info' : '');
    } catch (error) {
      setStatus(String(error?.message || 'Ollama Chat 요청 실패'), 'error');
    } finally {
      if (progressTimer) win.clearInterval(progressTimer);
      busy = false;
      if (sendBtn) sendBtn.textContent = 'Send';
      updateSendGate();
      position();
    }
  }

  // --- Ollama 서버/이벤트 준비 상태 게이트 (Assist 팝업과 동일 엔드포인트 재사용) ---
  async function fetchJson(url, options) {
    const r = await win.fetch(url, options);
    let payload = null;
    try { payload = await r.json(); } catch (_) { payload = null; }
    return {status: r.status, payload: payload || {}};
  }

  function updateSendGate() {
    const sendBtn = pick('.ollama-chat-send');
    const input = pick('.ollama-chat-input');
    if (sendBtn) sendBtn.disabled = busy || !serverReady;
    if (input) input.placeholder = serverReady
      ? '현재 프롬프트/결과에 대해 질문...'
      : 'Ollama 서버를 먼저 시작하세요';
  }

  function renderReadiness(html) {
    const el = pick('.ollama-chat-ready');
    if (!el) return;
    if (!html) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    el.innerHTML = html;
    el.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.dataset.act === 'start-server') void startServer();
        else void refreshReadiness();
      });
    });
  }

  async function refreshReadiness(fresh = false) {
    if (!popup) return;
    serverReady = false;
    updateSendGate();
    await refreshConnection();
    renderReadiness('<span class="ollama-chat-ready-msg">Ollama 상태 확인 중…</span>');
    let data = {};
    try { data = (await fetchOllamaStatus(win, {fresh})).payload; }
    catch (_) { data = {ok: false}; }
    if (!popup) return;
    const recheck = '<button type="button" class="ollama-chat-ready-btn secondary" data-act="recheck">다시 확인</button>';
    if (!data || data.ok === false) {
      renderReadiness('<span class="ollama-chat-ready-msg err">백엔드에 연결할 수 없습니다.</span>' + recheck);
      return;
    }
    installedModels = Array.isArray(data.models) ? data.models.map(item => String(item || '')).filter(Boolean) : [];
    if (data.model) connModel = String(data.model);
    updateModelSelect();
    if (!data.installed && !data.is_custom_endpoint) {
      renderReadiness('<span class="ollama-chat-ready-msg err">이 PC에 Ollama가 설치되어 있지 않습니다.</span>' + recheck);
      return;
    }
    if (!data.running) {
      const canControl = data.control_allowed !== false && !data.is_custom_endpoint;
      const msg = data.is_custom_endpoint
        ? '원격 Ollama 서버에 연결할 수 없습니다.'
        : 'Ollama 서버가 꺼져 있습니다.';
      renderReadiness(`<span class="ollama-chat-ready-msg warn">${escHtml(msg)}</span>`
        + (canControl ? '<button type="button" class="ollama-chat-ready-btn" data-act="start-server">서버 시작</button>' : '')
        + recheck);
      return;
    }
    serverReady = true;
    renderReadiness('');
    updateSendGate();
    void checkEventDatasetOnce();
  }

  async function startServer() {
    renderReadiness('<span class="ollama-chat-ready-msg">서버 시작 중…</span>');
    try { await fetchJson('/api/ollama/server/start', {method: 'POST'}); } catch (_) {}
    for (let i = 0; i < 20 && popup; i++) {
      await new Promise(resolve => win.setTimeout(resolve, 1000));
      let data = {};
      try { data = (await fetchJson('/api/ollama/status?fresh=1')).payload; } catch (_) {}
      if (data && data.running) break;
    }
    await refreshReadiness();
  }

  async function checkEventDatasetOnce({force = false} = {}) {
    if (eventChecked && !force) return;
    eventChecked = true;
    let ds = {};
    try {
      ds = (await fetchJson('/api/ollama/dataset')).payload;
    } catch (_) {
      renderDatasetState('');
      return;
    }
    if (!popup) return;
    if (ds && ds.active) {
      renderDatasetDownload(ds);
      if (!eventPollTimer) {
        eventPollTimer = win.setInterval(() => { void checkEventDatasetOnce({force: true}); }, 1200);
      }
      return;
    }
    stopEventDatasetPolling();
    if (eventMainAvailability(ds) === 'ready') {
      renderDatasetState('');
      return;
    }
    const error = ds?.error ? `<span class="ollama-chat-ready-msg err">${escHtml(ds.error)}</span>` : '';
    renderDatasetState(`
      ${error || '<span class="ollama-chat-ready-msg warn">이벤트 데이터가 없어 장면 자동 보강이 비활성화됩니다.</span>'}
      <button type="button" class="ollama-chat-ready-btn" data-dataset-act="download">이벤트 데이터 받기</button>
      <button type="button" class="ollama-chat-ready-btn secondary" data-dataset-act="recheck">다시 확인</button>`);
  }

  async function startEventDatasetDownload() {
    renderDatasetState('<span class="ollama-chat-ready-msg">이벤트 데이터 다운로드 시작 중…</span>');
    try {
      const result = (await fetchJson('/api/ollama/dataset', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({force: true}),
      })).payload;
      if (result && result.error) {
        renderDatasetState(`<span class="ollama-chat-ready-msg err">${escHtml(result.error)}</span>`);
        return;
      }
      renderDatasetDownload(result || {});
    } catch (_) {
      renderDatasetState('<span class="ollama-chat-ready-msg err">이벤트 데이터 다운로드를 시작하지 못했습니다.</span>');
      return;
    }
    stopEventDatasetPolling();
    eventPollTimer = win.setInterval(() => { void checkEventDatasetOnce({force: true}); }, 1200);
  }

  function open() {
    if (popup) {
      popup.style.display = '';
      if (!onResize) { onResize = () => position(); win.addEventListener('resize', onResize); }
      void refreshReadiness();
      position();
      win.requestAnimationFrame(() => position());
      return;
    }
    popup = document.createElement('div');
    popup.className = 'ollama-chat-popup';
    popup.innerHTML = `
      <div class="ollama-chat-header">
        <span class="ollama-chat-title">Ollama · Chat</span>
        <button type="button" class="ollama-chat-x" aria-label="닫기">&times;</button>
      </div>
      <div class="ollama-model-select-row ollama-chat-model-row">
        <label class="ollama-model-select-label">Model</label>
        <select class="ollama-model-select ollama-chat-model-select" aria-label="Ollama 모델 선택"></select>
      </div>
      <div class="ollama-chat-bodywrap">
        <div class="ollama-chat-ready" hidden></div>
        <div class="ollama-chat-dataset" hidden></div>
        <div class="ollama-chat-log"></div>
        <textarea class="ollama-chat-input" rows="3" placeholder="현재 프롬프트/결과에 대해 질문..."></textarea>
        <div class="ollama-chat-actions">
          <button type="button" class="ollama-chat-send">Send</button>
        </div>
        <div class="ollama-chat-status"></div>
      </div>`;
    document.body.appendChild(popup);
    pick('.ollama-chat-x')?.addEventListener('click', close);
    pick('.ollama-chat-send')?.addEventListener('click', send);
    pick('.ollama-chat-model-select')?.addEventListener('change', event => {
      void saveSelectedModel(event.target.value);
    });
    pick('.ollama-chat-input')?.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        send();
      }
    });
    renderMessages();
    void refreshReadiness();
    onResize = () => position();
    win.addEventListener('resize', onResize);
    position();
    win.requestAnimationFrame(() => {
      position();
      pick('.ollama-chat-input')?.focus();
    });
  }

  return {open, close, isOpen};
}
