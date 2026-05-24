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
        ? '검색 결과가 없습니다.<br><span style="font-size:10px">먼저 검색을 실행하세요</span>'
        : '심층 검색 데이터 준비 중...';
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
        <div class="mod-section-label">표시된 행</div>
        <div class="search-count-display" style="font-size:18px">${message.count || 0}</div>
      </div>
      <div>
        <div class="mod-section-label">원본 행</div>
        <div class="search-count-display" style="font-size:18px;color:var(--text-muted)">${message.original || 0}</div>
      </div>
    </div>
    <div>
      <div class="mod-section-label">검색 키워드</div>
      <input class="mod-input" id="depthQuery" type="text" value="${escHtml(message.query)}" placeholder="검색 태그...">
    </div>
    <div>
      <div class="mod-section-label">제외 키워드</div>
      <input class="mod-input" id="depthExclude" type="text" value="${escHtml(message.exclude)}" placeholder="제외 태그...">
    </div>
    <div>
      <div class="mod-section-label">등급</div>
      <div class="mod-checkbox-grid">
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_e" ${ratings.e?'checked':''}><span class="mod-checkbox-label">Explicit</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_q" ${ratings.q?'checked':''}><span class="mod-checkbox-label">NSFW</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_s" ${ratings.s?'checked':''}><span class="mod-checkbox-label">Sensitive</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_g" ${ratings.g?'checked':''}><span class="mod-checkbox-label">General</span></label>
      </div>
    </div>
    <div class="mod-section-label" style="margin-top:4px">숫자 필터</div>
    <div class="depth-filter-grid">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_min" ${ck('token_min',false)?'checked':''}><span class="mod-checkbox-label">토큰 \u2265</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_min" type="number" value="${fv('token_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_max" ${ck('token_max',false)?'checked':''}><span class="mod-checkbox-label">토큰 \u2264</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_max" type="number" value="${fv('token_max','150')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_min" ${ck('id_min',false)?'checked':''}><span class="mod-checkbox-label">ID \u2265</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_min" type="number" value="${fv('id_min','0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_max" ${ck('id_max',false)?'checked':''}><span class="mod-checkbox-label">ID \u2264</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_max" type="number" value="${fv('id_max','99999999')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_score_min" ${ck('score_min',false)?'checked':''}><span class="mod-checkbox-label">Score \u2265</span></label>
      <input class="mod-input mod-input-sm" id="dfv_score_min" type="number" value="${fv('score_min','0')}">
    </div>
    <div class="mod-checkbox-grid" style="margin-top:4px">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_rem_char" ${filters.rem_char?'checked':''}><span class="mod-checkbox-label">캐릭터명 없는 행 제외</span></label>
      <label class="mod-checkbox-item"><input type="checkbox" id="df_only_empty_char" ${filters.only_empty_char?'checked':''}><span class="mod-checkbox-label">캐릭터명 없는 행만 검색</span></label>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
      <button class="mod-action-btn mod-start" style="flex:1" onclick="depthFilter()">결과 내 재검색</button>
      <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('restore')">초기 상태로 복원</button>
    </div>
    <button class="mod-action-btn mod-refine" style="width:100%" onclick="depthAction('refresh_from_main')" title="현재 메인 검색 결과를 심층검색 원본 행으로 다시 불러오기">메인 검색 결과로 새로고침</button>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button class="mod-action-btn mod-start" style="flex:1;background:var(--accent)" onclick="depthAction('assign')">현재 결과를 메인에 할당</button>
      <button class="mod-action-btn mod-refine" style="flex:1" onclick="depthAction('promote')" title="현재 검색 결과를 원본 행으로 설정">현재 검색 결과를 원본 행으로</button>
    </div>
    <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')" style="margin-top:6px">
      스테이징 & 내보내기 <span class="mod-collapse-arrow">\u25B6</span>
    </div>
    <div class="collapsed" style="display:flex;flex-direction:column;gap:6px">
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('stage')">+ 스테이징에 추가</button>
        <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)">스테이징: <span class="depth-staging-count">${message.staging_count||0}</span></span>
      </div>
      <div style="display:flex;gap:6px">
        <button class="mod-action-btn" style="flex:1" onclick="depthAction('merge_staging')">스테이징 병합 → 현재 뷰</button>
        <button class="mod-action-btn mod-restore" style="flex:1" onclick="depthAction('clear_staging')">스테이징 초기화</button>
      </div>
      <button class="mod-action-btn" style="width:100%" onclick="depthAction('export')">현재 뷰 내보내기 (.parquet)</button>
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
