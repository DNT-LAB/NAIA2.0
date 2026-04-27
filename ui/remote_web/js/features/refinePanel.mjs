export function createRefinePanel({
  document,
  panel,
  modulePopup,
  escHtml,
  getWs,
  WebSocket,
  closeAuxiliaryPopups,
  positionFloatingPanel,
}) {
  let open = false;

  function openPanel() {
    if (open) {
      close();
      return;
    }
    closeAuxiliaryPopups(panel);
    open = true;
    panel.classList.add('open');
    positionFloatingPanel(panel, modulePopup);
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'get_depth_state' }));
      ws.send(JSON.stringify({ type: 'depth_action', action: 'open' }));
    }
  }

  function close() {
    open = false;
    panel.classList.remove('open');
  }

  function onDepthState(message) {
    if (!open) return;
    if (!message.open) {
      const msg = message.error === 'no_search_results'
        ? 'No search results loaded.<br><span style="font-size:10px">Run a search first</span>'
        : 'Preparing data...';
      panel.querySelector('.refine-body').innerHTML =
        `<div style="text-align:center;color:var(--text-dim);padding:20px">${msg}</div>`;
      return;
    }

    const body = panel.querySelector('.refine-body');
    const existing = body.querySelector('#depthQuery');
    if (existing) {
      const counts = body.querySelectorAll('.search-count-display');
      if (counts[0]) counts[0].textContent = message.count || 0;
      if (counts[1]) counts[1].textContent = message.original || 0;
      const stagingCount = body.querySelector('.depth-staging-count');
      if (stagingCount) stagingCount.textContent = message.staging_count || 0;
      return;
    }

    const ratings = message.ratings || { e: true, q: true, s: true, g: true };
    const filters = message.filters || {};
    const ck = (name, fallback) => {
      const value = filters[name];
      return value ? value.enabled : fallback;
    };
    const fv = (name, fallback) => {
      const value = filters[name];
      return value ? escHtml(value.value) : fallback;
    };

    body.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Filtered</div>
        <div class="search-count-display" style="font-size:18px">${message.count || 0}</div>
      </div>
      <div>
        <div class="mod-section-label">Original</div>
        <div class="search-count-display" style="font-size:18px;color:var(--text-muted)">${message.original || 0}</div>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Filter Tags</div>
      <input class="mod-input" id="depthQuery" type="text" value="${escHtml(message.query)}" placeholder="filter tags...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Tags</div>
      <input class="mod-input" id="depthExclude" type="text" value="${escHtml(message.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_e" ${ratings.e?'checked':''}><span class="mod-checkbox-label">E</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_q" ${ratings.q?'checked':''}><span class="mod-checkbox-label">Q</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_s" ${ratings.s?'checked':''}><span class="mod-checkbox-label">S</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_g" ${ratings.g?'checked':''}><span class="mod-checkbox-label">G</span></label>
      </div>
    </div>
    <div class="mod-section-label" style="margin-top:4px">Numeric Filters</div>
    <div class="depth-filter-grid">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_min" ${ck('token_min',false)?'checked':''}><span class="mod-checkbox-label">Tokens \u2265</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_min" type="number" value="${fv('token_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_max" ${ck('token_max',false)?'checked':''}><span class="mod-checkbox-label">Tokens \u2264</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_max" type="number" value="${fv('token_max','150')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_min" ${ck('id_min',false)?'checked':''}><span class="mod-checkbox-label">ID \u2265</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_min" type="number" value="${fv('id_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_max" ${ck('id_max',false)?'checked':''}><span class="mod-checkbox-label">ID \u2264</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_max" type="number" value="${fv('id_max','99999999')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_score_min" ${ck('score_min',false)?'checked':''}><span class="mod-checkbox-label">Score \u2265</span></label>
      <input class="mod-input mod-input-sm" id="dfv_score_min" type="number" value="${fv('score_min','0')}">
    </div>
    <div class="mod-checkbox-grid" style="margin-top:4px">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_rem_char" ${filters.rem_char?'checked':''}><span class="mod-checkbox-label">Has Character</span></label>
      <label class="mod-checkbox-item"><input type="checkbox" id="df_only_empty_char" ${filters.only_empty_char?'checked':''}><span class="mod-checkbox-label">No Character</span></label>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
      <button class="mod-action-btn mod-start" style="flex:1" onclick="depthFilter()">Filtered Search</button>
      <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('restore')">Restore</button>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="mod-action-btn mod-start" style="flex:1;background:var(--accent)" onclick="depthAction('assign')">Assign to Main</button>
      <button class="mod-action-btn mod-refine" style="flex:1" onclick="depthAction('promote')" title="Set current filtered results as the new baseline">Set as Baseline</button>
    </div>
    <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')" style="margin-top:6px">
      Staging & Export <span class="mod-collapse-arrow">\u25B6</span>
    </div>
    <div class="collapsed" style="display:flex;flex-direction:column;gap:6px">
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('stage')">+ Stage Current</button>
        <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)">Staged: <span class="depth-staging-count">${message.staging_count||0}</span></span>
      </div>
      <div style="display:flex;gap:6px">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('merge_staging')">Merge Staged</button>
        <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('clear_staging')">Clear</button>
      </div>
      <button class="mod-action-btn" style="width:100%" onclick="depthAction('export')">Export to Custom Parquet</button>
    </div>
  `;
  }

  function depthFilter() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const byId = id => document.getElementById(id);
    const query = (byId('depthQuery') || {}).value || '';
    const exclude = (byId('depthExclude') || {}).value || '';
    const ratings = {};
    for (const key of ['e','q','s','g']) {
      const element = byId('dr_' + key);
      ratings[key] = element ? element.checked : true;
    }
    const filters = {};
    for (const name of ['token_min','token_max','id_min','id_max','score_min']) {
      const check = byId('df_' + name);
      const input = byId('dfv_' + name);
      if (check && input) filters[name] = { enabled: check.checked, value: input.value };
    }
    filters.rem_char = (byId('df_rem_char') || {}).checked || false;
    filters.only_empty_char = (byId('df_only_empty_char') || {}).checked || false;
    ws.send(JSON.stringify({ type: 'depth_action', action: 'filter', query, exclude, ratings, filters }));
  }

  function depthAction(action) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'depth_action', action }));
  }

  function isOpen() {
    return open;
  }

  return {
    open: openPanel,
    close,
    onDepthState,
    depthFilter,
    depthAction,
    isOpen,
  };
}
