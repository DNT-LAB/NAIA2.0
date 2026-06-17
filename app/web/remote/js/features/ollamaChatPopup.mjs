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
  const messages = [];

  function pick(selector) {
    return popup ? popup.querySelector(selector) : null;
  }

  function close() {
    if (typeof hideTagInfo === 'function') hideTagInfo();
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
        item.appendChild(panel);
      }
      if (msg.role === 'assistant' && msg.type === 'scene' && Array.isArray(msg.segments) && msg.segments.length && !msg.dismissed) {
        const panel = document.createElement('div');
        panel.className = 'ollama-chat-chip-panel';
        panel.appendChild(makePanelHead(index, `scene: ${String(msg.anchor || '').slice(0, 64)}`));
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
    try {
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
        });
      } else if (payload.type === 'combos') {
        messages.push({
          role: 'assistant',
          type: 'combos',
          content: String(payload.message || ''),
          subject: String(payload.subject || ''),
          combos: Array.isArray(payload.combos) ? payload.combos : [],
        });
      } else {
        messages.push({role: 'assistant', type: 'chat', content: String(payload.message || '')});
      }
      renderMessages();
      setStatus(payload.model ? `model: ${payload.model}` : '', payload.model ? 'info' : '');
    } catch (error) {
      setStatus(String(error?.message || 'Ollama Chat 요청 실패'), 'error');
    } finally {
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

  async function refreshReadiness() {
    if (!popup) return;
    serverReady = false;
    updateSendGate();
    renderReadiness('<span class="ollama-chat-ready-msg">Ollama 상태 확인 중…</span>');
    let data = {};
    try { data = (await fetchJson('/api/ollama/status?fresh=0')).payload; }
    catch (_) { data = {ok: false}; }
    if (!popup) return;
    const recheck = '<button type="button" class="ollama-chat-ready-btn secondary" data-act="recheck">다시 확인</button>';
    if (!data || data.ok === false) {
      renderReadiness('<span class="ollama-chat-ready-msg err">백엔드에 연결할 수 없습니다.</span>' + recheck);
      return;
    }
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

  async function checkEventDatasetOnce() {
    // 이벤트 데이터셋 1회 체크(정보성). 미설치여도 채팅/의상조합엔 무영향 — 이벤트 도구
    // 신설 시 이 상태로 게이트한다. GET /api/ollama/dataset 재사용(Assist와 동일).
    if (eventChecked) return;
    eventChecked = true;
    try {
      const ds = (await fetchJson('/api/ollama/dataset')).payload;
      if (ds && ds.ready === false) {
        win.console?.info?.('[Ollama Chat] event preset dataset not installed — event features disabled until downloaded.');
      }
    } catch (_) {}
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
      <div class="ollama-chat-bodywrap">
        <div class="ollama-chat-ready" hidden></div>
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
