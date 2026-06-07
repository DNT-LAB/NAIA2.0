export function createEventStreamPanel({
  document,
  escHtml,
  setModuleParam,
  runStorytellerCycle,
  bindTagAssist,
  getApiMode,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let currentState = null;        // event_stream module state (advanced section)
  let currentStoryState = null;   // storyteller module state (run/progress)
  let steps = [];                 // authored step cards (1.5 EV.A parity)
  let stepsHydrated = false;      // seeded once from the first storyteller state
  let validationMap = {};         // per-step validation results, keyed by step index
  let pendingValidate = {};       // values snapshot sent with an in-flight validate
  let validatingIndex = null;     // 검증 진행 중인 카드 (그동안 해당 카드 편집/타 검증 잠금)
  let validateLockTimer = null;

  const sendModuleParam = setModuleParam || ((moduleId, key, value) => {
    if (typeof globalThis.setModuleParam === 'function') {
      globalThis.setModuleParam(moduleId, key, value);
    }
  });

  // Arms the cycle AND generates page 1 atomically server-side via a single command that
  // carries the authored steps + live UI params. The backend rolls the whole cycle back
  // on any failure, so there is no "armed but idle" state to get stuck in.
  const startCycle = typeof runStorytellerCycle === 'function'
    ? (request) => runStorytellerCycle(request)
    : (request) => {
        if (typeof globalThis.runStorytellerCycle === 'function') {
          globalThis.runStorytellerCycle(request);
        }
      };

  const bindAssist = typeof bindTagAssist === 'function'
    ? bindTagAssist
    : (el, opts) => {
        if (typeof globalThis.bindTagAssist === 'function') {
          globalThis.bindTagAssist(el, opts);
        }
      };

  // Use Vibe는 NAI 전용 — 모드를 모르면 NAI로 간주해 잘못된 잠금을 피한다(백엔드가
  // 어차피 비NAI에서 작업을 수행하지 않으므로 안전).
  function isNaiMode() {
    try {
      const mode = typeof getApiMode === 'function' ? getApiMode() : 'NAI';
      return String(mode || 'NAI').toUpperCase() === 'NAI';
    } catch {
      return true;
    }
  }

  function safe(value) {
    return escHtml ? escHtml(String(value ?? '')) : String(value ?? '');
  }

  function bool(value) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') return value.toLowerCase() === 'true';
    return Boolean(value);
  }

  const RATING_OPTIONS = [
    {value: 'all', label: '전체(활성 등급)'},
    {value: 'g', label: 'G'},
    {value: 's', label: 'S'},
    {value: 'q', label: 'Q'},
    {value: 'e', label: 'E'},
    {value: 'eq', label: 'E+Q'},
    {value: 'sg', label: 'S+G'},
  ];

  const RES_OPTIONS = [
    {value: 'default', label: '기본(현재 설정)'},
    {value: 'random', label: 'Random(해상도 매니저 목록)'},
    {value: 'previous', label: 'Previous(직전 페이지)'},
    {value: '1024 x 1024', label: '1024 x 1024'},
    {value: '960 x 1088', label: '960 x 1088'},
    {value: '896 x 1152', label: '896 x 1152'},
    {value: '832 x 1216', label: '832 x 1216'},
    {value: '1088 x 960', label: '1088 x 960'},
    {value: '1152 x 896', label: '1152 x 896'},
    {value: '1216 x 832', label: '1216 x 832'},
  ];

  function defaultStep() {
    return {include: '', exclude: '', rating: 'all', keep_clothes: false, keep_background: false, use_vibe: false, resolution: 'default'};
  }

  function ensureSteps() {
    if (!steps.length) steps = [defaultStep()];
  }

  function syncStepsFromDom() {
    // Tag autocomplete writes textarea.value PROGRAMMATICALLY (no input event), so the
    // closure copy can be stale. The DOM is the source of truth at action time — pull
    // every card's current values into steps before validating/running/persisting.
    moduleBody?.querySelectorAll('.story-step-card').forEach(card => {
      const index = Number(card.dataset.stepIndex);
      if (!Number.isFinite(index) || !steps[index]) return;
      const include = card.querySelector('.story-step-include');
      const exclude = card.querySelector('.story-step-exclude');
      const rating = card.querySelector('.story-step-rating');
      const resolution = card.querySelector('.story-step-res');
      const keepClothes = card.querySelector('[data-step-keepclothes]');
      const keepBackground = card.querySelector('[data-step-keepbg]');
      const useVibe = card.querySelector('[data-step-usevibe]');
      if (include) steps[index].include = include.value;
      if (exclude) steps[index].exclude = exclude.value;
      if (rating) steps[index].rating = rating.value;
      if (resolution) steps[index].resolution = resolution.value;
      if (keepClothes) steps[index].keep_clothes = Boolean(keepClothes.checked);
      if (keepBackground) steps[index].keep_background = Boolean(keepBackground.checked);
      // disabled(마지막 스텝/비NAI) 체크박스는 해제 상태로 그려지므로 동기화에서 제외 —
      // 저장된 use_vibe 값을 보존한다(스텝을 다시 추가하면 체크 복원).
      if (useVibe && !useVibe.disabled) steps[index].use_vibe = Boolean(useVibe.checked);
    });
  }

  function persistSteps() {
    syncStepsFromDom();
    sendModuleParam('storyteller', 'steps', JSON.stringify({steps}));
  }

  // 검증은 '그때의 값'에 대한 것이다. 자동완성처럼 input 이벤트 없이 값이 바뀌는 경로가
  // 있으므로, ok 플래그만 믿지 않고 검증 시점에 보낸 값과 현재 값을 대조한다.
  function stepMatchesValidation(index) {
    const result = validationMap[index];
    const step = steps[index];
    if (!result || !result.ok || !step) return false;
    return String(result.include ?? '') === String(step.include ?? '')
      && String(result.exclude ?? '') === String(step.exclude ?? '')
      && String(result.rating ?? 'all') === String(step.rating ?? 'all');
  }

  function allStepsValid() {
    return steps.length > 0 && steps.every((_, index) => stepMatchesValidation(index));
  }

  function updateRunGate() {
    const runBtn = moduleBody?.querySelector('#storytellerRunBtn');
    const hint = moduleBody?.querySelector('.story-run-gate-hint');
    const ok = allStepsValid();
    if (runBtn) runBtn.disabled = !ok;
    if (hint) hint.style.display = ok ? 'none' : '';
  }

  // 검증 중 잠금: 해당 카드 편집 금지 + 모든 카드의 검증 버튼 비활성(동시 검증 금지).
  function lockValidationUi(index) {
    moduleBody?.querySelectorAll('.story-step-validate').forEach(btn => { btn.disabled = true; });
    const card = moduleBody?.querySelector(`.story-step-card[data-step-index="${index}"]`);
    card?.querySelectorAll('textarea, select, .story-step-del').forEach(el => { el.disabled = true; });
    const btn = card?.querySelector('.story-step-validate');
    if (btn) btn.textContent = '검증 중…';
  }

  function unlockValidationUi() {
    validatingIndex = null;
    if (validateLockTimer) { clearTimeout(validateLockTimer); validateLockTimer = null; }
    if (bool(currentStoryState?.is_running)) return; // 실행 중엔 어차피 전체 disabled
    moduleBody?.querySelectorAll('.story-step-validate').forEach(btn => { btn.disabled = false; });
    moduleBody?.querySelectorAll('.story-step-card textarea, .story-step-card select, .story-step-card .story-step-del')
      .forEach(el => { el.disabled = false; });
  }

  // Edit → that step's validation is stale (1.5 contract: every step must be re-validated
  // before the cycle can run). Updates the card in place so the caret is never disturbed.
  function invalidateStep(index) {
    delete validationMap[index];
    applyValidationToCard(index);
  }

  function applyValidationToCard(index) {
    const card = moduleBody?.querySelector(`.story-step-card[data-step-index="${index}"]`);
    if (card) {
      const result = validationMap[index];
      const btn = card.querySelector('.story-step-validate');
      card.classList.remove('unvalidated', 'valid-ok', 'valid-bad');
      if (result?.ok) {
        card.classList.add('valid-ok');
        if (btn) {
          btn.textContent = `✓ ${Number(result.count || 0).toLocaleString()}건`;
          btn.classList.add('ok');
          btn.classList.remove('bad');
        }
      } else if (result) {
        card.classList.add('valid-bad');
        if (btn) {
          btn.textContent = 'Invalid · 0건';
          btn.classList.add('bad');
          btn.classList.remove('ok');
        }
      } else {
        card.classList.add('unvalidated');
        if (btn) {
          btn.textContent = '검증';
          btn.classList.remove('ok', 'bad');
        }
      }
    }
    updateRunGate();
  }

  // Use Vibe 체크박스: 마지막 스텝(적용할 다음 스텝 없음 — 무의미한 Anlas 소모 방지)과
  // 비NAI 모드(백엔드가 작업을 수행하지 않음)에서는 비활성+해제 표시. 값 자체는 보존
  // (sync가 disabled 입력을 건너뛰므로) — 아래에 스텝을 추가하면 체크가 되살아난다.
  function vibeCheckbox(step, index, running) {
    const isLast = index === steps.length - 1;
    const naiMode = isNaiMode();
    const forcedOff = isLast || !naiMode;
    const disabled = running || forcedOff;
    let title = '이 스텝의 생성 결과를 IE 0.6으로 인코딩해(2 Anlas) 다음 스텝부터 Vibe(RS 0.9)로 적용합니다. '
      + '스트림이 추가하는 Vibe는 1장뿐 — 다른 스텝에서 다시 체크하면 그 스텝 이미지로 교체됩니다. '
      + '라운드가 다시 시작되면 리셋되고, Vibe Storage에는 저장되지 않습니다 (NAI 전용, NAID3 제외).';
    if (!naiMode) {
      title = 'NAI 모드 전용입니다 — 현재 모드에서는 Vibe 사용이 동작하지 않습니다.';
    } else if (isLast) {
      title = '마지막 스텝에는 적용할 다음 스텝이 없어 사용할 수 없습니다 (무의미한 Anlas 소모 방지).';
    }
    return `
              <label title="${title}" ${forcedOff ? 'class="story-vibe-off"' : ''}>
                <input type="checkbox" data-step-usevibe="${index}"
                       ${step.use_vibe && !forcedOff ? 'checked' : ''} ${disabled ? 'disabled' : ''}> Vibe 사용 (2 Anlas)
              </label>`;
  }

  // ---- Storyteller hero section -------------------------------------------------
  function stepCard(step, index) {
    const running = bool(currentStoryState?.is_running);
    const completed = Number(currentStoryState?.completed_count) || 0;
    const isCurrent = running && index === completed;
    const isDone = running && index < completed;
    const result = validationMap[index];
    let stateClass = ' unvalidated';
    let validateLabel = '검증';
    let validateClass = '';
    if (stepMatchesValidation(index)) {
      stateClass = ' valid-ok';
      validateLabel = `✓ ${Number(result.count || 0).toLocaleString()}건`;
      validateClass = ' ok';
    } else if (result && !result.ok) {
      stateClass = ' valid-bad';
      validateLabel = 'Invalid · 0건';
      validateClass = ' bad';
    }
    const ratingOptions = RATING_OPTIONS
      .map(opt => `<option value="${opt.value}" ${String(step.rating || 'all') === opt.value ? 'selected' : ''}>${opt.label}</option>`)
      .join('');
    const dis = running ? 'disabled' : '';
    return `
      <div class="story-step-card${stateClass}${isCurrent ? ' current' : ''}${isDone ? ' done' : ''}" data-step-index="${index}">
        <div class="story-step-head">
          <span class="story-step-no">Step ${index + 1}</span>
          ${isCurrent ? '<span class="story-step-now">생성 중…</span>' : (isDone ? '<span class="story-step-donemark">✓ 완료</span>' : '')}
          <button type="button" class="story-step-del" data-step-del="${index}" title="스텝 삭제" ${dis}>×</button>
        </div>
        <div class="story-step-row">
          <label>포함</label>
          <textarea rows="1" class="mod-textarea story-step-include" data-step-include="${index}"
                    placeholder="예: 1girl, solo, classroom" ${dis}>${safe(step.include)}</textarea>
        </div>
        <div class="story-step-row">
          <label>제외</label>
          <textarea rows="1" class="mod-textarea story-step-exclude" data-step-exclude="${index}"
                    placeholder="예: 1boy" ${dis}>${safe(step.exclude)}</textarea>
        </div>
        <div class="story-step-row">
          <label>등급</label>
          <div class="story-step-bottom">
            <select class="story-step-rating" data-step-rating="${index}" ${dis}>${ratingOptions}</select>
            <button type="button" class="story-step-validate${validateClass}" data-step-validate="${index}" ${dis}>${validateLabel}</button>
          </div>
        </div>
        <div class="story-step-row">
          <label>해상도</label>
          <div class="story-step-bottom">
            <select class="story-step-res" data-step-res="${index}" ${dis}>${RES_OPTIONS
              .map(opt => `<option value="${opt.value}" ${String(step.resolution || 'default') === opt.value ? 'selected' : ''}>${opt.label}</option>`)
              .join('')}</select>
            <span class="story-step-carry">
              <label title="이 스텝의 의상을 다음 스텝에도 유지합니다 (다음 장면 행의 의상 태그는 제거하고 이 스텝의 의상을 주입)">
                <input type="checkbox" data-step-keepclothes="${index}" ${step.keep_clothes ? 'checked' : ''} ${dis}> 의상 유지
              </label>
              <label title="이 스텝의 배경/장소를 다음 스텝에도 유지합니다">
                <input type="checkbox" data-step-keepbg="${index}" ${step.keep_background ? 'checked' : ''} ${dis}> 배경 유지
              </label>
              ${vibeCheckbox(step, index, running)}
            </span>
          </div>
        </div>
      </div>
    `;
  }

  function statusLabel(status) {
    const map = {
      'Complete': '지난 실행: 완료',
      'Stopped': '지난 실행: 정지됨',
      'Stopped after error': '지난 실행: 오류로 정지',
    };
    return map[status] || '';
  }

  function storySection() {
    ensureSteps();
    const story = currentStoryState || {};
    const running = bool(story.is_running);
    const target = Number(story.target_count) || 0;
    const completed = Number(story.completed_count) || 0;
    const lastStatus = running ? '' : statusLabel(String(story.status || ''));
    return `
      <div class="event-stream-section event-stream-story">
        <div class="event-stream-section-title">STORYTELLER — 스텝 시퀀스</div>
        <div class="event-stream-story-hint">
          캐릭터·아티스트·스타일은 <b>고정(freeze)</b>되고, 각 스텝의 포함/제외 태그가
          <b>장면(구도)</b>을 정합니다. 스텝당 1장씩 순서대로 생성한 뒤 자동 정지합니다.
          장면은 <b>현재 검색 결과</b>에서 뽑으므로 먼저 검색해 두세요.
        </div>
        <div class="story-step-list">${steps.map(stepCard).join('')}</div>
        <div class="story-step-actions">
          <button type="button" class="mod-btn-secondary" id="storyStepAddBtn" ${running ? 'disabled' : ''}>+ 스텝 추가</button>
          ${lastStatus ? `<span class="story-step-laststatus">${lastStatus}</span>` : ''}
        </div>
        ${running
          ? `<div class="story-run-progress"><span>진행 중</span><strong>${completed} / ${target} 페이지</strong></div>
        <button type="button" class="story-run-btn stop" id="storytellerStopBtn">정지</button>`
          : `<button type="button" class="story-run-btn" id="storytellerRunBtn" ${allStepsValid() ? '' : 'disabled'}>한 사이클 실행 (${steps.length}스텝)</button>
        <div class="story-run-gate-hint" ${allStepsValid() ? 'style="display:none"' : ''}>모든 스텝을 검증(✓)해야 실행할 수 있습니다. 검증은 스텝별 매칭 존재 확인이며, 같은 조건의 스텝들이 행을 나눠 소비하면 실행 중 부족할 수 있습니다.</div>
        ${manualSection()}`}
      </div>
    `;
  }

  // 1.5 EV.A 방식 수동 진행: 런처의 '이벤트 스트림 활성' 토글이 저장된 시퀀스를 무장하고
  // Random 버튼이 한 스텝씩 민다(라운드 순환). 별도의 '시퀀스 수동 시작' 버튼은 혼란만
  // 줘서 제거(사용자 요청) — 활성 상태 표시 + 종료만 남긴다.
  function manualSection() {
    const streamActive = bool(currentState?.active);
    if (!streamActive) return '';
    const total = Number(currentState?.node_count) || steps.length || 1;
    const position = ((Number(currentState?.current_index) || 0) % total) + 1;
    return `
      <div class="story-manual-row">
        <span>수동 진행 중 — 다음: <strong>Step ${position} / ${total}</strong> (Random으로 진행)</span>
        <button type="button" class="mod-btn-secondary" id="storyManualStopBtn">종료</button>
      </div>`;
  }

  // ---- Advanced (legacy Event Stream debug view), collapsed ----------------------
  function nodeLabel(state) {
    const node = state?.current_node || null;
    if (!node) return 'Current Search';
    return node.name || node.node_id || 'Current Search';
  }

  function renderNodeList(nodes = []) {
    const list = Array.isArray(nodes) && nodes.length
      ? nodes
      : [{node_id: 'node.default', name: 'Current Search', source: 'current_search'}];
    return list.map((node, index) => `
      <div class="event-stream-node">
        <span class="event-stream-node-index">${index + 1}</span>
        <span class="event-stream-node-name">${safe(node.name || node.node_id || 'Node')}</span>
        <span class="event-stream-node-source">${safe(node.source || 'current_search')}</span>
      </div>
    `).join('');
  }

  function advancedSection(state = {}) {
    const active = bool(state.active);
    const storyRunning = bool(currentStoryState?.is_running);
    const tone = state?.error ? 'error' : (active ? 'ok' : 'idle');
    const runId = state.run_id || '-';
    const frameIndex = Number.isFinite(Number(state.frame_index)) ? Number(state.frame_index) : 0;
    const nodeCount = Number.isFinite(Number(state.node_count)) ? Number(state.node_count) : 0;
    const traceCount = Number.isFinite(Number(state.trace_count)) ? Number(state.trace_count) : 0;
    return `
      <details class="event-stream-advanced">
        <summary>고급 — 내부 상태 (디버그·표시 전용) ${active ? '<span class="event-stream-advanced-on">ON</span>' : ''}</summary>
        <div class="event-stream-advanced-body">
          <div class="event-stream-advanced-desc">
            Storyteller 실행이 자동으로 켜고 끄는 내부 freeze/할당 상태입니다. 직접 조작할
            필요가 없습니다. (수동으로 ON이면 일반 Random까지 이 allocator를 타므로 끄세요.)
          </div>
          ${active && !storyRunning
            ? '<button type="button" class="mod-btn-secondary" id="eventStreamOffBtn">이벤트 스트림 강제 끄기 (잔여 상태 정리)</button>'
            : ''}
          <div class="event-stream-status" data-tone="${tone}">
            <span>${active ? 'ON' : 'OFF'}</span>
            <strong>${safe(nodeLabel(state))}</strong>
          </div>
          <div class="event-stream-grid">
            <div class="event-stream-field"><span>Run</span><strong>${safe(runId)}</strong></div>
            <div class="event-stream-field"><span>Frame</span><strong>${frameIndex}</strong></div>
            <div class="event-stream-field"><span>Nodes</span><strong>${nodeCount || 1}</strong></div>
            <div class="event-stream-field"><span>Trace</span><strong>${traceCount}</strong></div>
          </div>
          <div class="event-stream-section">
            <div class="event-stream-section-title">Freeze</div>
            <div class="event-stream-freeze-list">
              <span>Wildcard</span>
              <span>Character</span>
              <span>Prompt Eng.</span>
            </div>
          </div>
          <div class="event-stream-section">
            <div class="event-stream-section-title">Node Sequence</div>
            <div class="event-stream-node-list">${renderNodeList(state.nodes)}</div>
          </div>
        </div>
      </details>
    `;
  }

  // ---- Render --------------------------------------------------------------------
  function render(state = {}) {
    currentState = state;
    if (!moduleBody) return;
    moduleBody.innerHTML = `
      <div class="event-stream-panel" data-event-stream-panel>
        ${storySection()}
        ${advancedSection(state)}
      </div>
    `;
    afterRender();
  }

  function afterRender() {
    moduleBody?.querySelectorAll('.story-step-include, .story-step-exclude').forEach(el => {
      try { bindAssist(el); } catch { /* autocomplete is optional */ }
    });
  }

  function rerenderIfSafe() {
    if (!document.querySelector('[data-event-stream-panel]')) return;
    // Don't yank the DOM out from under the user while they're typing in a step card.
    const focused = document.activeElement;
    if (focused && typeof focused.closest === 'function' && focused.closest('.story-step-card')) return;
    // Autocomplete writes values without input events — pull the DOM into the closure
    // BEFORE rebuilding, or the re-render would silently discard those edits. (Structural
    // ops never come through here; they sync→mutate→render themselves.)
    syncStepsFromDom();
    render(currentState || {});
  }

  // ---- Events ----------------------------------------------------------------------
  function bind() {
    document.addEventListener('input', event => {
      const target = event.target;
      if (!target || !target.dataset) return;
      if (target.dataset.stepInclude !== undefined) {
        const index = Number(target.dataset.stepInclude);
        if (steps[index]) { steps[index].include = target.value; invalidateStep(index); }
      } else if (target.dataset.stepExclude !== undefined) {
        const index = Number(target.dataset.stepExclude);
        if (steps[index]) { steps[index].exclude = target.value; invalidateStep(index); }
      }
    });

    document.addEventListener('change', event => {
      const target = event.target;
      if (!target) return;
      if (!target.dataset) return;
      if (target.dataset.stepRating !== undefined) {
        const index = Number(target.dataset.stepRating);
        if (steps[index]) { steps[index].rating = target.value; invalidateStep(index); persistSteps(); }
        return;
      }
      // 해상도/유지 플래그는 매칭 건수에 영향이 없으므로 검증을 무효화하지 않는다.
      if (target.dataset.stepRes !== undefined) {
        const index = Number(target.dataset.stepRes);
        if (steps[index]) { steps[index].resolution = target.value; persistSteps(); }
        return;
      }
      if (target.dataset.stepKeepclothes !== undefined) {
        const index = Number(target.dataset.stepKeepclothes);
        if (steps[index]) { steps[index].keep_clothes = Boolean(target.checked); persistSteps(); }
        return;
      }
      if (target.dataset.stepKeepbg !== undefined) {
        const index = Number(target.dataset.stepKeepbg);
        if (steps[index]) { steps[index].keep_background = Boolean(target.checked); persistSteps(); }
        return;
      }
      if (target.dataset.stepUsevibe !== undefined) {
        const index = Number(target.dataset.stepUsevibe);
        if (steps[index]) { steps[index].use_vibe = Boolean(target.checked); persistSteps(); }
        return;
      }
      if (target.dataset.stepInclude !== undefined || target.dataset.stepExclude !== undefined) {
        persistSteps();
      }
    });

    document.addEventListener('click', event => {
      const target = event.target;
      const id = target?.id;
      if (id === 'eventStreamOffBtn') {
        // 잔여 수동 활성 상태 정리(스토리 실행 중엔 백엔드가 거부).
        sendModuleParam('event_stream', 'active', 'false');
      } else if (id === 'storyManualStopBtn') {
        sendModuleParam('storyteller', 'manual_disarm', '1');
      } else if (id === 'storyStepAddBtn') {
        ensureSteps();
        if (steps.length < 100) {
          syncStepsFromDom();          // capture unsaved edits BEFORE mutating
          steps.push(defaultStep());
          validationMap = {};          // indexes shift → everything needs re-validation
          render(currentState || {});  // DOM now matches steps → persist's sync is safe
          persistSteps();
        }
      } else if (target?.dataset?.stepDel !== undefined) {
        const index = Number(target.dataset.stepDel);
        if (Number.isFinite(index)) {
          syncStepsFromDom();
          steps.splice(index, 1);
          ensureSteps();
          validationMap = {};
          render(currentState || {});
          persistSteps();
        }
      } else if (target?.dataset?.stepValidate !== undefined) {
        const index = Number(target.dataset.stepValidate);
        if (Number.isFinite(index) && steps[index] && validatingIndex === null) {
          syncStepsFromDom();
          // 응답이 오면 이 스냅샷이 validationMap에 합쳐져 "어떤 값이 검증됐는지"를 남긴다.
          pendingValidate[index] = {
            include: steps[index].include,
            exclude: steps[index].exclude,
            rating: steps[index].rating,
          };
          validatingIndex = index;
          lockValidationUi(index);
          // 응답 유실 대비 안전 해제.
          validateLockTimer = setTimeout(() => unlockValidationUi(), 30000);
          sendModuleParam('storyteller', 'validate', JSON.stringify({step: steps[index], index}));
        }
      } else if (id === 'storytellerRunBtn') {
        // One atomic command: arm + generate page 1 with the authored steps.
        syncStepsFromDom();
        // 실행 직전 하드 가드: 자동완성 등 이벤트 없는 값 변경이 검증을 비켜갔을 수 있다.
        // 검증 시점 값과 현재 값을 대조해 어긋난 카드를 무효화(적색)하고 실행하지 않는다.
        const staleIndexes = steps.map((_, index) => index)
          .filter(index => !stepMatchesValidation(index));
        if (staleIndexes.length) {
          staleIndexes.forEach(index => invalidateStep(index));
          updateRunGate();
          return;
        }
        startCycle({count: steps.length, steps});
      } else if (id === 'storytellerStopBtn') {
        sendModuleParam('storyteller', 'stop', '1');
      }
    });
  }

  bind();

  return {
    render,
    setState(state = {}) {
      currentState = state;
      rerenderIfSafe();
    },
    setStorytellerState(state = {}) {
      currentStoryState = state;
      let hydratedNow = false;
      if (!stepsHydrated && Array.isArray(state.steps)) {
        if (state.steps.length) {
          steps = state.steps.map(step => ({
            include: String(step?.include || ''),
            exclude: String(step?.exclude || ''),
            rating: String(step?.rating || 'all'),
            keep_clothes: Boolean(step?.keep_clothes),
            keep_background: Boolean(step?.keep_background),
            use_vibe: Boolean(step?.use_vibe),
            resolution: String(step?.resolution || 'default'),
          }));
          hydratedNow = true;
        }
        stepsHydrated = true;
      }
      if (Array.isArray(state.validation)) {
        const singleIndex = Number(state.validation_index);
        if (Number.isFinite(singleIndex)) {
          // Per-card validation response: update that card in place (caret-safe) instead
          // of re-rendering — the click focus sits inside the card and rerenderIfSafe
          // would otherwise skip the visual update entirely. Merge the values snapshot
          // taken at click time so stale-value comparison works.
          const sent = pendingValidate[singleIndex]
            || (steps[singleIndex] ? {
              include: steps[singleIndex].include,
              exclude: steps[singleIndex].exclude,
              rating: steps[singleIndex].rating,
            } : {});
          validationMap[singleIndex] = {...(state.validation[0] || {}), ...sent};
          delete pendingValidate[singleIndex];
          unlockValidationUi();
          applyValidationToCard(singleIndex);
          return;
        }
        state.validation.forEach((result, index) => {
          const step = steps[index] || {};
          validationMap[index] = {
            ...result,
            include: step.include ?? '',
            exclude: step.exclude ?? '',
            rating: step.rating ?? 'all',
          };
        });
      }
      if (hydratedNow && document.querySelector('[data-event-stream-panel]')) {
        // [재시작 Step 1 클로버 수정] 최초 하이드레이션은 DOM 동기화 없이 강제 재렌더 —
        // rerenderIfSafe는 재렌더 전 syncStepsFromDom을 돌리는데, 하이드레이션 전 DOM은
        // 기본 1카드뿐이라 방금 복원한 steps[0]를 기본값으로 도로 덮어쓴다(Step 1만
        // 재시작 시 유실되던 버그의 근본원인). 저장된 스텝이 항상 이긴다.
        render(currentState || {});
        return;
      }
      rerenderIfSafe();
    },
    getState() {
      return currentState;
    },
  };
}
