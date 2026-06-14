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
      } else {
        messages.push({role: 'assistant', type: 'chat', content: String(payload.message || '')});
      }
      renderMessages();
      setStatus(payload.model ? `model: ${payload.model}` : '', payload.model ? 'info' : '');
    } catch (error) {
      setStatus(String(error?.message || 'Ollama Chat 요청 실패'), 'error');
    } finally {
      busy = false;
      if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = 'Send'; }
      position();
    }
  }

  function open() {
    if (popup) {
      popup.style.display = '';
      if (!onResize) { onResize = () => position(); win.addEventListener('resize', onResize); }
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
