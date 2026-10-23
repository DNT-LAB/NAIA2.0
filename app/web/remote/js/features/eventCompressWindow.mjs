/**
 * 이벤트 압축 창(사용자 지시 2026-10-23) - Search 창 Tag Filter 의 [⇊ 이벤트] 단추가 연다.
 *
 *   [ ⇊ 압축 켬 ]  풀 6,158행 → 2,340 이벤트                       G S Q E
 *   [ 큰 묶음 먼저 ▾ ] [ 태그로 찾기 ]
 *   1girl, solo, standing, looking at viewer, hand on own hips        ×214   <- 보기만. 누르면 [랜덤] [생성] 이 펼쳐진다
 *   ...
 *   특징 제거 · 체크 = 지운다 · Auto Hide n · 개별 숨김 n
 *   [✓ 캐릭터 특징] [ 의상 ] [ 의상 이벤트 ] [✓ 색상] [✓ 장소·배경]
 *   [ 표정 ] [✓ 포즈·동작] [✓ 메타 태그] [✓ 사물] [ 저빈도 태그 ]
 *
 * 이벤트 = 지금 PE 전처리를 건 뒤 남는 태그 집합(+ 등급). 압축을 켜면 이벤트마다 1행만 풀에 남는다(서버가 한다).
 * 아래 칸은 PE 창의 '특징 제거' 와 같은 설정이다 - 여기서 바꾸면 PE 창도 바뀌고 서버가 이벤트를 다시 센다.
 * [랜덤] = 그 이벤트 행으로 메인 프롬프트 · [생성] = 그대로 한 장. 둘 다 풀을 소진하지 않는다.
 *
 * 서버 = /api/event-compress/{state,toggle,events,random,generate} · WS event_compress_state.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

// PE 창 '특징 제거' 묶음과 같은 키 · 이름 · 차례(promptEngineeringPanel.mjs PP_OPTIONS). 5칸 x 2줄.
const PE_KEYS = [
  ['remove_character_features', '캐릭터 특징'],
  ['remove_clothes', '의상'],
  ['remove_clothing_event', '의상 이벤트'],
  ['remove_color', '색상'],
  ['remove_location_and_background_color', '장소 · 배경'],
  ['remove_expression', '표정'],
  ['remove_pose_action', '포즈 · 동작'],
  ['remove_meta_tags', '메타 태그'],
  ['remove_object_tags', '사물'],
  ['remove_noise_tags', '저빈도 태그'],
];
const PAGE = 60;

export function createEventCompressWindow({
  document: doc = document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  setPeOption = null,              // (key, checked) - PE 창과 같은 길(setPromptEngineeringOption)
  toggleRating = null,             // (r) - Tag Filter 의 G/S/Q/E 와 같은 길
  activeRatings = () => [],        // 지금 켜진 등급 ['g', 's', ...]
  onStateChange = null,            // (state) - Search 창 단추의 노란 테
  anchorRect = () => null,         // 처음 뜰 자리 = 이 사각형(Search 창)의 오른쪽 - 사용자 지정 2026-10-23
} = {}) {
  let panel = null;
  let state = null;                // GET /state
  let items = [];
  let total = 0;
  let listSeq = 0;
  let stateSeq = 0;
  let loadingMore = false;
  let sort = 'desc';
  let query = '';
  let queryTimer = 0;
  let peTimer = 0;
  let open = '';                   // 펼친 이벤트 키
  let busy = '';                   // 'toggle' | 'random:<key>' | 'generate:<key>'
  let listSig = '';                // 목록을 다시 받을지 가르는 서명(풀 · 이벤트 수 · 켬)

  const escAttr = value => escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  const fmt = n => (Number(n) || 0).toLocaleString();

  function ensurePanel() {
    if (panel) return panel;
    const width = 620;
    const height = 640;
    const rect = anchorRect();
    const vw = win.innerWidth || 1280;
    const vh = win.innerHeight || 800;
    const initial = rect
      ? {x: Math.round(Math.max(6, Math.min(rect.right + 8, vw - width - 6))),
         y: Math.round(Math.max(6, Math.min(rect.top, vh - height - 6)))}
      : {right: 24, y: 90};
    panel = createDraggablePanel({
      document: doc,
      title: '이벤트 압축',
      variant: 'ecw',
      storageKey: 'event-compress',
      width,
      height,
      minWidth: 460,
      minHeight: 320,
      maxWidth: 1400,
      resizable: true,
      initial,
    });
    panel.body.innerHTML = `<div class="ecw-body">`
      + `<div class="ecw-top" data-ecw-top></div>`
      + `<div class="ecw-tools"><select class="ecw-sort" data-ecw-sort>`
      + `<option value="desc">큰 묶음 먼저</option><option value="asc">작은 묶음 먼저</option></select>`
      + `<input type="search" class="ecw-q" data-ecw-q placeholder="태그로 찾기 — 띄어 쓰면 모두 든 것" autocomplete="off" spellcheck="false"></div>`
      + `<div class="ecw-list" data-ecw-list></div>`
      + `<div class="ecw-pe" data-ecw-pe></div></div>`;
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('change', onChange);
    panel.body.addEventListener('input', onInput);
    panel.body.querySelector('[data-ecw-list]').addEventListener('scroll', onScroll, {passive: true});
    return panel;
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────
  function renderTop() {
    const el = panel?.body.querySelector('[data-ecw-top]');
    if (!el) return;
    const s = state || {};
    const on = !!s.enabled;
    const ratings = new Set(activeRatings());
    let count;
    if (!state) count = '<span class="ecw-dim">불러오는 중…</span>';
    else if (state.error) count = `<span class="ecw-dim">${escHtml(state.error)}</span>`;
    else if (s.scope === 'empty') count = '<span class="ecw-dim">풀이 비어 있습니다 — 검색이나 Tag Filter 를 먼저 거세요</span>';
    // 아직 안 셌다(stale - 꺼진 채 처음 연 창 등)도 '세는 중' - 목록을 청하면 서버가 센다. 0 이벤트로 보이면 안 된다.
    else if (s.computing || s.stale) count = `<span class="ecw-dim">풀</span> ${fmt(s.pool_rows)}행 <span class="ecw-dim">→</span> <span class="ecw-dim">이벤트 세는 중…</span>`;
    else {
      count = `<span class="ecw-dim">풀</span> ${fmt(s.pool_rows)}행 <span class="ecw-dim">→</span> `
        + `<b class="ecw-events">${fmt(s.events)}</b> <span class="ecw-dim">이벤트</span>`
        + (on ? '' : ' <span class="ecw-dim">(미적용)</span>');
    }
    const html = `<button type="button" class="ecw-toggle${on ? ' is-on' : ''}" data-ecw-toggle${busy === 'toggle' ? ' disabled' : ''}`
      + ` title="켜면 이벤트마다 1행만 풀에 남깁니다 · 끄면 뺀 행을 되돌립니다(Random 이 이미 쓴 행은 그대로)">`
      + `⇊ 압축 ${on ? '켬' : '끔'}</button>`
      + `<span class="ecw-count">${count}</span>`
      + `<span class="ecw-ratings">${['g', 's', 'q', 'e'].map(r => `<button type="button" class="rating-btn${ratings.has(r) ? ' active' : ''}"`
        + ` data-r="${r}" data-ecw-rating="${r}">${r.toUpperCase()}</button>`).join('')}</span>`;
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  }

  function renderList() {
    const el = panel?.body.querySelector('[data-ecw-list]');
    if (!el) return;
    let html;
    if (!state || (state.computing && !items.length)) html = '<div class="ecw-empty">이벤트를 세는 중…</div>';
    else if (state.error && !items.length) html = `<div class="ecw-empty">${escHtml(state.error)}</div>`;
    else if (!items.length) html = `<div class="ecw-empty">${query ? '맞는 이벤트가 없습니다.' : '이벤트가 없습니다.'}</div>`;
    else {
      const top = Math.max(1, ...items.map(it => Number(it.size) || 0));
      html = items.map(it => {
        const key = String(it.key || '');
        const size = Number(it.size) || 0;
        const used = !(Number(it.remaining) > 0);
        const isOpen = key === open;
        const acts = isOpen
          ? `<div class="ecw-acts">`
            + `<button type="button" class="ecw-act" data-ecw-act="random"${busy ? ' disabled' : ''}`
            + ` title="이 이벤트 행으로 메인 프롬프트를 채웁니다(Random 과 같은 파이프라인 · 풀은 그대로)">랜덤</button>`
            + `<button type="button" class="ecw-act is-gen" data-ecw-act="generate"${busy ? ' disabled' : ''}`
            + ` title="이 이벤트 행으로 바로 한 장 생성합니다(메인 프롬프트는 그대로)">생성</button></div>`
          : '';
        return `<div class="ecw-row${isOpen ? ' is-open' : ''}${used ? ' is-used' : ''}" data-ecw-key="${escAttr(key)}">`
          + `<div class="ecw-head" data-ecw-head><div class="ecw-tags">`
          + `<span class="ecw-r ecw-r-${escAttr(it.rating || '')}">${escHtml(String(it.rating || '').toUpperCase())}</span>`
          + `${escHtml(it.tags || '')}<div class="ecw-bar" style="width:${Math.max(2, Math.round(size / top * 100))}%"></div></div>`
          + `<span class="ecw-size" title="${used ? '이 이벤트는 Random 이 이미 썼습니다' : '묶인 행 수'}">×${fmt(size)}</span></div>`
          + acts + `</div>`;
      }).join('');
      if (items.length < total) html += `<div class="ecw-more">${loadingMore ? '불러오는 중…' : `${fmt(items.length)} / ${fmt(total)} — 스크롤하면 이어서`}</div>`;
    }
    if (el._html !== html) {
      const keep = el.scrollTop;
      el._html = html;
      el.innerHTML = html;
      el.scrollTop = keep;
    }
  }

  function renderPe() {
    const el = panel?.body.querySelector('[data-ecw-pe]');
    if (!el) return;
    const pe = (state && state.pe) || {};
    const options = pe.options || {};
    const extra = [];
    if (Number(pe.auto_hide_count) > 0) extra.push(`Auto Hide ${fmt(pe.auto_hide_count)}`);
    if (Number(pe.hide_count) > 0) extra.push(`개별 숨김 ${fmt(pe.hide_count)}`);
    // PE 창과 같은 칸(.pe-opt-*) - 모양이 어긋나지 않게 그 클래스를 그대로 쓴다. 칸 폭만 5열 최소 폭(.ecw-pe).
    const html = `<div class="ecw-pe-head">특징 제거<span>체크 = 지운다 · 남는 태그로 같은 이벤트를 가른다${extra.length ? ` · ${extra.join(' · ')}` : ''}</span></div>`
      + `<div class="pe-opt-list ecw-pe-grid">${PE_KEYS.map(([key, label]) => `<div class="pe-opt-cell"><label class="pe-opt-row">`
        + `<input type="checkbox" class="pe-opt-input" data-ecw-pe-key="${key}"${options[key] ? ' checked' : ''}>`
        + `<span class="pe-opt-check" aria-hidden="true"></span><span class="pe-opt-label">${escHtml(label)}</span></label></div>`).join('')}</div>`;
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  }

  function render() {
    if (!panel) return;
    renderTop();
    renderList();
    renderPe();
  }

  // ── 서버 ─────────────────────────────────────────────────────────────────
  async function getJson(url, init) {
    const res = await fetch(url, {cache: 'no-store', ...(init || {})});
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.ok === false) throw new Error(body.message || body.error || `요청이 실패했습니다(${res.status}).`);
    return body;
  }

  function postJson(url, payload) {
    return getJson(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload || {})});
  }

  function sigOf(s) {
    return s ? [s.scope, s.pool_rows, s.events, s.enabled ? 1 : 0, s.computing ? 1 : 0].join('|') : '';
  }

  /** 상태를 받는다 - 풀 · 이벤트 수 · 켬이 바뀌었으면 목록도 처음부터. */
  function applyState(next) {
    state = next;
    onStateChange?.(state);
    const sig = sigOf(state);
    // stale = PE 설정 · 풀이 바뀌어 다시 셀 차례. 꺼져 있으면 서버는 스스로 세지 않는다 - 목록을 청하면 센다.
    const relist = (sig !== listSig || !!state.stale) && !state.computing;
    if (!state.computing) listSig = sig;
    render();
    if (relist) void loadList(false);
  }

  async function refreshState() {
    if (!panel || !panel.isOpen()) return;
    const mine = ++stateSeq;
    let next;
    try {
      next = await getJson('/api/event-compress/state');
    } catch (error) {
      next = {error: error.message || String(error)};
    }
    if (mine !== stateSeq) return;
    applyState(next);
  }

  /** more=false 면 처음부터, true 면 다음 쪽을 붙인다. 조건이 바뀌면 늦은 답은 버린다. */
  async function loadList(more) {
    if (!panel || !panel.isOpen()) return;
    if (more && (loadingMore || items.length >= total)) return;
    const mine = more ? listSeq : ++listSeq;
    const offset = more ? items.length : 0;
    if (more) { loadingMore = true; renderList(); }
    try {
      const params = new URLSearchParams({sort, q: query, offset: String(offset), limit: String(PAGE)});
      const body = await getJson(`/api/event-compress/events?${params}`);
      if (mine !== listSeq) return;
      const got = Array.isArray(body.items) ? body.items : [];
      items = more ? items.concat(got) : got;
      total = Number(body.total) || items.length;
      if (!more && open && !items.some(it => it.key === open)) open = '';
      // 목록을 청해서 서버가 다시 셌다 - 윗줄의 수도 새것으로(꺼져 있을 때는 WS 가 안 올 수 있다).
      if (!more && state && state.stale) void refreshState();
    } catch (error) {
      if (mine !== listSeq) return;
      if (!more) { items = []; total = 0; }
      showToast(error.message || String(error), 'error');
    } finally {
      if (more && mine === listSeq) loadingMore = false;
    }
    renderList();
  }

  // ── 손 ──────────────────────────────────────────────────────────────────
  async function toggle() {
    if (busy || !state || state.error) return;
    busy = 'toggle';
    renderTop();
    try {
      applyState(await postJson('/api/event-compress/toggle', {enabled: !state.enabled}));
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      busy = '';
      renderTop();
    }
  }

  async function act(kind) {
    if (busy || !open) return;
    const item = items.find(it => it.key === open);
    if (!item) return;
    busy = `${kind}:${open}`;
    renderList();
    try {
      await postJson(`/api/event-compress/${kind}`, {key: item.key, requestId: `ecw-${Date.now().toString(36)}`});
      showToast(kind === 'random' ? '이 이벤트로 메인 프롬프트를 채웠습니다' : '이 이벤트로 생성을 요청했습니다', 'info');
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      busy = '';
      renderList();
    }
  }

  function onClick(event) {
    if (event.target.closest('[data-ecw-toggle]')) { void toggle(); return; }
    const rating = event.target.closest('[data-ecw-rating]');
    if (rating) {
      toggleRating?.(rating.dataset.ecwRating);
      // 등급은 Tag Filter 쪽이 다시 건다 - 그 뒤 서버가 상태를 알린다. 단추 모양만 먼저.
      win.setTimeout(() => { renderTop(); }, 0);
      return;
    }
    const button = event.target.closest('[data-ecw-act]');
    if (button) { void act(button.dataset.ecwAct); return; }
    const head = event.target.closest('[data-ecw-head]');
    if (head) {
      const key = head.closest('[data-ecw-key]')?.dataset.ecwKey || '';
      open = open === key ? '' : key;
      renderList();
    }
  }

  function onChange(event) {
    const sel = event.target.closest('[data-ecw-sort]');
    if (sel) { sort = sel.value === 'asc' ? 'asc' : 'desc'; void loadList(false); return; }
    const pe = event.target.closest('[data-ecw-pe-key]');
    if (pe) {
      setPeOption?.(pe.dataset.ecwPeKey, pe.checked);
      // 서버가 PE 를 바꾸고 이벤트를 다시 센다(켜져 있으면 WS 로 알린다). 꺼져 있을 때도 수가 바뀌므로 잠시 뒤 다시 묻는다.
      clearTimeout(peTimer);
      peTimer = win.setTimeout(() => { peTimer = 0; void refreshState(); }, 350);
    }
  }

  function onInput(event) {
    const q = event.target.closest('[data-ecw-q]');
    if (!q) return;
    clearTimeout(queryTimer);
    queryTimer = win.setTimeout(() => { queryTimer = 0; query = q.value.trim(); void loadList(false); }, 200);
  }

  function onScroll(event) {
    const list = event.currentTarget;
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 60) void loadList(true);
  }

  return {
    open() {
      ensurePanel();
      if (panel.isOpen()) panel.raise(); else panel.open();
      if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
      render();
      listSig = '';
      void refreshState();
    },
    toggleOpen() {
      if (panel && panel.isOpen()) panel.close(); else this.open();
    },
    /** WS event_compress_state - 열려 있으면 그린다. 닫혀 있어도 Search 창 단추 모양은 따라간다. */
    onState(message) {
      const next = {...(message || {})};
      delete next.type;
      if (!panel || !panel.isOpen()) { state = next; onStateChange?.(state); return; }
      stateSeq += 1;                   // 도는 GET 의 늦은 답이 이것을 덮지 않게
      applyState(next);
    },
    /** PE 설정 · 등급이 다른 곳에서 바뀌었다 - 열려 있으면 다시 묻는다. */
    refresh() { void refreshState(); },
    isOpen: () => !!(panel && panel.isOpen()),
  };
}
