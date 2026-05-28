export function createWildcardPanel({
  document,
  escHtml,
  renderInlineBrowser,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

  function render(state) {
    const historyHtml = state.history && state.history.length
      ? state.history.map(item => {
        const name = escHtml(item.name);
        const value = escHtml(item.value);
        return `<div>▶ ${name}: ${value}</div>`;
      }).join('')
      : '<div class="mod-empty">No wildcards used</div>';

    const seqState = state.sequential_state || state.state;
    const stateHtml = seqState && seqState.length
      ? seqState.map(item => {
        const dep = item.master ? ` <span style="color:var(--text-dim)">(↳ $${escHtml(item.master)})</span>` : '';
        return `<div>▶ ${escHtml(item.name)}: ${item.current} / ${item.total}${dep}</div>`;
      }).join('')
      : '<div class="mod-empty">No active sequential wildcards</div>';

    moduleBody.innerHTML = `
      <div class="mod-section">
        <div class="mod-section-label">Used Wildcards</div>
        <div class="mod-wc-history">${historyHtml}</div>
      </div>
      <div class="mod-section">
        <div class="mod-section-label">Sequential / Dependent State</div>
        <div class="mod-wc-state">${stateHtml}</div>
      </div>
      <div class="mod-section">
        <div class="mod-section-label">Browse Files</div>
        <div class="mod-wc-browser-inline" id="wcInlineBrowser">
          <div class="mod-empty">Loading wildcard files...</div>
        </div>
      </div>
      <div class="mod-section">
        <label class="mod-check-row">
          <input type="checkbox" ${state.prompt_squeeze ? 'checked' : ''} oninput="setModuleParam('wildcard','prompt_squeeze',String(this.checked))">
          <span style="font-size:12px">NovelAI 403 Prevention</span>
        </label>
      </div>
      <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reset_sequential','')">Reset Seq</button>
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reload','')">Reload</button>
        <span style="color:var(--text-dim);font-size:11px;margin-left:auto">Loaded: ${state.wildcard_count || 0}</span>
      </div>
    `;
    renderInlineBrowser?.();
  }

  return {
    render,
  };
}
