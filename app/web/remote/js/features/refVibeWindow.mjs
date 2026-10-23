/** REF & VIBE — Character Reference · Vibe Transfer 를 한 창에서(사용자 지시 2026-10-23).
 *
 *  예전엔 런처 'NAI 전용 도구' 의 모듈 팝업 두 개였다. 이제는
 *    - Result 위 `REF & VIBE` 알약(캐릭터 퀵 슬롯 바로 아래) → 떠 있는 창(`createDraggablePanel`)
 *    - 창 = [Vibe] [Char Ref] 탭 · 위 = 활성 줄(퀵 슬롯 문법) · 아래 = STORAGE(이름 · ★ · 그룹 · 검색 · IE 고르기)
 *  런처 단추는 남는다 - `openModule` 이 이 창으로 돌린다(app.js).
 *
 *  ⚠️ 모델이 이 도구를 쓰는지는 **모델 능력값**(`capabilities.vibe / character_reference`)으로만 판단한다
 *     (`isToolUnsupported`). V5 를 켤 때 화면을 고칠 일이 없게 - 모델 이름으로 분기하지 않는다.
 *  ⚠️ CR 과 VT 는 서로를 끈다(백엔드). 그래서 알약의 배지는 켜진 쪽 하나만 보인다.
 *  ⚠️ `title` 속성은 앱이 자체 툴팁으로 바꿔 덮는다 - 설명은 `data-naia-title` 로 단다.
 */

const TAB_KEY = 'naia.refvibe.tab';
const PAGE = 60;
const KINDS = {vibe: 'vibe_transfer', cr: 'character_reference'};
const API_KIND = {vibe: 'vibe', cr: 'character_reference'};
// 퀵 슬롯의 접힌 상자와 같은 너비 비율(`.cq-box{width:58%}` · app.js CQ_COLLAPSED_RATIO 와 짝).
const PILL_RATIO = 0.58;

export function createRefVibeWindow({
  document: doc,
  window: win = globalThis.window,
  escHtml,
  setModuleParam,
  getModuleState,            // (moduleId) => 마지막 module_state
  requestModuleState,        // (moduleId) => void
  loadDraggablePanel,        // () => Promise<createDraggablePanel>
  uploadImage,               // (moduleId, file, {quiet}) => void
  pasteImage,                // (moduleId, {quiet}) => Promise
  importVibeFile,            // (file) => void
  isToolUnsupported = () => false,   // (moduleId) => bool  모델 능력 / NAID3 / 모드
  isInteractive = () => false,
  showToast = () => {},
  confirmDialog = async () => false,
  promptDialog = async () => null,
  fetchFn = globalThis.fetch,
  storage = globalThis.localStorage,
  onLayout = () => {},       // 알약 높이 · 자리가 바뀌었다(인셋 배지가 그 아래로 간다)
}) {
  let panel = null;
  let panelReady = null;
  let tab = (() => { try { return storage?.getItem(TAB_KEY) === 'cr' ? 'cr' : 'vibe'; } catch (_) { return 'vibe'; } })();
  let visible = false;
  let pill = null;
  const openRows = new Set();           // `${tab}:${index}` - 펼친 활성 줄
  const nameCache = new Map();          // file_hash -> 보관함 이름(활성 줄 표시용)
  // 슬라이더를 끄는 동안 온 상태는 놓을 때 그린다 - 그리면 잡고 있던 손잡이가 사라진다.
  let pointerHeld = false;
  let renderPending = false;
  const lib = {
    vibe: freshLib(),
    cr: freshLib(),
  };
  let menu = null;

  function freshLib() {
    return {model: '', filter: 'all', categoryId: '', q: '', sort: 'recent', items: [], total: 0, offset: 0,
      loading: false, seq: 0, categories: [], counts: {}, models: [], currentModel: '', supported: true,
      selected: '', ie: null, loaded: false, error: ''};
  }

  // ── 알약 ──────────────────────────────────────────────────────────────────
  function ensurePill() {
    const wrapper = doc.querySelector('.viewer-wrapper');
    if (!wrapper) return null;
    if (pill && pill.isConnected && pill.parentElement === wrapper) return pill;
    pill = doc.createElement('div');
    pill.className = 'rvp';
    pill.innerHTML = `<button type="button" class="rvp-box" data-rvp-toggle>`
      + `<span class="rvp-caret" aria-hidden="true">▸</span><span class="rvp-title">REF &amp; VIBE</span>`
      + `<span class="rvp-note" data-rvp-note hidden></span>`
      + `<span class="rvp-count" data-rvp-count hidden></span></button>`;
    pill.addEventListener('click', event => {
      if (!event.target.closest('[data-rvp-toggle]')) return;
      if (pill.classList.contains('is-unsupported')) {
        showToast('REF & VIBE 는 V4 / V4.5 모델에서만 씁니다 - 지금 모델은 지원하지 않습니다', 'info');
        return;
      }
      show({toggle: true});
    });
    wrapper.appendChild(pill);
    pill.classList.toggle('open', visible);
    return pill;
  }

  function setVisible(next) {
    visible = !!next;
    const el = ensurePill();
    if (el) el.classList.toggle('open', visible);
    paintPill();
  }

  function isVisible() { return visible && !!pill?.isConnected; }

  /** 알약을 퀵 패널 바로 아래에 앉힌다. 퀵 패널 높이는 고정이 아니라 잰다(인셋 배지와 같은 방식). */
  function placePill() {
    const el = ensurePill();
    if (!el) return;
    const wrapper = el.parentElement;
    const cq = doc.querySelector('.cq-float.open');
    const cqBox = cq ? cq.getBoundingClientRect() : null;
    if (!cqBox || cqBox.height <= 0) {
      el.style.top = '';
      el.style.left = '';
      el.style.width = '';
    } else {
      const wrapBox = wrapper.getBoundingClientRect();
      el.style.top = `${Math.round(cqBox.bottom - wrapBox.top + 6)}px`;
      el.style.left = `${Math.round(cqBox.left - wrapBox.left)}px`;
      el.style.width = `${Math.round(cqBox.width * PILL_RATIO)}px`;
    }
  }

  function enabledCount(moduleId) {
    const state = getModuleState(moduleId);
    return (state?.frames || []).filter(frame => frame.is_enabled).length;
  }

  // 퀵 패널은 높이가 고정이 아니다(슬롯 수 · 펼침) - 크기가 바뀌면 알약이 따라 내려간다.
  // ⚠️ `.cq-float` 는 늦게 생기고, 떨어지면 새로 만들어진다 - 볼 때마다 지금 요소인지 확인해 다시 건다.
  let cqObserved = null;
  let cqObserver = null;
  function watchQuickPanel() {
    const cq = doc.querySelector('.cq-float');
    if (!cq || cq === cqObserved) return;
    cqObserver?.disconnect();
    cqObserved = cq;
    if (typeof win.ResizeObserver !== 'function') return;
    cqObserver = new win.ResizeObserver(() => paintPill());
    cqObserver.observe(cq);
  }

  function paintPill() {
    const el = ensurePill();
    if (!el) return;
    watchQuickPanel();
    const vibeOff = isToolUnsupported(KINDS.vibe);
    const crOff = isToolUnsupported(KINDS.cr);
    const unsupported = vibeOff && crOff;
    el.classList.toggle('is-unsupported', unsupported);
    const note = el.querySelector('[data-rvp-note]');
    note.hidden = !unsupported;
    note.textContent = unsupported ? 'V4.5 전용' : '';
    const vibe = vibeOff ? 0 : enabledCount(KINDS.vibe);
    const cr = crOff ? 0 : enabledCount(KINDS.cr);
    const count = el.querySelector('[data-rvp-count]');
    const text = vibe ? `V ${vibe}` : (cr ? `R ${cr}` : '');
    count.hidden = !text || unsupported;
    count.textContent = text;
    el.classList.toggle('is-live', !!text && !unsupported);
    el.classList.toggle('is-win', !!panel?.isOpen());
    placePill();
    // ⚠️ placePill 은 onLayout 을 부르지 않는다 - 인셋 배지 쪽이 placePill 을 부르므로 돌고 돈다.
    onLayout();
  }

  // ── 창 ────────────────────────────────────────────────────────────────────
  function ensurePanel() {
    if (panel) return Promise.resolve(panel);
    if (panelReady) return panelReady;
    panelReady = loadDraggablePanel().then(createDraggablePanel => {
      panel = createDraggablePanel({
        document: doc, window: win,
        title: 'REF & VIBE',
        variant: 'rvw',
        storageKey: 'ref-vibe-window',
        width: 600, height: 640, minWidth: 440, minHeight: 320, maxWidth: 1200,
        resizable: true, collapsible: true,
        initial: {x: 520, y: 90},
        escHtml,
        onOpen: () => paintPill(),
        onClose: () => { closeMenu(); paintPill(); },
      });
      panel.slot.innerHTML = `<span class="rvw-tabs" data-nodrag-tabs>`
        + `<button type="button" class="rvw-tab" data-rvw-tab="vibe"></button>`
        + `<button type="button" class="rvw-tab" data-rvw-tab="cr"></button></span>`
        + `<span class="rvw-model" data-rvw-model></span>`;
      panel.slot.addEventListener('click', event => {
        const button = event.target.closest('[data-rvw-tab]');
        if (button) setTab(button.dataset.rvwTab);
      });
      panel.body.innerHTML = `<div class="rvw">`
        + `<div class="rvw-active" data-rvw-active></div>`
        + `<div class="rvw-store" data-rvw-store></div></div>`
        + `<input type="file" accept="image/*" hidden data-rvw-file>`
        + `<input type="file" accept=".naiv4vibe,.naiv4vibebundle,application/json" hidden data-rvw-import>`;
      const body = panel.body;
      body.addEventListener('click', onClick);
      body.addEventListener('dblclick', onDblClick);
      body.addEventListener('input', onInput);
      body.addEventListener('change', onChange);
      body.addEventListener('keydown', onKey);
      body.addEventListener('contextmenu', onContextMenu);
      body.addEventListener('dragstart', onDragStart);
      body.addEventListener('dragend', onDragEnd);
      body.addEventListener('dragover', onDragOver);
      body.addEventListener('dragleave', onDragLeave);
      body.addEventListener('drop', onDrop);
      body.addEventListener('pointerdown', event => { if (event.target.closest('input[type=range]')) pointerHeld = true; });
      doc.addEventListener('pointerup', () => {
        if (!pointerHeld) return;
        pointerHeld = false;
        if (renderPending) { renderPending = false; renderActive(); }
      });
      body.querySelector('[data-rvw-file]').addEventListener('change', event => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (file) uploadImage(KINDS[tab], file, {quiet: true});
      });
      body.querySelector('[data-rvw-import]').addEventListener('change', event => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (file) importVibeFile(file);
      });
      return panel;
    });
    return panelReady;
  }

  function isOpen() { return !!panel?.isOpen(); }

  /** 열기. `toggle` 이면 같은 탭으로 열려 있을 때 닫는다(런처 단추를 두 번 누르는 손버릇). */
  function show({tab: nextTab = '', toggle = false} = {}) {
    return ensurePanel().then(() => {
      const wanted = nextTab === 'cr' || nextTab === 'vibe' ? nextTab : tab;
      if (toggle && panel.isOpen() && wanted === tab) { panel.close(); return; }
      setTab(wanted, {quiet: true});
      const first = !openedOnce;
      openedOnce = true;
      panel.open();
      // 이번 실행 첫 열기는 공용 규칙(FN | Result 경계)에 뜨는데, 그 자리는 퀵 슬롯 · 이 알약을 덮는다 -
      // 알약 오른쪽으로 비켜 선다. 그 뒤로는 사용자가 옮긴 자리를 따른다.
      if (first) stepAsideFromPill();
      requestModuleState(KINDS.vibe);
      requestModuleState(KINDS.cr);
      renderAll();
      loadLibrary(true);
    });
  }

  function hide() { panel?.close(); }

  let openedOnce = false;
  function stepAsideFromPill() {
    const el = pill && pill.classList.contains('open') ? pill : null;
    if (!el || !panel) return;
    const pillBox = el.getBoundingClientRect();
    const box = panel.el.getBoundingClientRect();
    if (pillBox.width <= 0 || box.left >= pillBox.right || box.right <= pillBox.left) return;
    const cq = doc.querySelector('.cq-float.open .cq-box') || doc.querySelector('.cq-float.open');
    const right = Math.max(pillBox.right, cq ? cq.getBoundingClientRect().right : 0);
    panel.moveTo(right + 12, Math.max(box.top, pillBox.top - 30));
  }

  function setTab(next, {quiet = false} = {}) {
    if (next !== 'vibe' && next !== 'cr') return;
    const changed = next !== tab;
    tab = next;
    try { storage?.setItem(TAB_KEY, tab); } catch (_) { /* 기억 못 해도 된다 */ }
    if (!panel) return;
    closeMenu();
    renderAll();
    if (changed && !quiet) loadLibrary(!lib[tab].loaded);
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────
  function renderAll() {
    if (!panel) return;
    renderHead();
    renderActive();
    renderStore();
  }

  function renderHead() {
    const vibeState = getModuleState(KINDS.vibe);
    const crState = getModuleState(KINDS.cr);
    const vibeOn = (vibeState?.frames || []).filter(f => f.is_enabled).length;
    const crOn = (crState?.frames || []).filter(f => f.is_enabled).length;
    const vibeMax = Number(vibeState?.max_frames || 16);
    panel.slot.querySelectorAll('[data-rvw-tab]').forEach(button => {
      const key = button.dataset.rvwTab;
      button.classList.toggle('on', key === tab);
      button.classList.toggle('is-off', isToolUnsupported(KINDS[key]));
      const loaded = (key === 'vibe' ? vibeState : crState)?.frames?.length || 0;
      button.textContent = `${key === 'vibe' ? 'Vibe' : 'Char Ref'} ${key === 'vibe' ? vibeOn : crOn}/${loaded}`;
      button.dataset.naiaTitle = key === 'vibe'
        ? `켜진 Vibe ${vibeOn}개 / 올린 ${loaded}개 (최대 ${vibeMax}개 · 4개까지 추가 Anlas 없음)`
        : `켜진 레퍼런스 ${crOn}개 / 올린 ${loaded}개`;
    });
    const model = panel.slot.querySelector('[data-rvw-model]');
    const current = lib[tab].currentModel || lib.vibe.currentModel || '';
    model.textContent = current;
    model.hidden = !current;
  }

  function frameName(frame) {
    const hash = String(frame.file_hash || '');
    const cached = hash && nameCache.get(hash);
    if (cached) return cached;
    const raw = String(frame.display_name || frame.file_name || hash || '').replace(/\.[a-z0-9]+$/i, '');
    return raw || '(이름 없음)';
  }

  function thumbHtml(frame) {
    if (frame.is_no_image || !frame.thumbnail) return `<span class="rvw-th is-empty" aria-hidden="true">enc</span>`;
    return `<img class="rvw-th" src="data:image/jpeg;base64,${frame.thumbnail}" alt="">`;
  }

  function renderActive() {
    if (!panel) return;
    if (pointerHeld) { renderPending = true; return; }
    const host = panel.body.querySelector('[data-rvw-active]');
    const moduleId = KINDS[tab];
    const scrollTop = host.querySelector('.rvw-rows')?.scrollTop || 0;
    if (isToolUnsupported(moduleId)) {
      host.innerHTML = `<div class="rvw-notice">${tab === 'vibe' ? 'Vibe Transfer' : 'Character Reference'} 는 지금 모델에서 쓰지 않습니다. `
        + `${tab === 'vibe' ? 'V4 / V4.5' : 'V4.5'} 모델을 고르면 쓸 수 있습니다.</div>`;
      return;
    }
    if (tab === 'cr' && isInteractive()) {
      host.innerHTML = `<div class="rvw-notice">Interactive 에서는 캐릭터 헤더의 [Reference] 가 레퍼런스를 맡습니다.</div>`;
      return;
    }
    const state = getModuleState(moduleId) || {};
    const frames = state.frames || [];
    const tools = tab === 'vibe'
      ? `<button type="button" class="rvw-btn" data-rvw-act="upload" data-naia-title="이미지를 올립니다 - 쓰려면 인코딩(2 Anlas)이 필요합니다">+ 업로드</button>`
        + `<button type="button" class="rvw-btn" data-rvw-act="paste">붙여넣기</button>`
        + `<button type="button" class="rvw-btn" data-rvw-act="import" data-naia-title=".naiv4vibe / .naiv4vibebundle - 이미 인코딩된 파일이라 Anlas 를 쓰지 않습니다">Import</button>`
        + `<label class="rvw-check" data-naia-title="켜진 Vibe 들의 강도 합을 1로 맞춥니다"><input type="checkbox" data-rvw-normalize${state.normalize ? ' checked' : ''}> Normalize</label>`
      : `<button type="button" class="rvw-btn" data-rvw-act="upload">+ 업로드</button>`
        + `<button type="button" class="rvw-btn" data-rvw-act="paste">붙여넣기</button>`;
    const notices = [];
    if (tab === 'vibe') {
      const extra = Number(state.extra_cost_count || 0);
      if (extra > 0) notices.push(`5개 이상 켜면 Anlas 가 더 듭니다(추가 ${extra}개).`);
      if (state.strength_warning) notices.push(`켜진 강도 합이 ${Number(state.strength_total || 0).toFixed(2)} 입니다 - Normalize 를 켜거나 강도를 낮추세요.`);
    }
    const rows = frames.map((frame, index) => (tab === 'vibe' ? vibeRow(frame, index) : crRow(frame, index))).join('');
    const max = tab === 'vibe' ? Number(state.max_frames || 16) : 0;
    host.innerHTML = `<div class="rvw-sec"><span class="rvw-sec-t">활성</span><span class="rvw-sec-n">${frames.length}${max ? ` / ${max}` : ''}</span>`
      + `<span class="rvw-sec-tools">${tools}</span></div>`
      + notices.map(text => `<div class="rvw-notice is-warn">${escHtml(text)}</div>`).join('')
      + (frames.length
        ? `<div class="rvw-rows">${rows}</div>`
        : `<div class="rvw-empty">아래 STORAGE 에서 고르거나, 이미지를 올리거나 붙여 넣으세요.</div>`);
    const list = host.querySelector('.rvw-rows');
    if (list) list.scrollTop = scrollTop;
  }

  function fmt(value, digits = 2) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : '0.00';
  }

  function encodedKeys(frame) {
    return (frame.encoding_keys || []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  }

  function vibeRow(frame, index) {
    const key = `vibe:${index}`;
    const open = openRows.has(key);
    const rs = fmt(frame.reference_strength);
    const ie = fmt(frame.information_extracted);
    const keys = encodedKeys(frame);
    const hasIe = keys.some(k => Math.abs(k - Number(ie)) < 1e-6);
    const live = frame.is_enabled ? ' is-live' : ' is-off';
    const encoding = frame.encoding_in_progress ? ' is-busy' : '';
    const head = `<div class="rvw-row${live}${encoding}" data-rvw-row="${index}">`
      + `<button type="button" class="rvw-en" data-rvw-en="${index}" aria-label="${frame.is_enabled ? '끄기' : '켜기'}">${frame.is_enabled ? '✔' : '✘'}</button>`
      + thumbHtml(frame)
      + `<button type="button" class="rvw-name" data-rvw-open="${index}">V${index + 1} · ${escHtml(frameName(frame))}</button>`
      + `<span class="rvw-k">RS</span>`
      + `<input type="range" class="rvw-range" min="-100" max="100" step="1" value="${Math.round(Number(rs) * 100)}" data-rvw-rs="${index}">`
      + `<span class="rvw-v" data-rvw-rs-out="${index}">${rs}</span>`
      + `<button type="button" class="rvw-ie${hasIe ? '' : ' is-pending'}" data-rvw-open="${index}" data-naia-title="${hasIe ? '이 IE 로 인코딩되어 있습니다' : '이 IE 는 아직 인코딩되지 않았습니다 - 펼쳐서 인코딩'}">IE ${ie}</button>`
      + `<button type="button" class="rvw-x" data-rvw-remove="${index}" aria-label="빼기">-</button></div>`;
    if (!open) return head;
    const chips = keys.map(k => `<button type="button" class="rvw-chip${Math.abs(k - Number(ie)) < 1e-6 ? ' on' : ''}" data-rvw-iechip="${index}" data-ie="${fmt(k)}">${fmt(k)}</button>`).join('');
    const locked = frame.is_no_image || frame.no_source;
    const canEncode = frame.can_encode !== false && !locked && !frame.is_naid3 && !frame.encoding_in_progress;
    const detail = `<div class="rvw-detail" data-rvw-detail="${index}">`
      + `<div class="rvw-line"><span class="rvw-k">RS</span><input type="number" class="rvw-num" min="-1" max="1" step="0.01" value="${rs}" data-rvw-rsnum="${index}">`
      + `<span class="rvw-k">IE</span>`
      + (locked
        ? `<span class="rvw-hint">원본 이미지가 없어 인코딩된 IE 만 고릅니다</span>`
        : `<input type="range" class="rvw-range is-wide" min="1" max="100" step="1" value="${Math.round(Number(ie) * 100)}" data-rvw-ie="${index}">`
          + `<span class="rvw-v" data-rvw-ie-out="${index}">${ie}</span>`)
      + `</div><div class="rvw-line">${chips}`
      + (canEncode
        ? `<button type="button" class="rvw-btn is-accent${hasIe ? ' is-hidden' : ''}" data-rvw-encode="${index}" data-ie="${ie}">IE ${ie} 인코딩 (2 Anlas)</button>`
        : (frame.encoding_in_progress ? `<span class="rvw-hint">인코딩 중…</span>`
          // 못 하는 이유를 말한다(토큰 없음 등) - 단추만 사라지면 고장으로 보인다. 원본 없는 Vibe 는 위 줄이 이미 말한다.
          : (locked ? '' : `<span class="rvw-hint">${escHtml(String(frame.encoding_unavailable_reason || '지금은 인코딩할 수 없습니다'))}</span>`)))
      + `</div></div>`;
    return head + detail;
  }

  function crRow(frame, index) {
    const key = `cr:${index}`;
    const open = openRows.has(key);
    const live = frame.is_enabled ? ' is-live' : ' is-off';
    const type = String(frame.reference_type || 'character&style');
    const options = [['character&style', 'Char&Style'], ['character', 'Character'], ['style', 'Style']]
      .map(([value, label]) => `<option value="${value}"${value === type ? ' selected' : ''}>${label}</option>`).join('');
    const head = `<div class="rvw-row${live}" data-rvw-row="${index}">`
      + `<button type="button" class="rvw-en" data-rvw-en="${index}" aria-label="${frame.is_enabled ? '끄기' : '켜기'}">${frame.is_enabled ? '✔' : '✘'}</button>`
      + thumbHtml(frame)
      + `<button type="button" class="rvw-name" data-rvw-open="${index}">R${index + 1} · ${escHtml(frameName(frame))}</button>`
      + `<select class="rvw-sel" data-rvw-type="${index}">${options}</select>`
      + `<button type="button" class="rvw-sf" data-rvw-open="${index}">S ${fmt(frame.strength)} · F ${fmt(frame.fidelity)}</button>`
      + `<button type="button" class="rvw-x" data-rvw-remove="${index}" aria-label="빼기">-</button></div>`;
    if (!open) return head;
    const slider = (name, value) => `<span class="rvw-k">${name === 'strength' ? 'Strength' : 'Fidelity'}</span>`
      + `<input type="range" class="rvw-range is-wide" min="0" max="20" step="1" value="${Math.round(Number(value) * 20)}" data-rvw-cr="${name}" data-index="${index}">`
      + `<span class="rvw-v" data-rvw-cr-out="${name}:${index}">${fmt(value)}</span>`;
    return head + `<div class="rvw-detail"><div class="rvw-line">${slider('strength', frame.strength)}</div>`
      + `<div class="rvw-line">${slider('fidelity', frame.fidelity)}</div></div>`;
  }

  // ── STORAGE ───────────────────────────────────────────────────────────────
  // 왼쪽 = 카테고리 칸(전체 · ★ · 카테고리들 · 미분류 · ◆ 클러스터) · 오른쪽 = 썸네일 격자(사용자 지시 2026-10-23 · Snapshot 창처럼).
  //  - 카테고리 = 정리용 폴더. 한 항목은 한 카테고리. 썸네일을 끌어 놓으면 **옮긴다** · 카테고리끼리 끌어 순서를 바꾼다.
  //  - 클러스터 = Vibe 묶음(번들 · 멤버마다 IE · RS · 켜짐). 카테고리 칸엔 `◆ 클러스터` 한 줄만 - 많아져도 칸이 안 길어진다.
  //    고르면 오른쪽이 클러스터 목록 → 누르면 멤버 편집. Vibe 전용.
  const DND_ITEM = 'application/x-naia-refvibe-item';
  const DND_CAT = 'application/x-naia-refvibe-category';
  const CLUSTER_NAME = /^[A-Za-z0-9가-힣ㄱ-ㅎㅏ-ㅣ]+$/;   // `vibe:이름` 트리거에 쓰인다(vibe_cluster_resolver 와 같은 규칙)
  const clusters = {list: [], loading: false, loaded: false, error: '', openId: '', seq: 0};
  let drag = null;                       // {type: 'item'|'cat', hash?, id?}

  function inClusters() { return tab === 'vibe' && lib.vibe.filter === 'clusters'; }

  function renderStore() {
    if (!panel) return;
    const host = panel.body.querySelector('[data-rvw-store]');
    const state = lib[tab];
    // 틀(머리줄 · 검색칸 · 두 칸)은 탭이 바뀔 때만 새로 짓는다. 치는 중에 목록이 오면 검색칸이 통째로 갈려
    // 초점을 잃었다 - 칸 안쪽만 갈아 끼운다.
    if (host.dataset.tab !== tab || !host.querySelector('[data-rvw-grid]')) {
      host.dataset.tab = tab;
      host.innerHTML = `<div class="rvw-sec"><span class="rvw-sec-t">STORAGE</span><span class="rvw-sec-m" data-rvw-models></span>`
        + `<span class="rvw-sec-tools"><input type="search" class="rvw-q" placeholder="이름 검색" spellcheck="false" autocomplete="off" data-rvw-q>`
        + `<span data-rvw-sortwrap><select class="rvw-sel" data-rvw-sort>`
        + [['recent', '최근순'], ['used', '사용순'], ['name', '이름순']].map(([v, l]) => `<option value="${v}">${l}</option>`).join('')
        + `</select></span></span></div>`
        + `<div class="rvw-split"><div class="rvw-cats" data-rvw-cats></div>`
        + `<div class="rvw-grid" data-rvw-grid></div></div>`
        + `<div data-rvw-pickhost></div>`;
      host.querySelector('[data-rvw-grid]').addEventListener('scroll', onGridScroll, {passive: true});
    }
    const models = tab === 'vibe' && state.models.length > 1 && !inClusters()
      ? `<select class="rvw-sel" data-rvw-libmodel>${state.models.map(m => `<option value="${escHtml(m.key)}"${m.key === state.model ? ' selected' : ''}>${escHtml(m.key)} ${m.count}</option>`).join('')}</select>`
      : (state.model && !inClusters() ? `<span class="rvw-sec-n">${escHtml(state.model)}</span>` : '');
    host.querySelector('[data-rvw-models]').innerHTML = models;
    const input = host.querySelector('[data-rvw-q]');
    input.placeholder = inClusters() ? '클러스터 이름' : '이름 검색';
    const q = inClusters() ? (clusters.q || '') : state.q;
    if (doc.activeElement !== input && input.value !== q) input.value = q;
    host.querySelector('[data-rvw-sortwrap]').hidden = inClusters();
    host.querySelector('[data-rvw-sort]').value = state.sort;
    host.querySelector('[data-rvw-cats]').innerHTML = categoriesHtml();
    const grid = host.querySelector('[data-rvw-grid]');
    const gridTop = grid.scrollTop;
    grid.classList.toggle('is-list', inClusters());
    grid.innerHTML = inClusters() ? clustersHtml() : gridHtml();
    grid.scrollTop = gridTop;
    host.querySelector('[data-rvw-pickhost]').innerHTML = inClusters() ? '' : selectionBar();
  }

  function categoriesHtml() {
    const state = lib[tab];
    const counts = state.counts || {};
    const catCounts = counts.categories || {};
    const row = (filter, id, label, count, {drop = null, draggable = false, cls = ''} = {}) => {
      const on = state.filter === filter && (filter !== 'category' || state.categoryId === id);
      return `<button type="button" class="rvw-cat${on ? ' on' : ''}${cls}" data-rvw-filter="${filter}" data-cat="${escHtml(id)}"`
        + (drop !== null ? ` data-rvw-drop="${escHtml(drop)}"` : '')
        + (draggable ? ` draggable="true" data-rvw-catdrag="${escHtml(id)}"` : '')
        + `><span class="rvw-cat-t">${escHtml(label)}</span><b>${count ?? ''}</b></button>`;
    };
    let html = row('all', '', '전체', counts.all)
      + row('favorite', '', '★ 즐겨찾기', counts.favorite, {drop: '__fav'})
      + `<div class="rvw-cat-sep"></div>`
      + state.categories.map(c => row('category', c.id, c.name, catCounts[c.id] ?? c.count, {drop: c.id, draggable: true})).join('')
      + row('uncategorized', '', '미분류', counts.uncategorized, {drop: ''})
      + `<button type="button" class="rvw-cat is-add" data-rvw-act="newcat">+ 카테고리</button>`;
    if (tab === 'vibe') {
      html += `<div class="rvw-cat-sep"></div>`
        + row('clusters', '', '◆ 클러스터', clusters.loaded ? clusters.list.length : '', {drop: '__cluster', cls: ' is-cluster'});
    }
    return html;
  }

  function gridHtml() {
    const state = lib[tab];
    const cards = state.items.map(item => storeCard(item)).join('');
    const empty = state.loading ? '불러오는 중…'
      : (state.error ? escHtml(state.error)
        : (state.q || state.filter !== 'all' ? '맞는 항목이 없습니다.' : '보관된 항목이 없습니다. 위에서 올리고 인코딩하면 여기에 쌓입니다.'));
    return (cards || `<div class="rvw-empty">${empty}</div>`)
      + (state.items.length && state.items.length < state.total ? `<div class="rvw-more">${state.items.length} / ${state.total}</div>` : '');
  }

  function storeCard(item) {
    const hash = String(item.file_hash || '');
    const name = String(item.display_name || item.name || item.file_name || hash);
    const selected = lib[tab].selected === hash ? ' is-sel' : '';
    const img = item.has_image === false || !item.thumbnail_url
      ? `<span class="rvw-card-im is-empty">enc</span>`
      : `<img class="rvw-card-im" loading="lazy" draggable="false" src="${escHtml(item.thumbnail_url)}" alt="">`;
    const ieCount = tab === 'vibe' ? `<span class="rvw-card-ie">${(item.encoding_keys || []).length}</span>` : '';
    return `<button type="button" class="rvw-card${selected}" draggable="true" data-rvw-card="${escHtml(hash)}">${img}`
      + (item.favorite ? `<span class="rvw-card-star">★</span>` : '')
      + ieCount + `<span class="rvw-card-lb">${escHtml(name)}</span></button>`;
  }

  function selectedItem() {
    const state = lib[tab];
    return state.items.find(item => String(item.file_hash) === state.selected) || null;
  }

  function defaultIe(item) {
    const keys = (item.encoding_keys || []).map(Number).filter(Number.isFinite);
    if (!keys.length) return null;
    // ⚠️ Number(null) 은 0 이다 - 안 쓴 항목이 가장 낮은 IE 로 골라졌다.
    const last = item.last_ie === null || item.last_ie === undefined ? NaN : Number(item.last_ie);
    if (Number.isFinite(last)) return keys.reduce((a, b) => (Math.abs(b - last) < Math.abs(a - last) ? b : a));
    return Math.max(...keys);
  }

  function selectionBar() {
    const item = selectedItem();
    if (!item) return '';
    const state = lib[tab];
    const name = escHtml(String(item.display_name || item.name || item.file_hash));
    let middle = '';
    if (tab === 'vibe') {
      const keys = (item.encoding_keys || []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
      const pick = state.ie ?? defaultIe(item);
      middle = `<span class="rvw-k">IE</span>` + keys.map(k => `<button type="button" class="rvw-chip${Math.abs(k - pick) < 1e-6 ? ' on' : ''}" data-rvw-pickie="${fmt(k)}">${fmt(k)}</button>`).join('');
    } else {
      const s = item.settings || {};
      middle = `<span class="rvw-hint">${escHtml(String(s.reference_type || 'character&style'))} · S ${fmt(s.strength ?? 1)} · F ${fmt(s.fidelity ?? 0.8)}</span>`;
    }
    return `<div class="rvw-pick"><span class="rvw-pick-n">${name}</span>${middle}`
      + `<span class="rvw-pick-tools">`
      + `<button type="button" class="rvw-btn is-accent" data-rvw-act="apply">적용</button>`
      + `<button type="button" class="rvw-btn" data-rvw-act="rename">이름</button>`
      + `<button type="button" class="rvw-btn${item.favorite ? ' is-on' : ''}" data-rvw-act="fav">★</button>`
      + `<button type="button" class="rvw-btn" data-rvw-act="catmenu" data-naia-title="카테고리로 옮깁니다 - 썸네일을 왼쪽 카테고리에 끌어 놓아도 됩니다">카테고리 ▾</button>`
      + (tab === 'vibe' ? `<button type="button" class="rvw-btn" data-rvw-act="clustermenu" data-naia-title="클러스터에 넣습니다 - 고른 IE 로">클러스터 ▾</button>` : '')
      + `<button type="button" class="rvw-btn is-danger" data-rvw-act="delete" data-naia-title="보관함에서 지웁니다(이 PC 에서만)">삭제</button>`
      + `</span></div>`;
  }

  async function api(path, {method = 'GET', body = null} = {}) {
    const response = await fetchFn(path, {
      method,
      cache: 'no-store',
      headers: body ? {'Content-Type': 'application/json'} : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
    return data;
  }

  function libraryUrl(state, offset, limit = PAGE) {
    const params = new URLSearchParams({kind: API_KIND[tab], sort: state.sort, offset: String(offset), limit: String(limit)});
    if (tab === 'vibe' && state.model) params.set('model', state.model);
    const filter = state.filter === 'clusters' ? 'all' : state.filter;
    params.set('filter', filter);
    if (filter === 'category' && state.categoryId) params.set('category_id', state.categoryId);
    if (state.q.trim() && state.filter !== 'clusters') params.set('q', state.q.trim());
    return `/api/ref-vibe/library?${params}`;
  }

  function takeMeta(state, data) {
    state.categories = Array.isArray(data.categories) ? data.categories : [];
    state.counts = data.counts || {};
    state.models = Array.isArray(data.models) ? data.models : [];
    state.currentModel = String(data.current_model || '');
    if (!state.model && data.model) state.model = String(data.model);
    state.supported = data.model_supported !== false;
  }

  /** 목록 받기. `reset` 이면 처음부터, 아니면 이어서(끝까지 굴렸을 때). 클러스터 보기면 수만 받고 클러스터를 받는다. */
  async function loadLibrary(reset = false) {
    if (!panel || !panel.isOpen()) return;
    const kind = tab;
    const state = lib[kind];
    if (kind === 'vibe' && (state.filter === 'clusters' || !clusters.loaded)) loadClusters();
    if (state.filter === 'clusters') {
      if (reset) refreshCounts();
      return;
    }
    if (state.loading && !reset) return;
    if (!reset && state.items.length >= state.total && state.loaded) return;
    const seq = ++state.seq;
    state.loading = true;
    state.error = '';
    if (reset) renderStore();
    try {
      const data = await api(libraryUrl(state, reset ? 0 : state.items.length));
      if (seq !== state.seq) return;
      const items = Array.isArray(data.items) ? data.items : [];
      state.items = reset ? items : state.items.concat(items);
      state.total = Number(data.total || 0);
      takeMeta(state, data);
      state.loaded = true;
      items.forEach(item => { if (item.name) nameCache.set(String(item.file_hash), String(item.name)); });
      if (state.selected && !state.items.some(item => String(item.file_hash) === state.selected) && reset) state.selected = '';
    } catch (error) {
      if (seq !== state.seq) return;
      state.error = `목록을 못 받았습니다: ${error.message || error}`;
    } finally {
      if (seq === state.seq) state.loading = false;
    }
    if (kind !== tab) return;
    renderHead();
    renderStore();
    renderActive();
  }

  function onGridScroll(event) {
    if (inClusters()) return;
    const grid = event.currentTarget;
    if (grid.scrollTop + grid.clientHeight >= grid.scrollHeight - 120) loadLibrary(false);
  }

  function replaceItems(updated) {
    const state = lib[tab];
    (Array.isArray(updated) ? updated : [updated]).filter(Boolean).forEach(next => {
      const at = state.items.findIndex(item => String(item.file_hash) === String(next.file_hash));
      if (at >= 0) state.items[at] = {...state.items[at], ...next};
      if (next.name) nameCache.set(String(next.file_hash), String(next.name));
      else nameCache.delete(String(next.file_hash));
    });
  }

  async function refreshCounts() {
    // 카테고리 · ★ 수는 목록 응답에 실려 온다 - 수만 다시 받는다(항목은 그대로 둔다).
    const state = lib[tab];
    try {
      const data = await api(libraryUrl(state, 0, 1));
      takeMeta(state, data);
      renderStore();
    } catch (_) { /* 수는 다음 목록에서 맞춰진다 */ }
  }

  // ── 보관 항목 동작 ────────────────────────────────────────────────────────
  function applySelected() {
    const item = selectedItem();
    if (!item) return;
    const state = lib[tab];
    if (tab === 'vibe') {
      const ie = state.ie ?? defaultIe(item);
      setModuleParam(KINDS.vibe, 'apply_storage', JSON.stringify({model: state.model, file_hash: item.file_hash, ie}));
    } else {
      setModuleParam(KINDS.cr, 'apply_storage', JSON.stringify({file_hash: item.file_hash}));
    }
  }

  async function renameSelected() {
    const item = selectedItem();
    if (!item) return;
    const next = await promptDialog('보관함에서 보일 이름입니다. 비우면 파일 이름으로 돌아갑니다.', {title: '이름', defaultValue: String(item.name || ''), placeholder: String(item.display_name || '')});
    if (next === null || next === undefined) return;
    try {
      const data = await api('/api/ref-vibe/library/item', {method: 'POST',
        body: {kind: API_KIND[tab], file_hash: item.file_hash, name: String(next), model: lib[tab].model}});
      replaceItems(data.item || data);
      renderStore();
      renderActive();
    } catch (error) {
      showToast(`이름을 못 바꿨습니다: ${error.message || error}`, 'error');
    }
  }

  async function setFavorite(hash, favorite) {
    try {
      const data = await api('/api/ref-vibe/library/item', {method: 'POST',
        body: {kind: API_KIND[tab], file_hash: hash, favorite, model: lib[tab].model}});
      replaceItems(data.item || data);
      if (lib[tab].filter === 'favorite') loadLibrary(true);
      else { refreshCounts(); renderStore(); }
    } catch (error) {
      showToast(`즐겨찾기를 못 바꿨습니다: ${error.message || error}`, 'error');
    }
  }

  async function deleteSelected() {
    const item = selectedItem();
    if (!item) return;
    const name = String(item.display_name || item.file_hash);
    const ok = await confirmDialog(`"${name}" 을 보관함에서 지웁니다. 되돌릴 수 없습니다.`, {title: '삭제', okText: '지우기'});
    if (!ok) return;
    if (tab === 'vibe') {
      setModuleParam(KINDS.vibe, 'delete_storage', `${lib.vibe.model}|${item.file_hash}`);
      lib.vibe.selected = '';
      win.setTimeout(() => loadLibrary(true), 400);
      return;
    }
    try {
      await api('/api/ref-vibe/library/delete', {method: 'POST', body: {kind: API_KIND.cr, file_hash: item.file_hash}});
      lib.cr.selected = '';
      loadLibrary(true);
    } catch (error) {
      showToast(`지우지 못했습니다: ${error.message || error}`, 'error');
    }
  }

  // ── 카테고리 ──────────────────────────────────────────────────────────────
  function categoryName(id) {
    return lib[tab].categories.find(c => c.id === id)?.name || '';
  }

  async function moveTo(hashes, categoryId) {
    const state = lib[tab];
    try {
      const data = await api('/api/ref-vibe/library/move', {method: 'POST',
        body: {kind: API_KIND[tab], file_hashes: hashes, category_id: categoryId, model: state.model}});
      replaceItems(data.items || []);
      if (data.counts) state.counts = data.counts;
      const first = state.items.find(item => String(item.file_hash) === hashes[0]);
      const label = String(first?.display_name || first?.name || hashes[0]);
      showToast(categoryId ? `${label} → ${categoryName(categoryId)}` : `${label} → 미분류`, 'info');
      // 보고 있는 칸에서 빠졌으면 목록을 다시 받는다.
      if (state.filter === 'category' || state.filter === 'uncategorized') loadLibrary(true);
      else renderStore();
    } catch (error) {
      showToast(`옮기지 못했습니다: ${error.message || error}`, 'error');
    }
  }

  async function categoryOp(body) {
    try {
      const data = await api('/api/ref-vibe/library/category', {method: 'POST',
        body: {kind: API_KIND[tab], model: lib[tab].model, ...body}});
      const state = lib[tab];
      if (Array.isArray(data.categories)) state.categories = data.categories;
      if (data.counts) state.counts = data.counts;
      return true;
    } catch (error) {
      showToast(`카테고리 작업을 못 했습니다: ${error.message || error}`, 'error');
      return false;
    }
  }

  async function newCategory() {
    const name = await promptDialog('카테고리 이름', {title: '새 카테고리', placeholder: '인물 톤'});
    if (!name || !String(name).trim()) return '';
    const before = new Set(lib[tab].categories.map(c => c.id));
    if (!await categoryOp({op: 'create', name: String(name).trim()})) return '';
    renderStore();
    return lib[tab].categories.find(c => !before.has(c.id))?.id || '';
  }

  async function renameCategory(id) {
    const name = await promptDialog('카테고리 이름', {title: '카테고리 이름 바꾸기', defaultValue: categoryName(id)});
    if (!name || !String(name).trim()) return;
    if (await categoryOp({op: 'rename', category_id: id, name: String(name).trim()})) renderStore();
  }

  async function deleteCategory(id) {
    if (!await confirmDialog(`카테고리 "${categoryName(id)}" 을 지웁니다. 안의 항목은 미분류로 갑니다.`, {title: '카테고리 지우기', okText: '지우기'})) return;
    if (!await categoryOp({op: 'delete', category_id: id})) return;
    const state = lib[tab];
    if (state.categoryId === id) { state.filter = 'all'; state.categoryId = ''; }
    loadLibrary(true);
  }

  async function reorderCategory(dragId, targetId, after) {
    const ids = lib[tab].categories.map(c => c.id).filter(id => id !== dragId);
    const at = ids.indexOf(targetId);
    if (at < 0) return;
    ids.splice(after ? at + 1 : at, 0, dragId);
    // 먼저 화면에서 옮겨 둔다(서버 답이 늦어도 손이 놓인 자리 그대로).
    const byId = new Map(lib[tab].categories.map(c => [c.id, c]));
    lib[tab].categories = ids.map(id => byId.get(id)).filter(Boolean);
    renderStore();
    if (await categoryOp({op: 'reorder', order: ids})) renderStore();
  }

  function openCategoryMenu(anchor) {
    const item = selectedItem();
    if (!item) return;
    const current = String(item.category || '');
    const rows = lib[tab].categories.map(c => `<button type="button" class="rvw-menu-i${c.id === current ? ' is-selected' : ''}" data-rvw-menu="${escHtml(c.id)}">`
      + `<span class="rvw-menu-mark">${c.id === current ? '✓' : ''}</span>${escHtml(c.name)}</button>`).join('');
    openMenu(anchor, rows
      + `<button type="button" class="rvw-menu-i${current ? '' : ' is-selected'}" data-rvw-menu="__none"><span class="rvw-menu-mark">${current ? '' : '✓'}</span>미분류</button>`
      + `<div class="rvw-menu-sep"></div>`
      + `<button type="button" class="rvw-menu-i is-new" data-rvw-menu="__new"><span class="rvw-menu-mark">+</span>새 카테고리</button>`, async id => {
      if (id === '__new') {
        const created = await newCategory();
        if (created) moveTo([item.file_hash], created);
        return;
      }
      const target = id === '__none' ? '' : id;
      if (target !== current) moveTo([item.file_hash], target);
    });
  }

  function openCategoryRowMenu(anchor, id) {
    openMenu(anchor, `<button type="button" class="rvw-menu-i" data-rvw-menu="rename">이름 바꾸기</button>`
      + `<div class="rvw-menu-sep"></div>`
      + `<button type="button" class="rvw-menu-i is-danger" data-rvw-menu="delete">카테고리 지우기</button>`, op => {
      if (op === 'rename') renameCategory(id);
      else if (op === 'delete') deleteCategory(id);
    });
  }

  // ── 클러스터 ──────────────────────────────────────────────────────────────
  async function loadClusters() {
    if (!panel || !panel.isOpen()) return;
    const seq = ++clusters.seq;
    clusters.loading = true;
    clusters.error = '';
    if (inClusters()) renderStore();
    try {
      const data = await api('/api/ref-vibe/clusters');
      if (seq !== clusters.seq) return;
      clusters.list = Array.isArray(data.clusters) ? data.clusters : [];
      clusters.loaded = true;
      if (clusters.openId && !clusters.list.some(c => c.id === clusters.openId)) clusters.openId = '';
    } catch (error) {
      if (seq !== clusters.seq) return;
      clusters.error = `클러스터를 못 받았습니다: ${error.message || error}`;
    } finally {
      if (seq === clusters.seq) clusters.loading = false;
    }
    if (tab === 'vibe') renderStore();
  }

  function clusterById(id) { return clusters.list.find(c => c.id === id) || null; }

  function replaceCluster(next) {
    if (!next || !next.id) return;
    const at = clusters.list.findIndex(c => c.id === next.id);
    if (at >= 0) clusters.list[at] = next; else clusters.list.push(next);
    clusters.list.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  }

  async function clusterOp(body, {quiet = false} = {}) {
    try {
      const data = await api('/api/ref-vibe/clusters', {method: 'POST', body});
      if (data.deleted) {
        clusters.list = clusters.list.filter(c => c.id !== data.deleted);
        if (clusters.openId === data.deleted) clusters.openId = '';
      } else {
        replaceCluster(data.cluster || data);
      }
      renderStore();
      return data;
    } catch (error) {
      if (!quiet) showToast(`클러스터 작업을 못 했습니다: ${error.message || error}`, 'error');
      return null;
    }
  }

  function memberThumb(member) {
    return member.has_image && member.thumbnail_url
      ? `<img class="rvw-th" loading="lazy" draggable="false" src="${escHtml(member.thumbnail_url)}" alt="">`
      : `<span class="rvw-th is-empty" aria-hidden="true">enc</span>`;
  }

  function clustersHtml() {
    if (clusters.openId) return clusterDetailHtml(clusterById(clusters.openId));
    const q = String(clusters.q || '').trim().toLowerCase();
    const list = clusters.list.filter(c => !q || String(c.name).toLowerCase().includes(q));
    const current = lib.vibe.currentModel;
    const cards = list.map(c => {
      const thumbs = (c.members || []).slice(0, 4).map(m => (m.has_image && m.thumbnail_url
        ? `<img src="${escHtml(m.thumbnail_url)}" alt="" loading="lazy" draggable="false">` : `<span></span>`)).join('');
      const other = current && c.model && c.model !== current;
      return `<div class="rvw-cl" data-rvw-clopen="${escHtml(c.id)}">`
        + `<span class="rvw-cl-stack">${thumbs}</span>`
        + `<span class="rvw-cl-body"><span class="rvw-cl-n">${escHtml(c.name)}</span>`
        + `<span class="rvw-cl-m">${Number(c.enabled_count ?? 0)}/${Number(c.frame_count ?? 0)} · ${escHtml(c.model || '?')}`
        + (other ? ` <em data-naia-title="지금 모델과 다릅니다 - 적용하면 결과가 달라질 수 있습니다">다른 모델</em>` : '') + `</span></span>`
        + `<button type="button" class="rvw-btn is-accent" data-rvw-clapply="clean" data-id="${escHtml(c.id)}" data-naia-title="활성 Vibe 를 이 클러스터로 바꿉니다">바꾸기</button>`
        + `<button type="button" class="rvw-btn" data-rvw-clapply="append" data-id="${escHtml(c.id)}" data-naia-title="활성 Vibe 뒤에 더합니다">더하기</button></div>`;
    }).join('');
    const empty = clusters.loading ? '불러오는 중…' : (clusters.error ? escHtml(clusters.error)
      : (q ? '맞는 클러스터가 없습니다.' : '클러스터가 없습니다. 활성 Vibe 를 맞춰 두고 아래에서 묶으세요.'));
    return (cards || `<div class="rvw-empty">${empty}</div>`)
      + `<button type="button" class="rvw-cl-new" data-rvw-act="clnew">+ 지금 활성 Vibe 로 새 클러스터</button>`;
  }

  function clusterDetailHtml(c) {
    if (!c) return `<div class="rvw-empty">클러스터를 찾지 못했습니다.</div>`;
    const rows = (c.members || []).map(m => {
      const keys = (m.encoding_keys || []).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
      const ie = Number(m.ie);
      const chips = keys.length
        ? keys.map(k => `<button type="button" class="rvw-chip${Math.abs(k - ie) < 1e-6 ? ' on' : ''}" data-rvw-mie="${m.index}" data-ie="${fmt(k)}">${fmt(k)}</button>`).join('')
        : `<span class="rvw-chip on">IE ${fmt(ie)}</span>`;
      const rs = fmt(m.rs);
      // 두 줄 - 위: 켜짐 · 썸네일 · 이름 · 빼기 / 아래: RS · IE 칩(한 줄에 넣으면 이름이 잘리고 칩이 접혔다).
      return `<div class="rvw-mrow${m.enabled ? ' is-live' : ' is-off'}">`
        + `<button type="button" class="rvw-en" data-rvw-men="${m.index}" aria-label="${m.enabled ? '끄기' : '켜기'}">${m.enabled ? '✔' : '✘'}</button>`
        + memberThumb(m)
        + `<span class="rvw-mrow-main"><span class="rvw-mrow-top">`
        + `<span class="rvw-name">${escHtml(String(m.display_name || `#${m.index + 1}`))}</span>`
        + `<button type="button" class="rvw-x" data-rvw-mremove="${m.index}" aria-label="클러스터에서 빼기">-</button></span>`
        + `<span class="rvw-mrow-sub"><span class="rvw-k">RS</span>`
        + `<input type="range" class="rvw-range" min="-100" max="100" step="1" value="${Math.round(Number(rs) * 100)}" data-rvw-mrs="${m.index}">`
        + `<span class="rvw-v" data-rvw-mrs-out="${m.index}">${rs}</span>`
        + `<span class="rvw-k">IE</span><span class="rvw-mchips">${chips}</span></span></span></div>`;
    }).join('');
    return `<div class="rvw-cl-head">`
      + `<button type="button" class="rvw-btn" data-rvw-act="clback" aria-label="클러스터 목록">←</button>`
      + `<span class="rvw-cl-n">${escHtml(c.name)}</span><span class="rvw-cl-m">${escHtml(c.model || '')}</span>`
      + `<span class="rvw-pick-tools">`
      + `<button type="button" class="rvw-btn is-accent" data-rvw-clapply="clean" data-id="${escHtml(c.id)}">바꾸기</button>`
      + `<button type="button" class="rvw-btn" data-rvw-clapply="append" data-id="${escHtml(c.id)}">더하기</button>`
      + `<button type="button" class="rvw-btn" data-rvw-act="clmore" data-id="${escHtml(c.id)}" aria-label="클러스터 메뉴">⋯</button></span></div>`
      + (c.description ? `<div class="rvw-hint rvw-cl-desc">${escHtml(c.description)}</div>` : '')
      + (rows || `<div class="rvw-empty">멤버가 없습니다. 보관함 썸네일을 [클러스터 ▾] 로 넣으세요.</div>`);
  }

  async function newClusterFromActive() {
    const frames = (getModuleState(KINDS.vibe)?.frames || []).filter(f => f.has_encoding || (f.encoding_keys || []).length);
    if (!frames.length) { showToast('인코딩된 활성 Vibe 가 없습니다 - 먼저 Vibe 를 올리고 인코딩하세요', 'info'); return; }
    const name = await promptDialog(`활성 Vibe ${frames.length}개를 IE · RS · 켜짐까지 묶습니다. 이름은 글자 · 숫자 · 한글만(프롬프트 vibe:이름 으로도 부릅니다).`,
      {title: '새 클러스터', placeholder: 'semireal'});
    if (!name || !String(name).trim()) return;
    if (!CLUSTER_NAME.test(String(name).trim())) { showToast('클러스터 이름은 글자 · 숫자 · 한글만 됩니다(띄어쓰기 · 기호 없이)', 'error'); return; }
    const data = await clusterOp({op: 'create', name: String(name).trim()});
    const made = data?.cluster || data;
    if (made?.id) { clusters.openId = made.id; renderStore(); showToast(`클러스터 "${made.name}" 를 만들었습니다`, 'success'); }
  }

  async function addToCluster(id, item) {
    const c = clusterById(id);
    if (!c || !item) return;
    const ie = lib.vibe.selected === item.file_hash && lib.vibe.ie !== null ? lib.vibe.ie : defaultIe(item);
    const data = await clusterOp({op: 'add', id, model: lib.vibe.model, file_hash: item.file_hash, ie});
    if (data) showToast(`${item.display_name || item.file_hash} → ◆ ${c.name}`, 'info');
  }

  function openClusterPickMenu(anchor, item) {
    if (!item) return;
    const model = lib.vibe.model;
    const rows = clusters.list.map(c => {
      const ok = !c.model || c.model === model;
      return `<button type="button" class="rvw-menu-i${ok ? '' : ' is-off'}" data-rvw-menu="${ok ? escHtml(c.id) : ''}"`
        + (ok ? '' : ` data-naia-title="${escHtml(c.model)} 클러스터 - 같은 모델의 Vibe 만 넣을 수 있습니다"`)
        + `><span class="rvw-menu-mark">◆</span>${escHtml(c.name)}</button>`;
    }).join('');
    openMenu(anchor, (rows || `<div class="rvw-menu-h">클러스터가 없습니다</div>`)
      + `<div class="rvw-menu-sep"></div>`
      + `<button type="button" class="rvw-menu-i is-new" data-rvw-menu="__view"><span class="rvw-menu-mark">◆</span>클러스터 보기</button>`, id => {
      if (id === '__view') { lib.vibe.filter = 'clusters'; clusters.openId = ''; loadLibrary(true); renderStore(); return; }
      if (id) addToCluster(id, item);
    });
  }

  function openClusterMoreMenu(anchor, id) {
    const c = clusterById(id);
    if (!c) return;
    openMenu(anchor, `<button type="button" class="rvw-menu-i" data-rvw-menu="rename">이름 바꾸기</button>`
      + `<button type="button" class="rvw-menu-i" data-rvw-menu="desc">설명 고치기</button>`
      + `<div class="rvw-menu-sep"></div>`
      + `<button type="button" class="rvw-menu-i is-danger" data-rvw-menu="delete" data-naia-title="클러스터 파일을 지웁니다(이 PC 에서만) - 보관함의 Vibe 는 그대로">클러스터 지우기</button>`, async op => {
      if (op === 'rename') {
        const name = await promptDialog('글자 · 숫자 · 한글만(프롬프트 vibe:이름 으로도 부릅니다)', {title: '클러스터 이름', defaultValue: c.name});
        if (!name || !String(name).trim() || String(name).trim() === c.name) return;
        if (!CLUSTER_NAME.test(String(name).trim())) { showToast('클러스터 이름은 글자 · 숫자 · 한글만 됩니다', 'error'); return; }
        clusterOp({op: 'rename', id, name: String(name).trim()});
      } else if (op === 'desc') {
        const text = await promptDialog('설명', {title: '클러스터 설명', defaultValue: c.description || ''});
        if (text === null || text === undefined) return;
        clusterOp({op: 'update', id, description: String(text)});
      } else if (op === 'delete') {
        if (!await confirmDialog(`클러스터 "${c.name}" 을 지웁니다. 보관함의 Vibe 는 그대로 남습니다.`, {title: '클러스터 지우기', okText: '지우기'})) return;
        clusterOp({op: 'delete', id});
      }
    });
  }

  // ── 작은 메뉴 ─────────────────────────────────────────────────────────────
  function closeMenu() {
    if (!menu) return;
    menu.remove();
    menu = null;
    doc.removeEventListener('pointerdown', onMenuOutside, true);
  }

  function onMenuOutside(event) {
    if (menu && !menu.contains(event.target)) closeMenu();
  }

  /** `anchor` = 요소 또는 {x, y}(끌어 놓은 자리). */
  function openMenu(anchor, html, onPick) {
    closeMenu();
    menu = doc.createElement('div');
    menu.className = 'rvw-menu';
    menu.innerHTML = html;
    doc.body.appendChild(menu);
    const box = anchor && typeof anchor.getBoundingClientRect === 'function'
      ? anchor.getBoundingClientRect()
      : {left: anchor.x, right: anchor.x, top: anchor.y, bottom: anchor.y};
    const width = menu.offsetWidth;
    const left = Math.min(box.left, win.innerWidth - width - 8);
    const below = box.bottom + 4;
    const top = below + menu.offsetHeight > win.innerHeight - 8 ? Math.max(8, box.top - menu.offsetHeight - 4) : below;
    menu.style.left = `${Math.max(8, Math.round(left))}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.addEventListener('click', event => {
      const item = event.target.closest('[data-rvw-menu]');
      if (!item || !item.dataset.rvwMenu) return;
      const keep = onPick(item.dataset.rvwMenu, item) === 'keep';
      if (!keep) closeMenu();
    });
    doc.addEventListener('pointerdown', onMenuOutside, true);
  }

  function openImportMenu(anchor) {
    openMenu(anchor, `<button type="button" class="rvw-menu-i" data-rvw-menu="file">.naiv4vibe / .naiv4vibebundle 파일…</button>`, () => {
      panel.body.querySelector('[data-rvw-import]').click();
    });
  }

  // ── 끌어 놓기 (Snapshot 창과 같은 규칙) ──────────────────────────────────
  // ⚠️ 놓을 자리 판별은 **자료형만으로** 한다 - 끌던 중 목록이 다시 그려져 dragend 가 안 오면 `drag` 가 남는다.
  //    그 값을 통행증으로 쓰면 다른 데서 끌어온 파일이 엉뚱한 항목으로 옮겨진다(Scene 창에서 실측된 결함).
  function dndTypes(event) {
    const types = event.dataTransfer?.types || [];
    return {item: Array.prototype.indexOf.call(types, DND_ITEM) >= 0, cat: Array.prototype.indexOf.call(types, DND_CAT) >= 0};
  }

  function clearDropMarks() {
    panel?.body.querySelectorAll('.is-drop, .is-drop-before, .is-drop-after').forEach(node => node.classList.remove('is-drop', 'is-drop-before', 'is-drop-after'));
  }

  function onDragStart(event) {
    const card = event.target.closest?.('[data-rvw-card]');
    const catRow = event.target.closest?.('[data-rvw-catdrag]');
    try {
      if (card) {
        drag = {type: 'item', hash: card.dataset.rvwCard};
        event.dataTransfer.setData(DND_ITEM, JSON.stringify({kind: tab, hash: drag.hash}));
        event.dataTransfer.setData('text/plain', drag.hash);   // 표준 자료형이 없으면 끌기를 취소하는 브라우저가 있다
        event.dataTransfer.effectAllowed = 'move';
        card.classList.add('is-dragging');
        panel.body.querySelector('[data-rvw-cats]')?.classList.add('is-dropzone');
      } else if (catRow) {
        drag = {type: 'cat', id: catRow.dataset.rvwCatdrag};
        event.dataTransfer.setData(DND_CAT, drag.id);
        event.dataTransfer.setData('text/plain', drag.id);
        event.dataTransfer.effectAllowed = 'move';
        catRow.classList.add('is-dragging');
      }
    } catch (_) { /* drag 값으로도 동작한다 */ }
    closeMenu();
  }

  function onDragEnd() {
    drag = null;
    clearDropMarks();
    panel?.body.querySelectorAll('.is-dragging').forEach(node => node.classList.remove('is-dragging'));
    panel?.body.querySelector('[data-rvw-cats]')?.classList.remove('is-dropzone');
  }

  function onDragOver(event) {
    const types = dndTypes(event);
    if (types.item) {
      const zone = event.target.closest?.('[data-rvw-drop]');
      if (!zone) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      clearDropMarks();
      zone.classList.add('is-drop');
    } else if (types.cat) {
      const row = event.target.closest?.('[data-rvw-catdrag]');
      if (!row) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      clearDropMarks();
      const box = row.getBoundingClientRect();
      row.classList.add(event.clientY < box.top + box.height / 2 ? 'is-drop-before' : 'is-drop-after');
    }
  }

  function onDragLeave(event) {
    const zone = event.target.closest?.('[data-rvw-drop], [data-rvw-catdrag]');
    if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('is-drop', 'is-drop-before', 'is-drop-after');
  }

  function onDrop(event) {
    const types = dndTypes(event);
    if (!types.item && !types.cat) return;
    event.preventDefault();
    const point = {x: event.clientX, y: event.clientY};
    clearDropMarks();
    if (types.item) {
      const zone = event.target.closest?.('[data-rvw-drop]');
      let hash = '';
      try { hash = JSON.parse(event.dataTransfer.getData(DND_ITEM) || '{}').hash || ''; } catch (_) { hash = ''; }
      hash = hash || (drag?.type === 'item' ? drag.hash : '');
      onDragEnd();
      if (!zone || !hash) return;
      const target = zone.dataset.rvwDrop;
      const item = lib[tab].items.find(i => String(i.file_hash) === hash);
      if (target === '__fav') { if (!item?.favorite) setFavorite(hash, true); return; }
      if (target === '__cluster') { openClusterPickMenu(point, item); return; }
      if (String(item?.category || '') === target) return;          // 제자리면 아무것도 안 한다
      moveTo([hash], target);
      return;
    }
    const row = event.target.closest?.('[data-rvw-catdrag]');
    const dragId = (() => { try { return event.dataTransfer.getData(DND_CAT); } catch (_) { return ''; } })() || drag?.id || '';
    const after = row ? event.clientY >= row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2 : false;
    onDragEnd();
    if (row && dragId && row.dataset.rvwCatdrag !== dragId) reorderCategory(dragId, row.dataset.rvwCatdrag, after);
  }

  // ── 이벤트 ────────────────────────────────────────────────────────────────
  function index(el, attr) {
    return Number.parseInt(el.getAttribute(attr), 10);
  }

  function onClick(event) {
    const t = event.target;
    const moduleId = KINDS[tab];
    let el;
    if ((el = t.closest('[data-rvw-en]'))) {
      const i = index(el, 'data-rvw-en');
      const frame = (getModuleState(moduleId)?.frames || [])[i];
      if (frame) setModuleParam(moduleId, `enable_${i}`, String(!frame.is_enabled));
      return;
    }
    if ((el = t.closest('[data-rvw-open]'))) {
      const key = `${tab}:${index(el, 'data-rvw-open')}`;
      if (openRows.has(key)) openRows.delete(key); else openRows.add(key);
      renderActive();
      return;
    }
    if ((el = t.closest('[data-rvw-remove]'))) {
      const i = index(el, 'data-rvw-remove');
      openRows.delete(`${tab}:${i}`);
      setModuleParam(moduleId, `remove_frame_${i}`, '');
      return;
    }
    if ((el = t.closest('[data-rvw-iechip]'))) {
      setModuleParam(KINDS.vibe, `info_extracted_${index(el, 'data-rvw-iechip')}`, el.dataset.ie);
      return;
    }
    if ((el = t.closest('[data-rvw-encode]'))) {
      el.disabled = true;
      el.textContent = '인코딩 중…';
      setModuleParam(KINDS.vibe, `encode_${index(el, 'data-rvw-encode')}`, el.dataset.ie);
      return;
    }
    if ((el = t.closest('[data-rvw-filter]'))) {
      const state = lib[tab];
      const filter = el.dataset.rvwFilter;
      if (filter === 'clusters') {
        // 이미 클러스터 보기면 목록으로 돌아간다(멤버 편집 중에 다시 누른 손버릇).
        clusters.openId = state.filter === 'clusters' ? '' : clusters.openId;
      }
      state.filter = filter;
      state.categoryId = el.dataset.cat || '';
      state.selected = '';
      loadLibrary(true);
      renderStore();
      return;
    }
    if ((el = t.closest('[data-rvw-clapply]'))) {
      setModuleParam(KINDS.vibe, 'cluster_load', JSON.stringify({id: el.dataset.id, mode: el.dataset.rvwClapply}));
      return;
    }
    if ((el = t.closest('[data-rvw-men]'))) {
      const member = clusterById(clusters.openId)?.members?.find(m => m.index === index(el, 'data-rvw-men'));
      if (member) clusterOp({op: 'update', id: clusters.openId, index: member.index, enabled: !member.enabled});
      return;
    }
    if ((el = t.closest('[data-rvw-mie]'))) {
      clusterOp({op: 'update', id: clusters.openId, index: index(el, 'data-rvw-mie'), ie: Number(el.dataset.ie)});
      return;
    }
    if ((el = t.closest('[data-rvw-mremove]'))) {
      clusterOp({op: 'remove', id: clusters.openId, index: index(el, 'data-rvw-mremove')});
      return;
    }
    if ((el = t.closest('[data-rvw-clopen]'))) {
      clusters.openId = el.dataset.rvwClopen;
      renderStore();
      return;
    }
    if ((el = t.closest('[data-rvw-card]'))) {
      const state = lib[tab];
      const hash = el.dataset.rvwCard;
      state.selected = state.selected === hash ? '' : hash;
      state.ie = null;
      renderStore();
      return;
    }
    if ((el = t.closest('[data-rvw-pickie]'))) {
      lib.vibe.ie = Number(el.dataset.rvwPickie);
      renderStore();
      return;
    }
    if ((el = t.closest('[data-rvw-act]'))) {
      const act = el.dataset.rvwAct;
      if (act === 'upload') panel.body.querySelector('[data-rvw-file]').click();
      else if (act === 'paste') pasteImage(moduleId, {quiet: true});
      else if (act === 'import') openImportMenu(el);
      else if (act === 'apply') applySelected();
      else if (act === 'rename') renameSelected();
      else if (act === 'fav') { const item = selectedItem(); if (item) setFavorite(item.file_hash, !item.favorite); }
      else if (act === 'catmenu') openCategoryMenu(el);
      else if (act === 'clustermenu') { if (!clusters.loaded) loadClusters(); openClusterPickMenu(el, selectedItem()); }
      else if (act === 'delete') deleteSelected();
      else if (act === 'newcat') newCategory();
      else if (act === 'clnew') newClusterFromActive();
      else if (act === 'clback') { clusters.openId = ''; renderStore(); }
      else if (act === 'clmore') openClusterMoreMenu(el, el.dataset.id);
    }
  }

  function onDblClick(event) {
    const card = event.target.closest('[data-rvw-card]');
    if (!card) return;
    lib[tab].selected = card.dataset.rvwCard;
    lib[tab].ie = null;
    applySelected();
    renderStore();
  }

  function onContextMenu(event) {
    const row = event.target.closest('[data-rvw-filter="category"]');
    if (!row) return;
    event.preventDefault();
    openCategoryRowMenu(row, row.dataset.cat);
  }

  let qTimer = 0;
  function onInput(event) {
    const t = event.target;
    if (t.matches('[data-rvw-rs]')) {
      const out = panel.body.querySelector(`[data-rvw-rs-out="${t.dataset.rvwRs}"]`);
      if (out) out.textContent = fmt(Number(t.value) / 100);
    } else if (t.matches('[data-rvw-ie]')) {
      const out = panel.body.querySelector(`[data-rvw-ie-out="${t.dataset.rvwIe}"]`);
      const ie = fmt(Number(t.value) / 100);
      if (out) out.textContent = ie;
      const encode = panel.body.querySelector(`[data-rvw-encode="${t.dataset.rvwIe}"]`);
      if (encode) {
        const frame = (getModuleState(KINDS.vibe)?.frames || [])[Number(t.dataset.rvwIe)];
        const has = encodedKeys(frame || {}).some(k => Math.abs(k - Number(ie)) < 1e-6);
        encode.dataset.ie = ie;
        encode.textContent = `IE ${ie} 인코딩 (2 Anlas)`;
        encode.classList.toggle('is-hidden', has);
      }
    } else if (t.matches('[data-rvw-cr]')) {
      const out = panel.body.querySelector(`[data-rvw-cr-out="${t.dataset.rvwCr}:${t.dataset.index}"]`);
      if (out) out.textContent = fmt(Number(t.value) / 20);
    } else if (t.matches('[data-rvw-mrs]')) {
      const out = panel.body.querySelector(`[data-rvw-mrs-out="${t.dataset.rvwMrs}"]`);
      if (out) out.textContent = fmt(Number(t.value) / 100);
    } else if (t.matches('[data-rvw-q]')) {
      if (inClusters()) { clusters.q = t.value; renderStore(); return; }
      const state = lib[tab];
      state.q = t.value;
      win.clearTimeout(qTimer);
      qTimer = win.setTimeout(() => loadLibrary(true), 250);
    }
  }

  function onChange(event) {
    const t = event.target;
    if (t.matches('[data-rvw-rs]')) {
      setModuleParam(KINDS.vibe, `ref_strength_${t.dataset.rvwRs}`, fmt(Number(t.value) / 100));
    } else if (t.matches('[data-rvw-rsnum]')) {
      const value = Math.max(-1, Math.min(1, Number(t.value)));
      if (Number.isFinite(value)) setModuleParam(KINDS.vibe, `ref_strength_${t.dataset.rvwRsnum}`, fmt(value));
    } else if (t.matches('[data-rvw-ie]')) {
      // 인코딩된 IE 면 바로 쓴다. 아니면 인코딩 단추가 뜬다(값은 아직 안 보낸다 - 인코딩과 어긋난 IE 방지).
      const ie = fmt(Number(t.value) / 100);
      const frame = (getModuleState(KINDS.vibe)?.frames || [])[Number(t.dataset.rvwIe)];
      if (encodedKeys(frame || {}).some(k => Math.abs(k - Number(ie)) < 1e-6)) {
        setModuleParam(KINDS.vibe, `info_extracted_${t.dataset.rvwIe}`, ie);
      }
    } else if (t.matches('[data-rvw-mrs]')) {
      clusterOp({op: 'update', id: clusters.openId, index: Number(t.dataset.rvwMrs), rs: Number(fmt(Number(t.value) / 100))});
    } else if (t.matches('[data-rvw-cr]')) {
      setModuleParam(KINDS.cr, `${t.dataset.rvwCr}_${t.dataset.index}`, fmt(Number(t.value) / 20));
    } else if (t.matches('[data-rvw-type]')) {
      setModuleParam(KINDS.cr, `ref_type_${t.dataset.rvwType}`, t.value);
    } else if (t.matches('[data-rvw-normalize]')) {
      setModuleParam(KINDS.vibe, 'normalize', String(t.checked));
    } else if (t.matches('[data-rvw-sort]')) {
      lib[tab].sort = t.value;
      loadLibrary(true);
    } else if (t.matches('[data-rvw-libmodel]')) {
      lib.vibe.model = t.value;
      lib.vibe.selected = '';
      loadLibrary(true);
    }
  }

  function onKey(event) {
    const t = event.target;
    if (t.matches('[data-rvw-rsnum]') && event.key === 'Enter') { event.preventDefault(); t.blur(); }
    if (t.matches('[data-rvw-q]') && event.key === 'Escape' && t.value) {
      event.preventDefault();
      t.value = '';
      if (inClusters()) { clusters.q = ''; renderStore(); return; }
      lib[tab].q = '';
      loadLibrary(true);
    }
  }

  // ── 바깥에서 부르는 것 ───────────────────────────────────────────────────
  /** module_state 가 왔다(app.js onModuleState). 창이 닫혀 있어도 알약 배지는 맞춘다. */
  function render(moduleId) {
    if (moduleId !== KINDS.vibe && moduleId !== KINDS.cr) return;
    paintPill();
    if (!panel || !panel.isOpen()) return;
    renderHead();
    if (moduleId === KINDS[tab]) {
      // 보관함에서 새로 인코딩되면 목록에도 생긴다 - 열려 있는 쪽은 조용히 다시 받는다.
      const before = lastFrameSig[moduleId];
      const sig = frameSig(getModuleState(moduleId));
      lastFrameSig[moduleId] = sig;
      renderActive();
      if (before !== undefined && before !== sig && tab === 'vibe' && !inClusters()) loadLibrary(true);
    }
  }
  const lastFrameSig = {};
  function frameSig(state) {
    return (state?.frames || []).map(f => `${f.file_hash}:${(f.encoding_keys || []).length}`).join('|');
  }

  /** 모델 · 모드가 바뀌었다 - 알약과 탭의 '지원 안 함' 표시를 다시. */
  function refresh() {
    paintPill();
    if (!panel || !panel.isOpen()) return;
    lib.vibe.model = '';
    lib.vibe.loaded = false;
    lib.vibe.selected = '';
    renderAll();
    loadLibrary(true);
  }

  return {
    setVisible, isVisible, show, hide, isOpen, render, refresh,
    placePill, paintPill,
    pillElement: () => (pill && pill.classList.contains('open') ? pill : null),
  };
}
