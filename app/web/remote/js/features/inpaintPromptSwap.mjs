/** 인페인트 프롬프트 스왑 - 프롬프트 칸 아래 칩 줄 + 설정 창(사용자 지정 2026-11-03).
 *
 *  V5 로 만든 그림을 V4.5 로(또는 그 반대로) 인페인트할 때, 그림에 박힌 옛 프리셋의 앞뒤 태그 · 작가를
 *  다른 프리셋 것으로 한 번에 바꾸고 **이 세션의 인페인트 모델**도 함께 바꾼다. 메인 모델은 그대로다.
 *
 *      ┌ 프롬프트 칸 ───────────────────────────────────────┐
 *      │ ...                                                │
 *      │ [원본] [4.5F 작가믹스] [5M 미디엄]        [⚙ 설정] │  ← 칩 줄(칸 맨 아래에 붙는다)
 *      └────────────────────────────────────────────────────┘
 *
 *  - [원본] = 세션을 열 때 그림에 있던 프롬프트 · 네거티브 · 모델로 되돌린다.
 *  - 최근 칩 둘 = 설정 창에서 [적용] 한 조합(모델 + 프리셋 + 작가 · 네거티브 처리). **누를 때 자리를 바꾸지 않는다** -
 *    누른 것을 앞으로 당기면 손에 익은 칩이 밀려 엉뚱한 것을 누른다(사용자 결정). 새 조합을 적용할 때만
 *    1번 자리에 들어가고 오래된 것이 빠진다. 같은 모델 + 프리셋이면 그 자리에서 옵션만 고친다.
 *  - 계산은 서버가 한다(`/api/img2img/prompt-swap/*`). 바탕은 늘 **세션을 열 때의 프롬프트**라 스왑이 겹치지 않는다.
 *
 *  ⚠️ 최근 목록은 localStorage(기기별)다 - 인페인트 ⚙ 의 1MP 옵션과 같은 자리 규칙.
 *  ⚠️ 칩 줄은 두 화면이 같은 HTML 을 쓴다(V5 캔버스 = 왼쪽 메인 프롬프트 칸, V4.5 = img2img 팝업의 메인 칸).
 *     클릭은 문서에서 한 번에 받는다 - 팝업은 상태가 올 때마다 innerHTML 로 다시 그려진다.
 */

const STORE_KEY = 'naia.inpaint.promptSwap.v1';
const RECENT_MAX = 2;
// 보이는 모델 칩. 사용자층은 대개 4.5F · 5F · 5M 셋만 쓴다(사용자 지정) - 4.5C · 5C 는 설정에서 켤 때만.
const MODELS_BASE = ['NAID4.5F', 'NAID5F', 'NAID5FM'];
const MODELS_CURATED = ['NAID4.5C', 'NAID5C'];
const SHORT = {
  'NAID4.5F': '4.5F', 'NAID4.5C': '4.5C', 'NAID4.5': '4.5F',
  'NAID5F': '5F', 'NAID5FM': '5M', 'NAID5C': '5C',
};
const FAMILY = {
  'NAID4.5F': 'v4.5', 'NAID4.5C': 'v4.5', 'NAID4.5': 'v4.5',
  'NAID5F': 'v5', 'NAID5FM': 'v5', 'NAID5C': 'v5',
};
// 이 모델은 네거티브를 쓰지 않는다(nai_model_contract: supports_negative_prompt=False).
const NO_NEGATIVE = new Set(['NAID5FM']);

export function shortModel(key) {
  return SHORT[key] || String(key || '').replace(/^NAID/, '');
}

function sameEntry(a, b) {
  return !!a && !!b && a.model === b.model && a.preset === b.preset
    && (a.artist_mode || 'preset') === (b.artist_mode || 'preset')
    && (a.negative_mode || 'preset') === (b.negative_mode || 'preset');
}

export function createInpaintPromptSwap({
  document: doc,
  window: win,
  escHtml,
  showToast = () => {},
  loadDraggablePanel,          // () => Promise<createDraggablePanel>
  getSession = () => null,     // () => img2img 모듈 상태(active 일 때)
  getPresets = () => [],       // () => PE preset_summaries (NAI)
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  fetchFn = (...args) => fetch(...args),
  takePendingEdit = () => null,    // 아직 안 보낸(0.5초 묶음) 메인 · 네거티브 편집을 꺼내 쥔다(다른 칸 것은 보낸다)
  restorePendingEdit = () => {},   // 꺼내 쥔 편집을 보낸다 - 스왑이 실패했을 때
} = {}) {
  let store = readStore();
  // 창별 기준 글: 마지막으로 서버가 넣어 준 메인 · 네거티브. 지금 글이 이것과 다르면 사람이 고친 것이다.
  const baseline = new Map();   // window_id -> {main, neg}
  let shownWindow = null;       // 설정 창이 미리보기를 그린 세션
  let busy = false;

  function readStore() {
    try {
      const raw = JSON.parse(storage?.getItem(STORE_KEY) || '{}');
      const recent = Array.isArray(raw.recent) ? raw.recent.filter(e => e && e.model && e.preset) : [];
      return {recent: recent.slice(0, RECENT_MAX), curated: !!raw.curated, draft: raw.draft || null};
    } catch (_) {
      return {recent: [], curated: false, draft: null};
    }
  }
  function writeStore() {
    try { storage?.setItem(STORE_KEY, JSON.stringify(store)); } catch (_) {}
  }

  // ── 칩 줄 ──────────────────────────────────────────────────────────────
  function rowHtml(state) {
    if (!state || !state.active || String(state.mode || '') !== 'inpaint') return '';
    const swap = state.swap && typeof state.swap === 'object' ? state.swap : null;
    const chips = [`<button type="button" class="ips-chip${swap ? '' : ' is-on'}" data-ips="original"`
      + ` title="그림에 있던 프롬프트 · 네거티브 · 모델로">원본</button>`];
    store.recent.forEach((entry, index) => {
      const on = swap && sameEntry(swap, entry);
      const artist = entry.artist_mode === 'keep' ? '원본 유지' : '프리셋 것';
      chips.push(`<button type="button" class="ips-chip${on ? ' is-on' : ''}" data-ips="recent" data-ips-index="${index}"`
        + ` title="${escHtml(`${entry.preset} · 작가 ${artist}`)}">`
        + `<b>${escHtml(shortModel(entry.model))}</b><span>${escHtml(entry.preset)}</span></button>`);
    });
    const model = String(state.effective_model || '');
    const note = model ? `<span class="ips-model" title="이 세션의 인페인트 모델">${escHtml(shortModel(model))}</span>` : '';
    return `<div class="ips-row" role="toolbar" aria-label="인페인트 프롬프트 스왑">${chips.join('')}`
      + `<span class="ips-gap"></span>${note}`
      + `<button type="button" class="ips-chip ips-settings" data-ips="settings">설정</button></div>`;
  }

  /** V5 캔버스 쪽 자리(왼쪽 메인 프롬프트 칸)에 그린다. 세션이 없으면 숨긴다. */
  function renderInto(host, state) {
    if (!host) return;
    const html = rowHtml(state);
    const wrap = host.closest('.prompt-highlight-wrap');
    host.hidden = !html;
    wrap?.classList.toggle('has-inpaint-swap', !!html);
    if (host.dataset.ipsHtml !== html) {
      host.innerHTML = html;
      host.dataset.ipsHtml = html;
    }
  }

  /** 상태가 올 때마다 부른다 - 창이 바뀌면 기준 글을 새로 잡는다. */
  function texts(state) {
    return {main: String(state?.main_prompt || ''), neg: String(state?.negative_prompt || '')};
  }

  function noteState(state) {
    const id = state && state.active ? Number(state.window_id || 0) : null;
    if (id === null) baseline.clear();
    else if (!baseline.has(id)) baseline.set(id, texts(state));
    if (!panel?.isOpen()) return;
    paintPanelHead();
    // 다른 그림의 세션이 됐다 - 옛 세션의 미리보기(와 오는 중인 답)를 버리고 새로 묻는다.
    if (id !== shownWindow) {
      shownWindow = id;
      previewSeq += 1;
      lastPreview = null;
      schedulePreview();
    }
  }

  // 지금 화면에 보이는 세션 글 칸. 친 글은 잠깐(디바운스) 서버보다 앞서 있다 - 상태만 보면 방금 친 것을
  // 고친 것으로 못 본다. 네거티브 칸은 V4.5 팝업에만 있다(V5 캔버스는 세션 네거티브를 칸에 안 띄운다).
  function visibleTexts() {
    const popup = doc.getElementById('img2imgMainPrompt');
    if (popup && popup.offsetParent) {
      return {main: popup.value, neg: doc.getElementById('img2imgNegativePrompt')?.value ?? null};
    }
    const host = doc.getElementById('inpaintSwapRow');
    if (host && !host.hidden) return {main: doc.getElementById('promptEdit')?.value ?? null, neg: null};
    return {main: null, neg: null};
  }

  function editedSinceSwap(state) {
    const id = Number(state?.window_id || 0);
    if (!baseline.has(id)) return false;
    const base = baseline.get(id);
    const now = texts(state);
    const shown = visibleTexts();
    return base.main !== now.main || base.neg !== now.neg
      || (shown.main !== null && shown.main !== base.main)
      || (shown.neg !== null && shown.neg !== base.neg);
  }

  async function post(path, body) {
    const res = await fetchFn(path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) throw new Error((data && (data.error || data.detail)) || `HTTP ${res.status}`);
    return data || {};
  }

  async function apply(body, {label = ''} = {}) {
    const state = getSession();
    if (!state || !state.active) { showToast('인페인트 세션이 없습니다', 'error'); return false; }
    if (busy) return false;
    if (editedSinceSwap(state)
      && !win.confirm('프롬프트를 고친 내용이 있습니다. 바꾸면 그 내용은 사라집니다. 계속할까요?')) return false;
    // ⚠️ 0.5초 묶음으로 쥐고 있던 메인 · 네거티브 편집을 꺼낸다. 두면 스왑이 끝난 뒤에 깨어나 **새 프롬프트를
    //    옛 글로** 덮는다 - 모델만 바뀐 채로(Codex 리뷰 2026-11-03). 버려도 되는 것은 위에서 사용자가 동의했기
    //    때문이다. 캐릭터 칸 편집은 스왑이 건드리지 않으니 지금 보낸다(꺼내는 쪽이 한다).
    const held = takePendingEdit();
    busy = true;
    try {
      const data = await post('/api/img2img/prompt-swap/apply', {...body, window_id: state.window_id});
      // 답의 state 는 module_state 포장({type, module_id, state})이다 - 벗겨야 기준 글이 바뀐다.
      const next = data.state?.state || data.state || data;
      if (next && next.active) baseline.set(Number(next.window_id || 0), texts(next));
      if (label) showToast(label, 'success');
      return true;
    } catch (error) {
      // 스왑이 안 됐다 - 꺼내 둔 편집을 되살린다. 그사이 다른 세션이 됐으면 그 세션에 쓰지 않는다.
      if (held && Number(getSession()?.window_id || 0) === Number(state.window_id || 0)) restorePendingEdit(held);
      showToast(`프롬프트를 바꾸지 못했습니다: ${error.message || error}`, 'error');
      return false;
    } finally {
      busy = false;
    }
  }

  function entryBody(entry) {
    return {
      preset: entry.preset, model: entry.model,
      artist_mode: entry.artist_mode === 'keep' ? 'keep' : 'preset',
      negative_mode: entry.negative_mode === 'keep' ? 'keep' : 'preset',
      keep: Array.isArray(entry.keep) ? entry.keep : [],
    };
  }

  doc.addEventListener('click', event => {
    const btn = event.target.closest?.('[data-ips]');
    if (!btn || btn.closest('.ips-panel')) return;
    const kind = btn.dataset.ips;
    if (kind === 'settings') { void toggle(); return; }
    if (kind === 'original') {
      void apply({original: true}, {label: '원본 프롬프트로 되돌렸습니다'});
      return;
    }
    if (kind === 'recent') {
      const entry = store.recent[Number(btn.dataset.ipsIndex)];
      if (entry) void apply(entryBody(entry), {label: `${shortModel(entry.model)} · ${entry.preset}`});
    }
  });

  // ── 설정 창 ────────────────────────────────────────────────────────────
  let panel = null;
  let opening = null;
  let content = null;
  // 창에서 고르는 중인 조합. 마지막 고름을 기억해 다시 열 때 이어 간다.
  const draft = Object.assign(
    {model: 'NAID4.5F', preset: '', artist_mode: 'preset', negative_mode: 'preset', keep: []},
    store.draft || {},
  );
  let previewSeq = 0;
  let previewTimer = null;
  let lastPreview = null;

  function modelsShown() {
    const list = [...MODELS_BASE];
    if (store.curated) list.splice(1, 0, MODELS_CURATED[0]), list.push(MODELS_CURATED[1]);
    if (!list.includes(draft.model)) list.push(draft.model);
    return list;
  }

  function presetsFor(model) {
    const family = FAMILY[model] || '';
    // `*randomized` 같은 `*` 항목은 저장된 프리셋이 아니라 PE 의 가상 줄이다 - 읽을 글이 없다.
    const rows = (getPresets() || []).filter(p => p && p.name && !String(p.name).startsWith('*')
      && String(p.api_mode || 'NAI').toUpperCase() === 'NAI');
    const same = rows.filter(p => p.model_key === model);
    const fam = rows.filter(p => p.model_key !== model && p.model_family === family);
    const none = rows.filter(p => !p.model_family);
    return {same, fam, none};
  }

  function presetOptions() {
    const {same, fam, none} = presetsFor(draft.model);
    const opt = p => `<option value="${escHtml(p.name)}"${p.name === draft.preset ? ' selected' : ''}>${escHtml(p.name)}</option>`;
    const group = (label, rows) => rows.length ? `<optgroup label="${escHtml(label)}">${rows.map(opt).join('')}</optgroup>` : '';
    const html = group(shortModel(draft.model), same) + group('같은 계열', fam) + group('모델 미지정', none);
    return html || '<option value="">이 계열의 프리셋이 없습니다</option>';
  }

  function ensurePresetValid() {
    const {same, fam, none} = presetsFor(draft.model);
    const all = [...same, ...fam, ...none];
    if (!all.some(p => p.name === draft.preset)) {
      draft.preset = all[0]?.name || '';
      draft.keep = [];
    }
  }

  function seg(key, value, label) {
    const on = (draft[key] || 'preset') === value;
    return `<button type="button" class="ips-seg${on ? ' is-on' : ''}" data-ipsp="${key}" data-value="${value}">${label}</button>`;
  }

  function buildContent() {
    content = doc.createElement('div');
    content.className = 'ips-panel';
    content.innerHTML = `
      <div class="ips-head" data-ipsp-head></div>
      <div class="ips-line"><span class="ips-k">모델</span><span class="ips-models" data-ipsp-models></span></div>
      <label class="ips-curated"><input type="checkbox" data-ipsp-curated><span>4.5C · 5C 보이기</span></label>
      <div class="ips-line"><span class="ips-k">프리셋</span><select class="ips-select" data-ipsp-preset></select></div>
      <div class="ips-line"><span class="ips-k">작가</span><span class="ips-segs" data-ipsp-artist></span></div>
      <div class="ips-line"><span class="ips-k">네거티브</span><span class="ips-segs" data-ipsp-negative></span></div>
      <div class="ips-sub" data-ipsp-source></div>
      <div class="ips-sub-title">지울 작가 <span>눌러서 남기기</span></div>
      <div class="ips-removed" data-ipsp-removed></div>
      <div class="ips-sub-title">결과 미리보기</div>
      <div class="ips-preview" data-ipsp-preview></div>
      <div class="ips-neg-note" data-ipsp-negnote hidden></div>
      <div class="ips-actions"><button type="button" class="ips-apply" data-ipsp-apply>적용</button></div>`;
    content.addEventListener('click', onPanelClick);
    content.addEventListener('change', onPanelChange);
    paintControls();
  }

  function paintPanelHead() {
    const head = content?.querySelector('[data-ipsp-head]');
    if (!head) return;
    const state = getSession();
    if (!state || !state.active || state.mode !== 'inpaint') {
      head.textContent = '인페인트 세션이 열려 있을 때 미리보기와 적용이 됩니다.';
      return;
    }
    const src = state.source_model ? shortModel(state.source_model) : '알 수 없음';
    head.innerHTML = `원본 <b>${escHtml(src)}</b> 그림 · 지금 인페인트 모델 <b>${escHtml(shortModel(state.effective_model || ''))}</b>`;
  }

  function paintControls() {
    if (!content) return;
    ensurePresetValid();
    content.querySelector('[data-ipsp-models]').innerHTML = modelsShown().map(key =>
      `<button type="button" class="ips-seg${key === draft.model ? ' is-on' : ''}" data-ipsp="model" data-value="${escHtml(key)}">`
      + `${escHtml(shortModel(key))}</button>`).join('');
    content.querySelector('[data-ipsp-curated]').checked = store.curated;
    content.querySelector('[data-ipsp-preset]').innerHTML = presetOptions();
    content.querySelector('[data-ipsp-artist]').innerHTML = seg('artist_mode', 'keep', '원본 유지') + seg('artist_mode', 'preset', '프리셋 것');
    content.querySelector('[data-ipsp-negative]').innerHTML = seg('negative_mode', 'preset', '프리셋 것') + seg('negative_mode', 'keep', '원본 유지');
    const note = content.querySelector('[data-ipsp-negnote]');
    note.hidden = !NO_NEGATIVE.has(draft.model);
    note.textContent = '5M 은 네거티브를 쓰지 않습니다 - 넣어도 보내지 않습니다.';
    paintPanelHead();
  }

  function saveDraft() {
    store.draft = {...draft};
    writeStore();
  }

  function onPanelClick(event) {
    const btn = event.target.closest('[data-ipsp]');
    if (btn) {
      const key = btn.dataset.ipsp;
      if (key === 'model') {
        draft.model = btn.dataset.value;
        draft.keep = [];
      } else {
        draft[key] = btn.dataset.value;
      }
      saveDraft();
      paintControls();
      schedulePreview();
      return;
    }
    const gone = event.target.closest('[data-ipsp-keep]');
    if (gone) {
      const raw = gone.dataset.ipspKeep;
      draft.keep = draft.keep.includes(raw) ? draft.keep.filter(k => k !== raw) : [...draft.keep, raw];
      saveDraft();
      schedulePreview();
      return;
    }
    if (event.target.closest('[data-ipsp-apply]')) void applyDraft();
  }

  function onPanelChange(event) {
    if (event.target.matches('[data-ipsp-preset]')) {
      draft.preset = event.target.value;
      draft.keep = [];
      saveDraft();
      schedulePreview();
    } else if (event.target.matches('[data-ipsp-curated]')) {
      store.curated = !!event.target.checked;
      writeStore();
      paintControls();
    }
  }

  function schedulePreview() {
    if (previewTimer) win.clearTimeout(previewTimer);
    previewTimer = win.setTimeout(() => { previewTimer = null; void runPreview(); }, 120);
  }

  function paintPreview(data, error = '') {
    if (!content) return;
    const removedEl = content.querySelector('[data-ipsp-removed]');
    const previewEl = content.querySelector('[data-ipsp-preview]');
    const sourceEl = content.querySelector('[data-ipsp-source]');
    if (error) {
      removedEl.innerHTML = '';
      sourceEl.textContent = '';
      previewEl.textContent = error;
      previewEl.classList.add('is-muted');
      return;
    }
    previewEl.classList.remove('is-muted');
    const src = data.source_preset;
    sourceEl.textContent = src
      ? (src.recorded ? `원본 프리셋: ${src.name} (생성 때 기록)` : `원본 프리셋 추정: ${src.name} (앞뒤 태그 ${src.total}개 중 ${src.matched}개 일치)`)
      : '원본 프리셋을 찾지 못했습니다 - 앞뒤 태그는 그대로 두고 작가만 정리합니다.';
    // 지운 것 + 남기기로 한 것을 함께 보여야 다시 지울 수 있다.
    const removed = Array.isArray(data.removed) ? data.removed : [];
    const keptRows = draft.keep.filter(k => !removed.some(r => r.raw === k)).map(k => ({raw: k, kept: true}));
    const rows = [...removed, ...keptRows];
    const why = {prefix: 'artist: 접두', dictionary: '작가 사전', anchor: '작가 묶음 표식'};
    removedEl.innerHTML = rows.length
      ? rows.map(row => `<button type="button" class="ips-gone${row.kept ? ' is-kept' : ''}" data-ipsp-keep="${escHtml(row.raw)}"`
        + ` title="${escHtml(row.kept ? '남기는 중 - 누르면 지웁니다' : (why[row.reason] || ''))}">${escHtml(row.raw)}</button>`).join('')
      : `<span class="ips-none">${draft.artist_mode === 'keep' ? '원본 유지 - 그림의 작가를 지우지 않습니다' : '지울 작가가 없습니다'}</span>`;
    previewEl.textContent = String(data.main_prompt || '');
  }

  async function runPreview() {
    if (!content || !panel?.isOpen()) return;
    const state = getSession();
    if (!state || !state.active || state.mode !== 'inpaint') {
      paintPreview(null, '인페인트 세션을 열면 여기서 결과를 미리 봅니다.');
      return;
    }
    if (!draft.preset) { paintPreview(null, '프리셋을 고르세요.'); return; }
    const seq = ++previewSeq;
    // 첫 미리보기는 서버가 작가 사전을 읽느라 몇 초 걸린다 - 빈 칸으로 두면 고장 난 것처럼 보인다.
    if (!lastPreview) paintPreview(null, '미리보기를 만드는 중…');
    try {
      const data = await post('/api/img2img/prompt-swap/preview', {...entryBody(draft), window_id: state.window_id});
      if (seq !== previewSeq) return;
      lastPreview = data;
      paintPreview(data);
    } catch (error) {
      if (seq !== previewSeq) return;
      lastPreview = null;
      paintPreview(null, `미리보기 실패: ${error.message || error}`);
    }
  }

  async function applyDraft() {
    if (!draft.preset) { showToast('프리셋을 고르세요', 'error'); return; }
    const entry = entryBody(draft);
    const ok = await apply(entry, {label: `${shortModel(entry.model)} · ${entry.preset}`});
    if (!ok) return;
    // 같은 모델 + 프리셋이 있으면 그 자리에서 옵션만 고친다. 없으면 1번 자리로, 오래된 것은 빠진다.
    const at = store.recent.findIndex(e => e.model === entry.model && e.preset === entry.preset);
    if (at >= 0) store.recent[at] = entry;
    else store.recent = [entry, ...store.recent].slice(0, RECENT_MAX);
    writeStore();
    refreshRows();
  }

  // 칩 줄은 상태가 올 때 다시 그려지지만, 최근 목록만 바뀐 경우를 위해 지금 다시 그린다.
  let onRecentChange = () => {};
  function refreshRows() { onRecentChange(); }

  async function ensure() {
    if (panel) return panel;
    if (opening) return opening;
    opening = (async () => {
      const createDraggablePanel = await loadDraggablePanel();
      panel = createDraggablePanel({
        document: doc, window: win,
        variant: 'pewin ips-window',
        title: '인페인트 프롬프트 스왑',
        storageKey: 'inpaint-prompt-swap',
        width: 400, height: 470, minWidth: 320, maxWidth: 720, minHeight: 260,
        resizable: true,
        escHtml,
      });
      buildContent();
      panel.body.appendChild(content);
      return panel;
    })();
    try { return await opening; } finally { opening = null; }
  }

  async function toggle() {
    const p = await ensure();
    if (p.isOpen()) { p.close(); return; }
    p.open();
    shownWindow = getSession()?.active ? Number(getSession().window_id || 0) : null;
    paintControls();
    void runPreview();
  }

  return {
    rowHtml,
    renderInto,
    noteState,
    toggle,
    // 프리셋 목록이 바뀌면(PE 상태) 창의 고름 칸을 다시 채운다.
    syncPresets: () => { if (panel?.isOpen()) paintControls(); },
    setOnRecentChange: fn => { onRecentChange = typeof fn === 'function' ? fn : () => {}; },
    isOpen: () => !!(panel && panel.isOpen()),
  };
}
