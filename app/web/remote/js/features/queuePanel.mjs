// Stop(2026-11-10 · 사용자 승인 목업) - 도는 로컬 생성 한 장을 멈춘다. 빨간 바탕은 .mod-stop(자동화 '정지')을 그대로 쓰고
// 크기 · 모양만 여기서 준다(다른 기능처럼 모듈이 제 style 을 싣는다 - style.css 를 건드리지 않는다).
// .queue-panel-btn 이 아니다: 접힌 띠는 그 단추들(Pause · Clear)을 숨기지만 Stop 은 접혀도 보여야 한다.
const QSTOP_CSS = `
.queue-panel-stop {
  height: 26px; padding: 0 10px; border: 1px solid rgba(240,64,64,0.9); border-radius: 5px;
  font-family: var(--font-mono); font-size: 10px; font-weight: 800; cursor: pointer; flex: none;
}
.queue-panel-stop[hidden] { display: none; }
.queue-panel-stop:hover:not(:disabled) { filter: brightness(1.15); }
.queue-panel-stop:disabled { opacity: 0.45; cursor: default; }
.queue-panel.collapsed .queue-panel-stop { height: 18px; padding: 0 7px; font-size: 9px; border-radius: 4px; }
@media (max-width: 767px) {
  .queue-panel-stop,
  .queue-panel.collapsed .queue-panel-stop { min-height: 38px; min-width: 56px; padding: 0 12px; font-size: 12px; }
  .queue-panel.collapsed.has-stop .queue-panel-header { height: auto; padding-top: 3px; padding-bottom: 3px; }
}
`;

function ensureStopStyle(document) {
  if (!document || typeof document.createElement !== 'function' || !document.head) return;
  if (typeof document.getElementById === 'function' && document.getElementById('queue-stop-style')) return;
  const style = document.createElement('style');
  style.id = 'queue-stop-style';
  style.textContent = QSTOP_CSS;
  document.head.appendChild(style);
}

export function createQueuePanelController({
  document,
  fetch: fetchFn = window.fetch.bind(window),
  localStorage = window.localStorage,
  showToast = () => {},
  escHtml = value => String(value ?? ''),
}) {
  const root = document.getElementById('queuePanel');
  if (!root) {
    return {
      init() {},
      refresh() {},
      handleState() {},
    };
  }

  const title = root.querySelector('[data-queue-title]');
  const body = root.querySelector('[data-queue-body]');
  const meta = root.querySelector('[data-queue-meta]');
  const stopBtn = root.querySelector('[data-queue-stop]');
  const pauseBtn = root.querySelector('[data-queue-action="pause"]');
  const clearBtn = root.querySelector('[data-queue-action="clear"]');
  const collapseBtn = root.querySelector('[data-queue-collapse]');
  const header = root.querySelector('.queue-panel-header');
  const countEl = root.querySelector('[data-queue-count]');
  // 쉬고 있을 때 Generate 한 번은 큐에 들어갔다가 러너가 곧바로 꺼낸다 - 서버는 그 사이 '대기 1' 을
  // 먼저 보낸다(generation_commands: queue_state 다음에 러너 시작). 그 한 프레임에 패널이 번쩍였다
  // (사용자 제보 2026-10-21). 생성 중이 아닐 때 들어온 대기는 이만큼 남아 있을 때만 보인다.
  const IDLE_QUEUE_GRACE_MS = 700;
  let state = {active: null, items: [], paused: false, total: 0, is_generating: false};
  // 실행하면 늘 접힌 채로 시작한다(사용자 지시 2026-10-21) - 펼친 것은 이번 실행 동안만.
  let collapsed = true;
  let holdVisibleUntil = 0;
  let pulseTimer = 0;
  let idleQueuedSince = 0;
  let graceTimer = 0;
  // 중단을 보낸 장 {id}. 서버가 그 장이 끝났다고 보여 줄 때(queue_state 의 active 가 바뀜)까지 Stop 을 잠근다 - 화면이 먼저
  // 닫지 않는다. 연타 · 머리줄 Stop 과 RUN 줄 × 를 함께 눌러도 한 번만 보낸다.
  let stopSent = null;
  ensureStopStyle(document);

  // 도는 장. 서버는 모든 모드의 도는 장을 싣지만(queue_state.active), 패널이 그 장으로 뜨는 것은 멈출 수 있는
  // 로컬 생성(cancellable - 외부 ComfyUI · 내장 ANIMA)일 때뿐이다(사용자 결정 2026-11-10: 중단 단추를 Queue 패널에 둔다).
  // NAI · WebUI 의 한 장은 예전처럼 안 뜨고, 대기가 쌓였을 때의 개수 · 문구도 예전 그대로다(그때도 이 장은 세지 않는다).
  function shownActive(nextState) {
    const active = nextState?.active;
    return active && active.cancellable ? active : null;
  }

  function visibleState(nextState) {
    const waiting = Array.isArray(nextState?.items) && nextState.items.length > 0;
    return Boolean(
      shownActive(nextState)
      || (waiting && (nextState?.is_generating
        || (idleQueuedSince && Date.now() - idleQueuedSince >= IDLE_QUEUE_GRACE_MS)))
      || nextState?.paused
      || Date.now() < holdVisibleUntil
    );
  }

  function labelForItem(item) {
    const parts = [];
    if (item?.source) parts.push(item.source);
    if (item?.mode) parts.push(item.mode);
    if (item?.resolution) parts.push(item.resolution);
    return parts.join(' · ') || 'Queued request';
  }

  function badgeHtml(text, className = '') {
    if (!text && text !== 0) return '';
    const cls = className ? ` ${className}` : '';
    return `<span class="queue-badge${cls}">${escHtml(String(text))}</span>`;
  }

  function renderItem(item, options = {}) {
    const active = Boolean(options.active);
    const prompt = item?.prompt_preview || item?.label || 'No prompt preview';
    const badges = [
      active ? badgeHtml('RUN', 'active') : badgeHtml(`#${item?.position ?? '?'}`),
      item?.priority > 0 ? badgeHtml('Front', 'priority') : '',
      item?.character_count ? badgeHtml(`C${item.character_count}`, 'nai') : '',
      item?.vibe_count ? badgeHtml(`V${item.vibe_count}`, 'nai') : '',
      item?.char_ref_count ? badgeHtml(`R${item.char_ref_count}`, 'nai') : '',
    ].join('');
    const seed = item?.seed ? `<span>${escHtml(String(item.seed))}</span>` : '';
    // 도는 장(RUN): 멈출 수 있으면 대기 줄의 × 와 같은 모양 · 같은 자리의 중단 단추, 아니면 예전처럼 'current'.
    const remove = active
      ? (item?.cancellable
        ? `<button type="button" class="queue-icon-btn danger" data-queue-stop-row="${escHtml(item?.id || '')}" title="생성 중단" aria-label="생성 중단"${stopLocked(item) ? ' disabled' : ''}>×</button>`
        : '<span class="queue-active-lock">current</span>')
      : `<button type="button" class="queue-icon-btn danger" data-queue-remove="${escHtml(item?.id || '')}" title="Remove from queue" aria-label="Remove from queue">×</button>`;
    return `
      <div class="queue-item${active ? ' active' : ''}">
        <div class="queue-item-main">
          <div class="queue-item-top">
            <span class="queue-item-label">${escHtml(labelForItem(item))}</span>
            <span class="queue-item-badges">${badges}</span>
          </div>
          <div class="queue-item-prompt">${escHtml(prompt)}</div>
          <div class="queue-item-meta">
            ${item?.negative_preview ? `<span>UC ${escHtml(item.negative_preview)}</span>` : ''}
            ${seed}
          </div>
        </div>
        ${remove}
      </div>`;
  }

  function bindRowActions() {
    root.querySelectorAll('[data-queue-remove]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        const requestId = button.getAttribute('data-queue-remove');
        if (requestId) performAction('remove', {request_id: requestId});
      });
    });
    root.querySelectorAll('[data-queue-stop-row]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        requestStop(button.getAttribute('data-queue-stop-row') || '');
      });
    });
  }

  function stopLocked(active) {
    return Boolean(active && stopSent && stopSent.id === String(active.id || ''));
  }

  // 지금 도는 그 장만 멈춘다 - 그 장의 id 를 싣는다(서버는 지금 도는 장과 같을 때만 멈춘다: A 가 끝나고 B 가 막 시작된 순간의
  // 누름이 B 를 멈추지 않게). 누르면 곧바로 잠그고(문구는 그대로), 풀거나 치우는 것은 서버의 queue_state 다(handleState).
  async function requestStop(rowId = '') {
    const active = shownActive(state);
    if (!active) return;
    const id = String(active.id || '');
    if (rowId && rowId !== id) return;            // 다시 그리기 전의 낡은 줄
    if (stopLocked(active)) return;               // 연타 - 한 번만 보낸다
    stopSent = {id};
    render();
    let data = {};
    try {
      const response = await fetchFn('/api/generation/cancel', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(id ? {request_id: id} : {}),
      });
      data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    } catch (error) {
      console.error('Generation stop failed', error);
      if (stopSent && stopSent.id === id) stopSent = null;
      render();
      showToast(error.message || 'Stop failed', 'error');
      return;
    }
    if (data.accepted !== false) return;          // 받았다 - 잠근 채로 서버의 queue_state 를 기다린다
    if (data.reason === 'not_running' || data.reason === 'idle') {
      // 그 장은 이미 끝났다 - 조용히 넘어가고 서버의 지금 상태를 받아 단추를 치운다.
      refresh();
      return;
    }
    // 멈출 수 없다(unsupported_mode 등) - 서버가 준 말을 알리고 단추를 푼다.
    if (stopSent && stopSent.id === id) stopSent = null;
    render();
    if (data.message) showToast(data.message, 'info');
  }

  function render() {
    const items = Array.isArray(state.items) ? state.items : [];
    const active = shownActive(state);
    const hasActive = Boolean(active);
    const pendingCount = Number(state.total ?? items.length) || items.length;
    const displayCount = pendingCount + (hasActive ? 1 : 0);
    root.hidden = !visibleState(state);
    root.classList.toggle('collapsed', collapsed);
    root.classList.toggle('paused', Boolean(state.paused));
    root.classList.toggle('has-stop', hasActive);
    if (stopBtn) {
      // 멈출 수 있는 도는 장이 있을 때만(shownActive = cancellable) - 접혀도 보인다(CSS 는 QSTOP_CSS)
      stopBtn.hidden = !hasActive;
      stopBtn.disabled = stopLocked(active);
    }
    if (title) title.textContent = 'Queue';
    if (countEl) countEl.textContent = String(displayCount);
    if (meta) {
      meta.textContent = state.paused
        ? `${pendingCount} paused`
        : hasActive
          ? `${pendingCount} waiting`
          : `${pendingCount} queued`;
    }
    if (pauseBtn) {
      pauseBtn.textContent = state.paused ? 'Resume' : 'Pause';
      pauseBtn.dataset.queueAction = state.paused ? 'resume' : 'pause';
      pauseBtn.disabled = !hasActive && !pendingCount && !state.paused;
    }
    if (clearBtn) clearBtn.disabled = pendingCount < 1;
    if (collapseBtn) {
      collapseBtn.textContent = collapsed ? '▴' : '▾';
      collapseBtn.setAttribute('aria-label', collapsed ? 'Expand queue' : 'Collapse queue');
      collapseBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
    if (!body) return;
    if (collapsed) {
      body.innerHTML = '';
      return;
    }

    const activeHtml = hasActive ? renderItem(active, {active: true}) : '';
    const pendingHtml = items.length
      ? items.map(item => renderItem(item)).join('')
      : `<div class="queue-empty">${Date.now() < holdVisibleUntil ? 'Waiting for queue update...' : 'No pending items'}</div>`;
    body.innerHTML = `${activeHtml}${pendingHtml}`;
    bindRowActions();
  }

  async function performAction(action, extra = {}) {
    try {
      const response = await fetchFn('/api/queue/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action, ...extra}),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      await refresh();
    } catch (error) {
      console.error('Queue action failed', error);
      showToast(error.message || 'Queue action failed', 'error');
    }
  }

  async function refresh() {
    try {
      const response = await fetchFn('/api/queue/state', {cache: 'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      handleState(await response.json());
    } catch (error) {
      console.warn('Queue state refresh failed', error);
    }
  }

  // 접힘은 사용자가 [▾] · 접힌 띠로만 바꾼다(사용자 지시 2026-10-21). 예전에는 패널이 숨었다가
  // 다시 나타날 때마다 펼쳤는데, 자동 생성은 한 장마다 큐가 1 -> 0 으로 비므로 매 장 펼쳐져
  // 결과 화면을 가렸다.
  function handleState(nextState = {}) {
    state = {
      ...state,
      ...nextState,
      items: Array.isArray(nextState.items) ? nextState.items : [],
    };
    // 서버가 보여 준다: 중단을 보낸 그 장이 더는 도는 장이 아니면(끝남 · 중단됨 · 다음 장) 잠금을 푼다.
    const runningNow = shownActive(state);
    if (stopSent && (!runningNow || String(runningNow.id || '') !== stopSent.id)) stopSent = null;
    const idleWaiting = state.items.length > 0 && !state.is_generating;
    if (!idleWaiting) {
      idleQueuedSince = 0;
      clearTimeout(graceTimer);
    } else if (!idleQueuedSince) {
      clearTimeout(graceTimer);
      if (!root.hidden) {
        // 이미 보이던 대기(생성 중에 쌓인 것)는 장과 장 사이 is_generating false 에서 숨기지 않는다(Codex 리뷰).
        idleQueuedSince = Date.now() - IDLE_QUEUE_GRACE_MS;
      } else {
        idleQueuedSince = Date.now();
        // 러너가 못 꺼내 가고 남아 있으면(막힘 · 대기) 그때는 보여 준다.
        graceTimer = setTimeout(render, IDLE_QUEUE_GRACE_MS + 20);
      }
    }
    render();
  }

  function wake() {
    holdVisibleUntil = Date.now() + 2500;
    // 접혀 있으면 펴지 않고 띠만 잠깐 또렷하게 - 큐에 들어갔다는 표시.
    root.classList.add('pulse');
    clearTimeout(pulseTimer);
    pulseTimer = setTimeout(() => root.classList.remove('pulse'), 2500);
    render();
    setTimeout(() => {
      if (Date.now() >= holdVisibleUntil) render();
    }, 2600);
  }

  function setCollapsed(next) {
    collapsed = next;
    render();
  }

  function init() {
    root.querySelectorAll('[data-queue-action]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        const action = button.dataset.queueAction;
        if (action) performAction(action);
      });
    });
    stopBtn?.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();   // 접힌 띠를 펴지 않는다
      requestStop();
    });
    if (collapseBtn) {
      collapseBtn.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        setCollapsed(!collapsed);
      });
    }
    // 접힌 띠는 어디를 눌러도 편다(캐릭터 퀵 패널 CHARACTER 머리와 같다).
    header?.addEventListener('click', event => {
      if (!collapsed || event.target.closest('button')) return;
      setCollapsed(false);
    });
    render();
  }

  return {
    init,
    refresh,
    handleState,
    wake,
  };
}
