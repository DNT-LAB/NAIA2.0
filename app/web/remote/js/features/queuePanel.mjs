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
  const STORAGE_KEY = 'naia_queue_panel_collapsed';
  let state = {active: null, items: [], paused: false, total: 0, is_generating: false};
  let collapsed = localStorage.getItem(STORAGE_KEY) === '1';
  let holdVisibleUntil = 0;

  function visibleState(nextState) {
    return Boolean(
      nextState?.active
      || (Array.isArray(nextState?.items) && nextState.items.length)
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
    if (title) title.textContent = collapsed ? `Queue ${displayCount}` : 'Queue';
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
    if (collapseBtn) collapseBtn.textContent = collapsed ? '▴' : '▾';
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

  function handleState(nextState = {}) {
    const wasHidden = root.hidden;
    const nextVisible = visibleState(nextState);
    if (wasHidden && nextVisible) {
      collapsed = false;
      localStorage.setItem(STORAGE_KEY, '0');
    }
    state = {
      ...state,
      ...nextState,
      items: Array.isArray(nextState.items) ? nextState.items : [],
    };
    render();
  }

  function wake() {
    holdVisibleUntil = Date.now() + 2500;
    collapsed = false;
    localStorage.setItem(STORAGE_KEY, '0');
    render();
    setTimeout(() => {
      if (Date.now() >= holdVisibleUntil) render();
    }, 2600);
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
        collapsed = !collapsed;
        localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0');
        render();
      });
    }
    render();
  }

  return {
    init,
    refresh,
    handleState,
    wake,
  };
}
