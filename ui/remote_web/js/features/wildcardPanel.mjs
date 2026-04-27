export function createWildcardPanel({
  document,
  escHtml,
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

    const stateHtml = state.state && state.state.length
      ? state.state.map(item => `<div>▶ ${escHtml(item.name)}: ${item.current} / ${item.total}</div>`).join('')
      : '<div class="mod-empty">No active sequential wildcards</div>';

    const instantHtml = state.instant_groups && state.instant_groups.length
      ? state.instant_groups.map(group => {
        const keys = (group.keys || []).map(key => escHtml(key)).join(', ');
        const more = group.count > 20
          ? ` <span style="color:var(--text-dim)">+${group.count - 20} more</span>`
          : '';
        return `<div class="mod-wc-group">
          <div class="mod-wc-group-header">$${escHtml(group.name)} <span style="color:var(--text-dim)">(${group.count})</span></div>
          <div class="mod-wc-group-keys">${keys}${more}</div>
        </div>`;
      }).join('')
      : '<div class="mod-empty">No instant wildcards</div>';

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
        <div class="mod-section-label">Instant Wildcards</div>
        <div class="mod-wc-instant">${instantHtml}</div>
      </div>
      <div class="mod-section">
        <label class="mod-check-row">
          <input type="checkbox" ${state.prompt_squeeze ? 'checked' : ''} oninput="setModuleParam('wildcard','prompt_squeeze',String(this.checked))">
          <span style="font-size:12px">NovelAI 403 Prevention</span>
        </label>
      </div>
      <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="mod-btn-sm" onclick="wcOpenBrowser()">Browse Files</button>
        <button class="mod-btn-sm" onclick="openModule('instant_wildcard')">Instant Editor</button>
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reset_sequential','')">Reset Seq</button>
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reload','')">Reload</button>
        <span style="color:var(--text-dim);font-size:11px;margin-left:auto">Loaded: ${state.wildcard_count || 0}</span>
      </div>
    `;
  }

  return {
    render,
  };
}
