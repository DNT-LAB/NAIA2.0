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
    return {model: '', filter: 'all', groupId: '', q: '', sort: 'recent', items: [], total: 0, offset: 0,
      loading: false, seq: 0, groups: [], counts: {}, models: [], currentModel: '', supported: true,
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
        width: 520, height: 620, minWidth: 380, minHeight: 300, maxWidth: 1100,
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
        : (frame.encoding_in_progress ? `<span class="rvw-hint">인코딩 중…</span>` : ''))
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
  function renderStore() {
    if (!panel) return;
    const host = panel.body.querySelector('[data-rvw-store]');
    const state = lib[tab];
    const grid = host.querySelector('[data-rvw-grid]');
    const gridTop = grid ? grid.scrollTop : 0;
    const counts = state.counts || {};
    const groupCounts = counts.groups || {};
    const models = tab === 'vibe' && state.models.length > 1
      ? `<select class="rvw-sel" data-rvw-libmodel>${state.models.map(m => `<option value="${escHtml(m.key)}"${m.key === state.model ? ' selected' : ''}>${escHtml(m.key)} ${m.count}</option>`).join('')}</select>`
      : (state.model ? `<span class="rvw-sec-n">${escHtml(state.model)}</span>` : '');
    const chip = (filter, groupId, label, count) => {
      const on = state.filter === filter && (filter !== 'group' || state.groupId === groupId);
      return `<button type="button" class="rvw-chip${on ? ' on' : ''}" data-rvw-filter="${filter}" data-group="${escHtml(groupId)}">${escHtml(label)} <b>${count ?? 0}</b></button>`;
    };
    const chips = chip('all', '', '전체', counts.all)
      + chip('favorite', '', '★', counts.favorite)
      + state.groups.map(g => chip('group', g.id, g.name, groupCounts[g.id] ?? g.count)).join('')
      + chip('ungrouped', '', '미분류', counts.ungrouped)
      + `<button type="button" class="rvw-chip is-new" data-rvw-act="newgroup">+ 그룹</button>`;
    const cards = state.items.map(item => storeCard(item)).join('');
    const empty = state.loading ? '불러오는 중…'
      : (state.error ? escHtml(state.error)
        : (state.q || state.filter !== 'all' ? '맞는 항목이 없습니다.' : '보관된 항목이 없습니다. 위에서 올리고 인코딩하면 여기에 쌓입니다.'));
    // 틀(머리줄 · 검색칸)은 탭이 바뀔 때만 새로 짓는다. 치는 중에 목록이 오면 검색칸이 통째로 갈려
    // 초점을 잃었다 - 칩 · 격자 · 고른 항목 줄만 갈아 끼운다.
    if (host.dataset.tab !== tab || !host.querySelector('[data-rvw-grid]')) {
      host.dataset.tab = tab;
      host.innerHTML = `<div class="rvw-sec"><span class="rvw-sec-t">STORAGE</span><span class="rvw-sec-m" data-rvw-models></span>`
        + `<span class="rvw-sec-tools"><input type="search" class="rvw-q" placeholder="이름 검색" spellcheck="false" autocomplete="off" data-rvw-q>`
        + `<select class="rvw-sel" data-rvw-sort>`
        + [['recent', '최근순'], ['used', '사용순'], ['name', '이름순']].map(([v, l]) => `<option value="${v}">${l}</option>`).join('')
        + `</select></span></div>`
        + `<div class="rvw-chips" data-rvw-chips></div>`
        + `<div class="rvw-grid" data-rvw-grid></div>`
        + `<div data-rvw-pickhost></div>`;
      host.querySelector('[data-rvw-grid]').addEventListener('scroll', onGridScroll, {passive: true});
    }
    host.querySelector('[data-rvw-models]').innerHTML = models;
    const input = host.querySelector('[data-rvw-q]');
    if (doc.activeElement !== input && input.value !== state.q) input.value = state.q;
    host.querySelector('[data-rvw-sort]').value = state.sort;
    host.querySelector('[data-rvw-chips]').innerHTML = chips;
    const nextGrid = host.querySelector('[data-rvw-grid]');
    nextGrid.innerHTML = (cards || `<div class="rvw-empty">${empty}</div>`)
      + (state.items.length && state.items.length < state.total ? `<div class="rvw-more">${state.items.length} / ${state.total}</div>` : '');
    nextGrid.scrollTop = gridTop;
    host.querySelector('[data-rvw-pickhost]').innerHTML = selectionBar();
  }

  function storeCard(item) {
    const hash = String(item.file_hash || '');
    const name = String(item.display_name || item.name || item.file_name || hash);
    const selected = lib[tab].selected === hash ? ' is-sel' : '';
    const img = item.has_image === false || !item.thumbnail_url
      ? `<span class="rvw-card-im is-empty">enc</span>`
      : `<img class="rvw-card-im" loading="lazy" src="${escHtml(item.thumbnail_url)}" alt="">`;
    const ieCount = tab === 'vibe' ? `<span class="rvw-card-ie">${(item.encoding_keys || []).length}</span>` : '';
    return `<button type="button" class="rvw-card${selected}" data-rvw-card="${escHtml(hash)}">${img}`
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
      + `<button type="button" class="rvw-btn" data-rvw-act="groups">그룹 ▾</button>`
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

  function libraryUrl(state, offset) {
    const params = new URLSearchParams({kind: API_KIND[tab], sort: state.sort, offset: String(offset), limit: String(PAGE)});
    if (tab === 'vibe' && state.model) params.set('model', state.model);
    params.set('filter', state.filter);
    if (state.filter === 'group' && state.groupId) params.set('group_id', state.groupId);
    if (state.q.trim()) params.set('q', state.q.trim());
    return `/api/ref-vibe/library?${params}`;
  }

  /** 목록 받기. `reset` 이면 처음부터, 아니면 이어서(끝까지 굴렸을 때). */
  async function loadLibrary(reset = false) {
    if (!panel || !panel.isOpen()) return;
    const kind = tab;
    const state = lib[kind];
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
      state.groups = Array.isArray(data.groups) ? data.groups : [];
      state.counts = data.counts || {};
      state.models = Array.isArray(data.models) ? data.models : [];
      state.currentModel = String(data.current_model || '');
      if (!state.model && data.model) state.model = String(data.model);
      state.supported = data.model_supported !== false;
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

  // ── 동작 ──────────────────────────────────────────────────────────────────
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

  async function toggleFavorite() {
    const item = selectedItem();
    if (!item) return;
    try {
      const data = await api('/api/ref-vibe/library/item', {method: 'POST',
        body: {kind: API_KIND[tab], file_hash: item.file_hash, favorite: !item.favorite, model: lib[tab].model}});
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

  async function refreshCounts() {
    // 그룹 · ★ 수는 목록 응답에 실려 온다 - 지금 쪽만 다시 받는다(항목은 그대로 둔다).
    const state = lib[tab];
    try {
      const data = await api(libraryUrl(state, 0).replace(`limit=${PAGE}`, 'limit=1'));
      state.counts = data.counts || state.counts;
      state.groups = Array.isArray(data.groups) ? data.groups : state.groups;
      renderStore();
    } catch (_) { /* 수는 다음 목록에서 맞춰진다 */ }
  }

  async function newGroup() {
    const name = await promptDialog('그룹 이름', {title: '새 그룹', placeholder: 'semireal'});
    if (!name || !String(name).trim()) return;
    try {
      await api('/api/ref-vibe/library/group', {method: 'POST', body: {kind: API_KIND[tab], op: 'create', name: String(name).trim(), model: lib[tab].model}});
      refreshCounts();
    } catch (error) {
      showToast(`그룹을 못 만들었습니다: ${error.message || error}`, 'error');
    }
  }

  async function setMembership(groupId, add) {
    const item = selectedItem();
    if (!item) return;
    try {
      const data = await api('/api/ref-vibe/library/group-members', {method: 'POST',
        body: {kind: API_KIND[tab], group_id: groupId, op: add ? 'add' : 'remove', file_hashes: [item.file_hash], model: lib[tab].model}});
      replaceItems(data.items || []);
      if (data.counts) lib[tab].counts = data.counts;
      if (lib[tab].filter === 'group' || lib[tab].filter === 'ungrouped') loadLibrary(true);
      else renderStore();
    } catch (error) {
      showToast(`그룹을 못 바꿨습니다: ${error.message || error}`, 'error');
    }
  }

  async function groupOp(groupId, op) {
    const group = lib[tab].groups.find(g => g.id === groupId);
    if (!group) return;
    if (op === 'apply-clean' || op === 'apply-append') {
      setModuleParam(KINDS.vibe, 'apply_group', JSON.stringify({group_id: groupId, mode: op === 'apply-clean' ? 'clean' : 'append'}));
      return;
    }
    try {
      if (op === 'rename') {
        const name = await promptDialog('그룹 이름', {title: '그룹 이름 바꾸기', defaultValue: group.name});
        if (!name || !String(name).trim()) return;
        await api('/api/ref-vibe/library/group', {method: 'POST', body: {kind: API_KIND[tab], op: 'rename', group_id: groupId, name: String(name).trim(), model: lib[tab].model}});
      } else if (op === 'delete') {
        if (!await confirmDialog(`그룹 "${group.name}" 을 지웁니다. 항목은 보관함에 그대로 남습니다.`)) return;
        await api('/api/ref-vibe/library/group', {method: 'POST', body: {kind: API_KIND[tab], op: 'delete', group_id: groupId, model: lib[tab].model}});
        if (lib[tab].groupId === groupId) { lib[tab].filter = 'all'; lib[tab].groupId = ''; }
      }
      loadLibrary(true);
    } catch (error) {
      showToast(`그룹 작업을 못 했습니다: ${error.message || error}`, 'error');
    }
  }

  // ── 작은 메뉴(그룹 칩 우클릭 · 항목의 그룹 ▾) ─────────────────────────────
  function closeMenu() {
    if (!menu) return;
    menu.remove();
    menu = null;
    doc.removeEventListener('pointerdown', onMenuOutside, true);
  }

  function onMenuOutside(event) {
    if (menu && !menu.contains(event.target)) closeMenu();
  }

  function openMenu(anchor, html, onPick) {
    closeMenu();
    menu = doc.createElement('div');
    menu.className = 'rvw-menu';
    menu.innerHTML = html;
    doc.body.appendChild(menu);
    const box = anchor.getBoundingClientRect();
    const width = menu.offsetWidth;
    const left = Math.min(box.left, win.innerWidth - width - 8);
    const below = box.bottom + 4;
    const top = below + menu.offsetHeight > win.innerHeight - 8 ? Math.max(8, box.top - menu.offsetHeight - 4) : below;
    menu.style.left = `${Math.max(8, Math.round(left))}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.addEventListener('click', event => {
      const item = event.target.closest('[data-rvw-menu]');
      if (!item) return;
      const keep = onPick(item.dataset.rvwMenu, item) === 'keep';
      if (!keep) closeMenu();
    });
    doc.addEventListener('pointerdown', onMenuOutside, true);
  }

  function openGroupsMenu(anchor) {
    const item = selectedItem();
    if (!item) return;
    const mine = new Set(item.groups || []);
    const groups = lib[tab].groups;
    const rows = groups.length
      ? groups.map(g => `<button type="button" class="rvw-menu-i" data-rvw-menu="${escHtml(g.id)}">${mine.has(g.id) ? '☑' : '☐'} ${escHtml(g.name)}</button>`).join('')
      : `<div class="rvw-menu-h">그룹이 없습니다</div>`;
    openMenu(anchor, rows + `<button type="button" class="rvw-menu-i is-new" data-rvw-menu="__new">+ 새 그룹</button>`, id => {
      if (id === '__new') { newGroup(); return; }
      setMembership(id, !mine.has(id));
    });
  }

  function openGroupChipMenu(anchor, groupId) {
    const rows = (tab === 'vibe'
      ? `<button type="button" class="rvw-menu-i" data-rvw-menu="apply-clean">이 그룹으로 바꾸기</button>`
        + `<button type="button" class="rvw-menu-i" data-rvw-menu="apply-append">이 그룹 더하기</button>`
      : '')
      + `<button type="button" class="rvw-menu-i" data-rvw-menu="rename">이름 바꾸기</button>`
      + `<button type="button" class="rvw-menu-i is-danger" data-rvw-menu="delete">그룹 지우기</button>`;
    openMenu(anchor, rows, op => { groupOp(groupId, op); });
  }

  function openImportMenu(anchor) {
    openMenu(anchor, `<button type="button" class="rvw-menu-i" data-rvw-menu="file">.naiv4vibe / .naiv4vibebundle 파일…</button>`, () => {
      panel.body.querySelector('[data-rvw-import]').click();
    });
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
      state.filter = el.dataset.rvwFilter;
      state.groupId = el.dataset.group || '';
      loadLibrary(true);
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
      else if (act === 'fav') toggleFavorite();
      else if (act === 'groups') openGroupsMenu(el);
      else if (act === 'delete') deleteSelected();
      else if (act === 'newgroup') newGroup();
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
    const chip = event.target.closest('[data-rvw-filter="group"]');
    if (!chip) return;
    event.preventDefault();
    openGroupChipMenu(chip, chip.dataset.group);
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
    } else if (t.matches('[data-rvw-q]')) {
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
      if (before !== undefined && before !== sig && tab === 'vibe') loadLibrary(true);
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
    renderAll();
    loadLibrary(true);
  }

  return {
    setVisible, isVisible, show, hide, isOpen, render, refresh,
    placePill, paintPill,
    pillElement: () => (pill && pill.classList.contains('open') ? pill : null),
  };
}
