// Refine (심층검색) — tab view inside the module popup.
// Not a separate floating panel anymore: clicking 심층검색 in the Search panel
// switches the SAME module-popup surface into refine-mode (app.js toggles the
// `.refine-mode` class on #modulePopup, hiding the search body + popup header and
// revealing #refineView). The `[← SEARCH]` button switches back. On wide screens
// the body is a 2-column layout: left = counts + the full-label refine controls +
// a separated action island; right = the sample preview slot, a staging board
// (each staged item labelled by its 검색|제외 pair, Dev0714 model) and a
// merge/export island.
export function createRefinePanel({
  document,
  container,
  escHtml,
  getWs,
  WebSocket,
  enterMode,
  exitMode,
}) {
  let open = false;
  let lastSample = null;
  let lastViewCount = null;

  function send(payload) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }

  function openPanel() {
    if (open) { close(); return; }
    open = true;
    if (typeof enterMode === 'function') enterMode();
    ensureRefineStyle();
    renderShell();
    send({ type: 'get_depth_state' });
    send({ type: 'depth_action', action: 'open' });
  }

  // [← SEARCH] — leave refine-mode, back to the Search panel.
  function close() {
    if (!open) return;
    open = false;
    if (typeof exitMode === 'function') exitMode();
  }

  function isOpen() {
    return open;
  }

  // Render the static shell (header + 2-col scaffold + preview + staging islands)
  // once. The left column (counts + controls + action island) is filled by
  // onDepthState; the staging list by renderStagingBoard; the preview by onDepthSample.
  function renderShell() {
    if (container.querySelector('.refine-header')) return;
    container.innerHTML = `
    <div class="refine-header">
      <button type="button" class="refine-back" onclick="refineBack()">← SEARCH</button>
      <span class="refine-title">심층검색</span>
    </div>
    <div class="refine-2col">
      <div class="refine-left"></div>
      <div class="refine-right">
        <div class="refine-preview">
          <div class="rf-prev-head">
            <span class="mod-section-label">샘플 미리보기</span>
            <span class="rf-prev-actions">
              <button type="button" class="rf-sample-btn" onclick="refineSample()">무작위 샘플</button>
              <button type="button" class="rf-gen-btn" onclick="refineGenerate()">생성</button>
            </span>
          </div>
          <div class="rf-prev-body rf-prev-empty">무작위 샘플을 뽑아 결과셋을 들여다보세요.</div>
        </div>
        <div class="refine-stageboard">
          <div class="rf-staging-head">
            <span class="mod-section-label">스테이징</span>
            <span class="rf-staging-badge">staged <b class="depth-staging-count">0</b></span>
          </div>
          <button class="mod-action-btn mod-start rf-stage-add" onclick="depthAction('stage')">＋ 현재 뷰를 스테이징에 추가</button>
          <div class="rf-stage-list"></div>
        </div>
        <div class="refine-staging">
          <div class="mod-section-label">병합 &amp; 내보내기</div>
          <div class="rf-stage-grid">
            <button class="mod-action-btn" onclick="depthAction('merge_staging')">병합 → 현재 뷰</button>
            <button class="mod-action-btn mod-restore" onclick="depthAction('clear_staging')">스테이징 초기화</button>
          </div>
          <button class="mod-action-btn rf-stage-export" onclick="depthAction('export')">현재 뷰 내보내기 (.parquet)</button>
        </div>
      </div>
    </div>`;
  }

  function onDepthState(message) {
    if (!open) return;
    renderShell();
    if (!message.open) {
      const left = container.querySelector('.refine-left');
      const msg = message.error === 'no_search_results'
        ? '검색 결과가 없습니다.<br><span style="font-size:10px">먼저 검색을 실행하세요</span>'
        : '심층 검색 데이터 준비 중...';
      if (left) left.innerHTML = `<div style="text-align:center;color:var(--text-dim);padding:20px">${msg}</div>`;
      renderStagingBoard([], 0);
      return;
    }

    maybeInvalidateSample(message.count || 0);

    // Build the controls once; afterwards counts + staging are patched in place.
    if (container.querySelector('#depthQuery')) {
      setCounts(message.count || 0, message.original || 0);
      renderStagingBoard(message.staging || [], message.staging_count || 0);
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

    const left = container.querySelector('.refine-left');
    left.innerHTML = `
    <div class="search-top-row rf-counts">
      <div>
        <div class="mod-section-label">표시된 행 <button type="button" class="refine-sync" onclick="depthAction('refresh_from_main')" title="현재 메인 검색 결과를 심층검색 원본으로 다시 불러오기"><span class="rf-sync-icon">⟳</span> 검색 동기화</button></div>
        <div class="search-count-display rf-count">${message.count || 0}</div>
      </div>
      <div>
        <div class="mod-section-label">원본 행</div>
        <div class="search-count-display rf-original">${message.original || 0}</div>
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
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_e" ${ratings.e ? 'checked' : ''}><span class="mod-checkbox-label">Explicit</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_q" ${ratings.q ? 'checked' : ''}><span class="mod-checkbox-label">NSFW</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_s" ${ratings.s ? 'checked' : ''}><span class="mod-checkbox-label">Sensitive</span></label>
        <label class="mod-checkbox-item"><input type="checkbox" id="dr_g" ${ratings.g ? 'checked' : ''}><span class="mod-checkbox-label">General</span></label>
      </div>
    </div>
    <div class="mod-section-label" style="margin-top:4px">숫자 필터</div>
    <div class="depth-filter-grid">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_min" ${ck('token_min', false) ? 'checked' : ''}><span class="mod-checkbox-label">토큰 ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_min" type="number" value="${fv('token_min', '0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_token_max" ${ck('token_max', false) ? 'checked' : ''}><span class="mod-checkbox-label">토큰 ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_token_max" type="number" value="${fv('token_max', '150')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_min" ${ck('id_min', false) ? 'checked' : ''}><span class="mod-checkbox-label">ID ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_min" type="number" value="${fv('id_min', '0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_id_max" ${ck('id_max', false) ? 'checked' : ''}><span class="mod-checkbox-label">ID ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_id_max" type="number" value="${fv('id_max', '99999999')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_score_min" ${ck('score_min', false) ? 'checked' : ''}><span class="mod-checkbox-label">Score ≥</span></label>
      <input class="mod-input mod-input-sm" id="dfv_score_min" type="number" value="${fv('score_min', '0')}">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_score_max" ${ck('score_max', false) ? 'checked' : ''}><span class="mod-checkbox-label">Score ≤</span></label>
      <input class="mod-input mod-input-sm" id="dfv_score_max" type="number" value="${fv('score_max', '999999')}">
    </div>
    <div class="mod-checkbox-grid" style="margin-top:4px">
      <label class="mod-checkbox-item"><input type="checkbox" id="df_rem_char" ${filters.rem_char ? 'checked' : ''}><span class="mod-checkbox-label">캐릭터명 없는 행 제외</span></label>
      <label class="mod-checkbox-item"><input type="checkbox" id="df_only_empty_char" ${filters.only_empty_char ? 'checked' : ''}><span class="mod-checkbox-label">캐릭터명 없는 행만 검색</span></label>
    </div>
    <div class="refine-actions-island">
      <div class="rf-act-row">
        <button class="mod-action-btn mod-start" onclick="depthFilter()">결과 내 재검색</button>
        <button class="mod-action-btn mod-restore" onclick="depthAction('restore')">초기 상태로 복원</button>
      </div>
      <div class="rf-act-divider"></div>
      <button class="mod-action-btn mod-start rf-assign" onclick="depthAction('assign')">현재 결과를 메인에 할당</button>
      <button class="mod-action-btn mod-refine rf-promote" onclick="depthAction('promote')" title="현재 검색 결과를 원본 행으로 설정">현재 검색 결과를 원본 행으로</button>
    </div>`;

    renderStagingBoard(message.staging || [], message.staging_count || 0);
  }

  // Staging board: each staged item shown as its 검색 | 제외 keyword pair + row count.
  function renderStagingBoard(items, totalCount) {
    setStagingCount(totalCount);
    const listEl = container.querySelector('.rf-stage-list');
    if (!listEl) return;
    const list = Array.isArray(items) ? items : [];
    if (!list.length) {
      listEl.innerHTML = '<div class="rf-stage-empty">현재 뷰를 스테이징에 추가해 서로 다른 검색 결과를 누적·합칠 수 있습니다.</div>';
      return;
    }
    const tag = (value) => {
      const text = String(value || '').trim();
      return text ? escHtml(text) : '<span class="rf-stage-dim">—</span>';
    };
    listEl.innerHTML = list.map((item, index) => `
      <div class="rf-stage-item">
        <span class="rf-stage-idx">${index + 1}</span>
        <span class="rf-stage-pair">
          <span class="rf-stage-field"><span class="rf-stage-tag">검색</span>${tag(item.query)}</span>
          <span class="rf-stage-sep">|</span>
          <span class="rf-stage-field"><span class="rf-stage-tag">제외</span>${tag(item.exclude)}</span>
        </span>
        <span class="rf-stage-count">${Number(item.count || 0).toLocaleString()}</span>
      </div>`).join('');
  }

  function setCounts(count, original) {
    const c = container.querySelector('.rf-count');
    const o = container.querySelector('.rf-original');
    if (c) c.textContent = count;
    if (o) o.textContent = original;
  }

  function setStagingCount(count) {
    const el = container.querySelector('.depth-staging-count');
    if (el) el.textContent = count;
  }

  // The sample preview belongs to the view it was drawn from. When the displayed
  // (표시된 행) count changes — filter / restore / 검색 동기화 / merge — the shown
  // sample may no longer be in the current view, so clear it. (Sampling itself
  // does not change the count, so re-sampling never triggers this.)
  function maybeInvalidateSample(count) {
    if (lastViewCount !== null && count !== lastViewCount && lastSample) {
      lastSample = null;
      const body = container.querySelector('.rf-prev-body');
      if (body) {
        body.classList.add('rf-prev-empty');
        body.innerHTML = '표시된 행이 바뀌었습니다 — 무작위 샘플을 다시 뽑아보세요.';
      }
    }
    lastViewCount = count;
  }

  // Preview slot: one sampled row, replaced on each [무작위 샘플] press.
  function onDepthSample(message) {
    if (!open) return;
    const body = container.querySelector('.rf-prev-body');
    if (!body) return;
    if (!message || message.ok === false) {
      lastSample = null;
      body.classList.add('rf-prev-empty');
      body.innerHTML = message && message.reason === 'empty'
        ? '결과셋이 비어 있어 샘플을 뽑을 수 없습니다.'
        : '샘플을 가져오지 못했습니다.';
      return;
    }
    lastSample = message;
    body.classList.remove('rf-prev-empty');
    const field = (label, value, cls) =>
      `<div class="rf-field ${cls || ''}"><span class="rf-field-key">${label}</span><span class="rf-field-val">${escHtml(String(value ?? ''))}</span></div>`;
    body.innerHTML = `
      ${field('id', message.id, 'rf-mono')}
      ${field('아티스트', message.artist)}
      ${field('캐릭터', message.character)}
      ${field('작품', message.copyright)}
      <div class="rf-field rf-field-block">
        <span class="rf-field-key">General</span>
        <div class="rf-general">${escHtml(String(message.general ?? ''))}</div>
      </div>`;
  }

  function refineSample() {
    send({ type: 'depth_action', action: 'sample' });
  }

  function refineGenerate() {
    send({ type: 'depth_generate' });
  }

  function depthFilter() {
    const byId = id => document.getElementById(id);
    const query = (byId('depthQuery') || {}).value || '';
    const exclude = (byId('depthExclude') || {}).value || '';
    const ratings = {};
    for (const key of ['e', 'q', 's', 'g']) {
      const element = byId('dr_' + key);
      ratings[key] = element ? element.checked : true;
    }
    const filters = {};
    for (const name of ['token_min', 'token_max', 'id_min', 'id_max', 'score_min', 'score_max']) {
      const check = byId('df_' + name);
      const input = byId('dfv_' + name);
      if (check && input) filters[name] = { enabled: check.checked, value: input.value };
    }
    filters.rem_char = (byId('df_rem_char') || {}).checked || false;
    filters.only_empty_char = (byId('df_only_empty_char') || {}).checked || false;
    send({ type: 'depth_action', action: 'filter', query, exclude, ratings, filters });
  }

  function depthAction(action) {
    send({ type: 'depth_action', action });
  }

  function ensureRefineStyle() {
    if (document.getElementById('refine-tab-style')) return;
    const css = `
.module-popup.refine-mode{width:96vw;max-width:96vw}
@media(min-width:768px){.module-popup.refine-mode{width:min(720px,calc(100vw - 516px));max-width:none}}
.module-popup.refine-mode > .module-popup-header,
.module-popup.refine-mode > #modulePopupBody{display:none}
#refineView{display:none;flex-direction:column;gap:10px;padding:12px 14px 14px}
.module-popup.refine-mode > #refineView{display:flex}
.refine-header{display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border,#2a2a33);padding-bottom:8px}
.refine-back{background:var(--bg-elevated,#2a2a33);color:var(--text,#e8e8ee);border:1px solid var(--border,#33333f);border-radius:6px;padding:5px 11px;font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap}
.refine-back:hover{border-color:var(--accent-blue,#8d7bd6);color:var(--accent-blue,#8d7bd6)}
.refine-title{font-size:14px;font-weight:700;color:var(--text,#e8e8ee)}
.refine-2col{display:flex;gap:14px;align-items:flex-start}
.refine-left{flex:1 1 50%;min-width:0;display:flex;flex-direction:column;gap:8px}
.refine-right{flex:1 1 50%;min-width:0;display:flex;flex-direction:column;gap:10px}
.rf-counts .mod-section-label{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.refine-sync{display:inline-flex;align-items:center;gap:4px;background:var(--bg,#15151b);border:1px solid var(--border,#33333f);border-radius:999px;padding:2px 9px;color:var(--text-dim,#888);cursor:pointer;font-size:10px;font-weight:600;line-height:1.4;white-space:nowrap}
.refine-sync:hover{border-color:var(--accent-green,#5a9e6f);color:var(--accent-green,#5a9e6f)}
.rf-sync-icon{font-size:12px}
.rf-counts .rf-original{color:var(--text-muted,#aaa)}
/* Preview slot */
.refine-preview{border:1px solid var(--border,#2a2a33);border-radius:10px;background:var(--bg-elevated,#21212a);padding:10px}
.rf-prev-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.rf-prev-head .mod-section-label{margin:0}
.rf-prev-actions{display:flex;gap:6px;flex:0 0 auto}
.rf-sample-btn,.rf-gen-btn{height:28px;line-height:1;padding:0 13px;font-size:11px;font-weight:600;border-radius:6px;cursor:pointer;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--border,#33333f)}
.rf-sample-btn{background:var(--bg,#15151b);color:var(--text,#e8e8ee)}
.rf-sample-btn:hover{border-color:var(--accent-blue,#8d7bd6);color:var(--accent-blue,#8d7bd6)}
.rf-gen-btn{background:var(--accent-green,#5a9e6f);color:#0f1a12;border-color:transparent}
.rf-gen-btn:hover{filter:brightness(1.08)}
.rf-prev-body{font-size:12px;color:var(--text,#e8e8ee);display:flex;flex-direction:column;gap:5px;min-height:120px}
.rf-prev-body.rf-prev-empty{align-items:center;justify-content:center;text-align:center;color:var(--text-dim,#888);font-size:11px}
.rf-field{display:flex;gap:8px;align-items:baseline}
.rf-field-key{flex:0 0 56px;color:var(--text-dim,#888);font-size:10px;text-transform:uppercase;letter-spacing:.03em}
.rf-field-val{flex:1;min-width:0;color:var(--text,#e8e8ee);word-break:break-word}
.rf-field.rf-mono .rf-field-val{font-family:var(--font-mono,monospace)}
.rf-field-block{flex-direction:column;gap:3px}
.rf-general{max-height:150px;overflow:auto;background:var(--bg,#15151b);border:1px solid var(--border,#2a2a33);border-radius:6px;padding:7px 8px;font-size:11px;line-height:1.5;color:var(--text-muted,#cfcfd6);white-space:pre-wrap;word-break:break-word}
/* Action island (재검색/복원 · 할당/원본으로) — separated from the filter inputs above */
.refine-actions-island{border:1px solid var(--border,#2a2a33);border-radius:10px;background:var(--bg-elevated,#21212a);padding:10px;display:flex;flex-direction:column;gap:7px;margin-top:4px}
.rf-act-row{display:flex;gap:6px}
.rf-act-row .mod-action-btn{flex:1}
.rf-act-divider{height:1px;background:var(--border,#2a2a33);margin:1px 0}
.rf-assign,.rf-promote{width:100%}
.rf-assign{background:var(--accent,var(--accent-blue,#8d7bd6))}
/* Staging board (Dev0714 검색|제외 pairs) */
.refine-stageboard{border:1px solid var(--border,#2a2a33);border-radius:10px;background:var(--bg-elevated,#21212a);padding:10px;display:flex;flex-direction:column;gap:8px}
.rf-staging-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
.rf-staging-head .mod-section-label{margin:0}
.rf-staging-badge{font-family:var(--font-mono,monospace);font-size:10px;color:var(--text-dim,#888);background:var(--bg,#15151b);border:1px solid var(--border,#2a2a33);border-radius:999px;padding:2px 9px}
.rf-staging-badge b{color:var(--accent-green,#5a9e6f);font-size:12px;margin-left:3px}
.rf-stage-add{width:100%}
.rf-stage-list{display:flex;flex-direction:column;gap:5px;max-height:150px;overflow:auto}
.rf-stage-empty{color:var(--text-dim,#888);font-size:11px;text-align:center;padding:8px 4px;line-height:1.5}
.rf-stage-item{display:flex;align-items:center;gap:8px;background:var(--bg,#15151b);border:1px solid var(--border,#2a2a33);border-radius:7px;padding:6px 8px;font-size:11px}
.rf-stage-idx{flex:0 0 auto;width:16px;height:16px;border-radius:50%;background:var(--bg-elevated,#2a2a33);color:var(--text-dim,#888);font-family:var(--font-mono,monospace);font-size:9px;display:inline-flex;align-items:center;justify-content:center}
.rf-stage-pair{flex:1;min-width:0;display:flex;align-items:center;gap:6px;overflow:hidden}
.rf-stage-field{min-width:0;display:inline-flex;align-items:baseline;gap:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text,#e8e8ee)}
.rf-stage-tag{flex:0 0 auto;font-size:9px;color:var(--text-dim,#888);text-transform:uppercase;letter-spacing:.03em}
.rf-stage-sep{flex:0 0 auto;color:var(--border-strong,#444)}
.rf-stage-dim{color:var(--text-dim,#666)}
.rf-stage-count{flex:0 0 auto;font-family:var(--font-mono,monospace);font-size:10px;color:var(--accent-green,#5a9e6f)}
/* Merge & export island */
.refine-staging{border:1px solid var(--border,#2a2a33);border-radius:10px;background:var(--bg-elevated,#21212a);padding:10px;display:flex;flex-direction:column;gap:7px}
.rf-stage-grid{display:flex;gap:6px}
.rf-stage-grid .mod-action-btn{flex:1}
.rf-stage-export{width:100%}
@media (max-width:680px){
  .refine-2col{flex-direction:column}
  .refine-left,.refine-right{flex:1 1 auto;width:100%}
}`;
    const style = document.createElement('style');
    style.id = 'refine-tab-style';
    style.textContent = css;
    document.head.appendChild(style);
  }

  return {
    open: openPanel,
    close,
    isOpen,
    onDepthState,
    onDepthSample,
    refineSample,
    refineGenerate,
    depthFilter,
    depthAction,
  };
}
