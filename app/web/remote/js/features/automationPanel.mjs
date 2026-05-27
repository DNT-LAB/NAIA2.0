export function createAutomationPanel({
  document,
  setModuleParam,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;

  function onTypeChange(value) {
    setModuleParam('automation', 'auto_type', value);
    if (lastState) {
      lastState.auto_type = parseInt(value, 10);
      render(lastState);
    }
  }

  // Patch only the status line so the live countdown can tick without a full
  // re-render (which would steal focus from the inputs).
  function setLiveStatus(text) {
    const statusEl = moduleBody.querySelector('.mod-status');
    if (statusEl) statusEl.textContent = text || '';
  }

  function render(state) {
    lastState = state;
    const typeLabels = ['Unlimited', 'Timer', 'Count'];
    const typeRadios = typeLabels.map((label, index) =>
      `<label class="mod-checkbox-item">
        <input type="radio" name="autoType" value="${index}" ${state.auto_type === index ? 'checked' : ''} onchange="onAutoTypeChange(this.value)">
        <span class="mod-checkbox-label">${label}</span>
      </label>`
    ).join('');

    const isRunning = state.is_running;
    const isAvailable = state.available !== false;
    moduleBody.innerHTML = `
      <div>
        <div class="mod-section-label">Delay (seconds)</div>
        <div style="display:flex;gap:8px;align-items:center">
          <input class="mod-input" type="text" value="${state.delay || '0'}" onchange="setModuleParam('automation','delay',this.value)" style="flex:1">
          <label class="mod-checkbox-item" style="margin:0">
            <input type="checkbox" ${state.random_delay ? 'checked' : ''} oninput="setModuleParam('automation','random_delay',String(this.checked))">
            <span class="mod-checkbox-label">Random ±50%</span>
          </label>
        </div>
      </div>
      <div>
        <div class="mod-section-label">Repeat Count</div>
        <input class="mod-input" type="text" value="${state.repeat || '1'}" onchange="setModuleParam('automation','repeat',this.value)">
      </div>
      <div>
        <div class="mod-section-label">Termination</div>
        <div class="mod-checkbox-grid" style="grid-template-columns:1fr 1fr 1fr">${typeRadios}</div>
      </div>
      ${state.auto_type === 1 ? `<div>
        <div class="mod-section-label">Timer (minutes)</div>
        <input class="mod-input" type="text" value="${state.timer_minutes || '30'}" onchange="setModuleParam('automation','timer_minutes',this.value)">
      </div>` : ''}
      ${state.auto_type === 2 ? `<div>
        <div class="mod-section-label">Count Limit</div>
        <input class="mod-input" type="text" value="${state.count_limit || '100'}" onchange="setModuleParam('automation','count_limit',this.value)">
      </div>` : ''}
      <div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${state.notify ? 'checked' : ''} oninput="setModuleParam('automation','notify',String(this.checked))">
          <span class="mod-checkbox-label">Notify on completion</span>
        </label>
      </div>
      <div style="display:flex;gap:8px">
        <button class="mod-action-btn mod-start" ${isRunning || !isAvailable ? 'disabled' : ''} onclick="setModuleParam('automation','start','1')">Start</button>
        <button class="mod-action-btn mod-stop" ${!isRunning ? 'disabled' : ''} onclick="setModuleParam('automation','stop','1')">Stop</button>
      </div>
      <div class="mod-status">${state.status || ''}</div>
    `;
  }

  return {
    onTypeChange,
    render,
    setLiveStatus,
  };
}
