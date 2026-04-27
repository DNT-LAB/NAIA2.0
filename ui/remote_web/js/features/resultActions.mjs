export function createResultActionsController({
  document,
  getWs,
  WebSocket,
  showToast,
}) {
  const button = document.getElementById('resultActionMenuBtn');
  let currentMeta = null;
  let menu = null;

  function canUse(action) {
    if (!currentMeta || currentMeta.history_id == null) return false;
    if (action === 'reroll') return !!currentMeta.has_source_row;
    if (action === 'enqueue_front' || action === 'enqueue_back') return !!currentMeta.has_gen_params;
    return true;
  }

  function updateButton() {
    if (!button) return;
    const enabled = !!(currentMeta && currentMeta.history_id != null);
    button.disabled = !enabled;
    button.title = enabled ? 'Result actions' : 'No generated result actions available';
  }

  function sendHistoryAction(action, useCurrentUi = false) {
    if (!canUse(action)) {
      showToast('Action is not available for this result.', 'error');
      return;
    }
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      showToast('Remote connection is not ready.', 'error');
      return;
    }
    ws.send(JSON.stringify({
      type: 'history_action',
      history_id: currentMeta.history_id,
      action,
      use_current_ui: !!useCurrentUi,
    }));
    close();
  }

  function renderMenu() {
    if (menu) menu.remove();
    menu = document.createElement('div');
    menu.className = 'result-actions-menu';
    menu.innerHTML = `
      <button type="button" data-action="load_prompt">Load Prompt</button>
      <button type="button" data-action="reroll">Reroll</button>
      <div class="result-actions-separator"></div>
      <button type="button" data-action="enqueue_front" data-current="0">Queue Front - Original</button>
      <button type="button" data-action="enqueue_front" data-current="1">Queue Front - Current UI</button>
      <button type="button" data-action="enqueue_back" data-current="0">Queue Back - Original</button>
      <button type="button" data-action="enqueue_back" data-current="1">Queue Back - Current UI</button>
    `;
    menu.querySelectorAll('button[data-action]').forEach(item => {
      const action = item.dataset.action;
      item.disabled = !canUse(action);
      item.addEventListener('click', () => {
        sendHistoryAction(action, item.dataset.current === '1');
      });
    });
    document.body.appendChild(menu);
  }

  function positionMenu() {
    if (!button || !menu) return;
    const rect = button.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.right - menuRect.width, window.innerWidth - menuRect.width - 8));
    const top = Math.min(rect.bottom + 6, window.innerHeight - menuRect.height - 8);
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
  }

  function open() {
    if (!button || button.disabled) return;
    renderMenu();
    menu.classList.add('open');
    positionMenu();
  }

  function close() {
    if (!menu) return;
    menu.remove();
    menu = null;
  }

  function toggle() {
    if (menu) close();
    else open();
  }

  function setCurrentMeta(meta) {
    currentMeta = meta || null;
    updateButton();
    if (menu) close();
  }

  function bind() {
    if (!button) return;
    document.addEventListener('mousedown', event => {
      if (!menu) return;
      if (menu.contains(event.target) || button.contains(event.target)) return;
      close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
    });
    window.addEventListener('resize', () => {
      if (menu) positionMenu();
    });
    updateButton();
  }

  return {
    bind,
    setCurrentMeta,
    toggle,
    close,
  };
}
