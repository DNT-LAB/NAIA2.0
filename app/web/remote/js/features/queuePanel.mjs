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

  function visibleState(nextState) {
    const waiting = Array.isArray(nextState?.items) && nextState.items.length > 0;
    return Boolean(
      nextState?.active
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
    const remove = active
      ? '<span class="queue-active-lock">current</span>'
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
  }

  function render() {
    const items = Array.isArray(state.items) ? state.items : [];
    const hasActive = Boolean(state.active);
    const pendingCount = Number(state.total ?? items.length) || items.length;
    const displayCount = pendingCount + (hasActive ? 1 : 0);
    root.hidden = !visibleState(state);
    root.classList.toggle('collapsed', collapsed);
    root.classList.toggle('paused', Boolean(state.paused));
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

    const activeHtml = hasActive ? renderItem(state.active, {active: true}) : '';
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
