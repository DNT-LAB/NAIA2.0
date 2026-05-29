export function createWildcardPanel({
  document,
  escHtml,
  renderInlineBrowser,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

  function renderHistory(state) {
    return state.history && state.history.length
      ? state.history.map(item => {
        const name = escHtml(item.name);
        const value = escHtml(item.value);
        return `<div>▶ ${name}: ${value}</div>`;
      }).join('')
      : '<div class="mod-empty">No wildcards used</div>';
  }

  function renderSeqState(state) {
    const seqState = state.sequential_state || state.state;
    return seqState && seqState.length
      ? seqState.map(item => {
        const dep = item.master ? ` <span style="color:var(--text-dim)">(↳ $${escHtml(item.master)})</span>` : '';
        return `<div>▶ ${escHtml(item.name)}: ${item.current} / ${item.total}${dep}</div>`;
      }).join('')
      : '<div class="mod-empty">No active sequential wildcards</div>';
  }

  function render(state) {
    const historyEl = moduleBody.querySelector('.mod-wc-history');
    const stateEl = moduleBody.querySelector('.mod-wc-state');
    // 라이브 틱(state.live_update)이고 구조가 이미 있으면 런타임 섹션만 in-place 갱신한다.
    // 파일 브라우저를 통째로 재구축하면 매 생성마다 get_file_tree 재요청 + 깜빡임이
    // 발생하므로 보존. 열기/reload 등 마커 없는 갱신은 아래 full rebuild 경로를 탄다
    // (Reload 버튼이 트리를 새로고침하던 기존 동작 유지).
    if (state.live_update && historyEl && stateEl) {
      historyEl.innerHTML = renderHistory(state);
      stateEl.innerHTML = renderSeqState(state);
      const loadedEl = moduleBody.querySelector('.mod-wc-loaded');
      if (loadedEl) loadedEl.textContent = `Loaded: ${state.wildcard_count || 0}`;
      const squeezeEl = moduleBody.querySelector('.mod-wc-squeeze');
      if (squeezeEl) squeezeEl.checked = !!state.prompt_squeeze;
      return;
    }

    moduleBody.innerHTML = `
      <div class="mod-section">
        <div class="mod-section-label">Used Wildcards</div>
        <div class="mod-wc-history">${renderHistory(state)}</div>
      </div>
      <div class="mod-section">
        <div class="mod-section-label">Sequential / Dependent State</div>
        <div class="mod-wc-state">${renderSeqState(state)}</div>
      </div>
      <div class="mod-section">
        <div class="mod-section-label">Browse Files</div>
        <div class="mod-wc-browser-inline" id="wcInlineBrowser">
          <div class="mod-empty">Loading wildcard files...</div>
        </div>
      </div>
      <div class="mod-section">
        <label class="mod-check-row">
          <input type="checkbox" class="mod-wc-squeeze" ${state.prompt_squeeze ? 'checked' : ''} oninput="setModuleParam('wildcard','prompt_squeeze',String(this.checked))">
          <span style="font-size:12px">NovelAI 403 Prevention</span>
        </label>
      </div>
      <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reset_sequential','')">Reset Seq</button>
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','reload','')">Reload</button>
        <span class="mod-wc-loaded" style="color:var(--text-dim);font-size:11px;margin-left:auto">Loaded: ${state.wildcard_count || 0}</span>
      </div>
    `;
    renderInlineBrowser?.();
  }

  return {
    render,
  };
}
