/**
 * 이벤트 압축 창(사용자 지시 2026-10-23) - Search 창 Tag Filter 의 [⇊ 압축] 단추가 연다.
 *
 *   풀 6,158행 → 2,340 이벤트                                     G S Q E
 *   태그 수  ▁▃▇▅▃▂   6 – 11      빈도  ▁▂▃▅▇   1,320 – 3     <- 반씩 나란히(사용자 지시 2026-10-23)
 *            ●━━━━━●                    ●━━━━●              태그 수 = 이벤트에서 '세는' 태그 개수
 *   빈도 = 태그 하나가 나오는 이벤트 수(왼쪽 흔함 · 오른쪽 희귀 · 하늘색). 범위 밖 태그는 이벤트를 거르지 않고 태그 수에서만
 *   빠진다 - 목록에서 회색. 1girl · solo 같은 인원수 태그는 늘 센다(서버 PEOPLE 목록).
 *   [ 큰 묶음 먼저 ▾ ] [ 태그로 찾기 ]                    <- 찾기 칸 자동완성 = 지금 이벤트에 든 태그만
 *   1girl, breasts, navel, solo, thighs                                 ×60   <- 보기만. 누르면 [랜덤] [생성]
 *   ...
 *   특징 제거 · 체크 = 지운다 · Auto Hide n · 개별 숨김 n
 *   [✓ 캐릭터 특징] [ 의상 ] [ 의상 이벤트 ] [✓ 색상] [✓ 장소·배경]
 *   [ 표정 ] [✓ 포즈·동작] [✓ 메타 태그] [✓ 사물] [ 저빈도 태그 ]
 *
 * 이벤트 = 지금 PE 전처리를 건 뒤 남는 태그 집합(+ 등급). [커밋] = 걸러진 이벤트마다 1행으로 Tag Filter 를 좁힌다.
 * 압축 켬 단추(풀이 바뀔 때마다 실시간 재압축)는 회수했다(사용자 2026-10-23 - 풀이 10만 · 100만으로 커지면 비싸다 ·
 * 커밋 수와 이벤트 수가 어긋났다). 서버의 켬 상태는 불러올 때 꺼진다.
 * 아래 칸은 PE 창의 '특징 제거' 와 같은 설정이다 - 여기서 바꾸면 PE 창도 바뀌고 서버가 이벤트를 다시 센다.
 * 다시 세는 동안은 창을 막는다(사용자 지시 - 연달아 누르면 셈이 겹친다).
 * [랜덤] = 그 이벤트 행으로 메인 프롬프트 · [생성] = 그대로 한 장. 둘 다 풀을 소진하지 않는다.
 * 태그 수 컷은 목록만 거른다(사용자 결정 2026-10-23 - 나중에 Quick Filter 로 커밋할 수 있게).
 *
 * 서버 = /api/event-compress/{state,toggle,events,tags,random,generate} · WS event_compress_state.
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
const CUT_KEY = 'naia.ecw.tagcut';
const FREQ_CUT_KEY = 'naia.ecw.freqcut';
const BUSY_CAP_MS = 60000;           // 서버가 답을 못 주면 막은 창을 이만큼 뒤에 푼다

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
  reapplyTagFilter = () => false,  // Tag Filter [재적용] 과 같은 일 - 칩 조건으로 다시 걸어 원래 풀로(커밋 되돌리기)
  canReapply = () => false,        // 그 단추가 지금 쓸 수 있나(걸 조건이 있나)
} = {}) {
  let panel = null;
  let state = null;                // GET /state
  let items = [];
  let total = 0;
  let hist = {};                   // {태그 수: 이벤트 수} - 컷 · 찾기와 무관한 전체
  let histMin = 0;
  let histMax = 0;
  let cut = readCut(CUT_KEY);      // 태그 수 {min, max} - null = 끝까지
  let freqHist = {};               // {태그 빈도: 그 빈도의 태그 수} - 인원수 태그 · 컷 · 찾기와 무관한 전체
  let freqVals = [];               // 있는 빈도값 - 큰 것(흔함)부터 작은 것(희귀)까지. 눈금 = 이 값들(한 값에 쏠리지 않게)
  let cutFreq = readCut(FREQ_CUT_KEY);  // 빈도 {min, max} - 범위 밖 태그는 태그 수에서 빠진다 · null = 끝까지
  let listSeq = 0;
  let stateSeq = 0;
  let acSeq = 0;
  let loadingMore = false;
  let sort = 'desc';
  let query = '';
  let queryTimer = 0;
  let acTimer = 0;
  let ac = {items: [], index: -1, open: false};
  let open = '';                   // 펼친 이벤트 키
  let busy = '';                   // 'commit' | 'random:<key>' | 'generate:<key>'
  let waiting = false;             // 다시 세는 동안 창을 막는다
  let waitTimer = 0;
  let listSig = '';                // 목록을 다시 받을지 가르는 서명(풀 · 이벤트 수 · 켬)
  let commitRows = 0;              // 지금 컷 · 찾기로 커밋하면 Tag Filter 에 남을 행 수(서버가 센다)
  let eventsSig = '';              // 그 수를 센 분석의 서명 - 커밋 때 함께 보내 그사이 풀이 바뀌었으면 서버가 거절한다
  let sizedThisLaunch = false;     // 앱을 켠 뒤 처음 열 때 한 번 - 최소 폭으로 접는다(사용자 지시)
  let drag = null;
  let refreshTimer = 0;

  const escAttr = value => escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  const fmt = n => (Number(n) || 0).toLocaleString();

  function readCut(key) {
    try {
      const raw = JSON.parse(win.localStorage.getItem(key) || 'null');
      if (raw && typeof raw === 'object') {
        return {min: Number.isFinite(raw.min) ? raw.min : null, max: Number.isFinite(raw.max) ? raw.max : null};
      }
    } catch (_) { /* 없으면 끝까지 */ }
    return {min: null, max: null};
  }

  function saveCut() {
    try {
      win.localStorage.setItem(CUT_KEY, JSON.stringify(cut));
      win.localStorage.setItem(FREQ_CUT_KEY, JSON.stringify(cutFreq));
    } catch (_) { /* 이번 창에서만 */ }
  }

  /** 서버에 보낼 컷 - 전체 범위와 같으면 보내지 않는다(분포가 바뀌어도 '끝까지' 가 유지되게). */
  function cutParams() {
    const p = {};
    // 기억한 컷은 그대로 보낸다 - '끝까지' 는 손잡이를 끝에 놓을 때 null 로 저장된다(commitCut).
    // 지금 분포의 끝값과 비교해 빼면 안 된다: 막 연 창(분포 모름)이나, 커밋 직후(풀이 24–45 뿐이라 끝값 = 컷)
    // 다음 목록이 컷 없이 세어 [커밋 n행] 이 실제와 달랐다(실측 196 vs 184 · 468 vs 256).
    if (cut.min != null) p.min_tags = String(cut.min);
    if (cut.max != null) p.max_tags = String(cut.max);
    if (cutFreq.min != null) p.min_freq = String(cutFreq.min);
    if (cutFreq.max != null) p.max_freq = String(cutFreq.max);
    return p;
  }

  function ensurePanel() {
    if (panel) return panel;
    const width = 560;
    const height = 680;
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
      minWidth: 360,
      minHeight: 320,
      maxWidth: 1400,
      resizable: true,
      initial,
    });
    // 정렬 칸은 앱 표준 콤보박스(customSelects 가 mod-select-sm 을 바꿔 끼운다 - 사용자 지시 2026-10-23).
    panel.body.innerHTML = `<div class="ecw-body">`
      + `<div class="ecw-top" data-ecw-top></div>`
      + `<div class="ecw-cut" data-ecw-cut></div>`
      + `<div class="ecw-tools"><span class="ecw-sortbox"><select class="mod-select-sm" data-ecw-sort aria-label="정렬">`
      + `<option value="desc">큰 묶음 먼저</option><option value="asc">작은 묶음 먼저</option></select></span>`
      + `<span class="ecw-qbox"><input type="search" class="ecw-q" data-ecw-q placeholder="태그로 찾기" autocomplete="off" spellcheck="false">`
      + `<div class="ecw-ac" data-ecw-ac hidden></div></span>`
      + `<span class="ecw-cmt" data-ecw-cmt></span></div>`
      + `<div class="ecw-list" data-ecw-list></div>`
      + `<div class="ecw-pe" data-ecw-pe></div>`
      + `<div class="ecw-wait" data-ecw-wait hidden><span>이벤트를 다시 세는 중…</span></div></div>`;
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('change', onChange);
    panel.body.addEventListener('input', onInput);
    panel.body.addEventListener('keydown', onKeyDown);
    panel.body.addEventListener('pointerdown', onPointerDown);
    panel.body.addEventListener('focusout', onFocusOut);
    panel.body.querySelector('[data-ecw-list]').addEventListener('scroll', onScroll, {passive: true});
    return panel;
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────
  function renderTop() {
    const el = panel?.body.querySelector('[data-ecw-top]');
    if (!el) return;
    const s = state || {};
    const ratings = new Set(activeRatings());
    let count;
    if (!state) count = '<span class="ecw-dim">불러오는 중…</span>';
    else if (state.error) count = `<span class="ecw-dim">${escHtml(state.error)}</span>`;
    else if (s.scope === 'empty') count = '<span class="ecw-dim">풀이 비어 있습니다 — 검색이나 Tag Filter 를 먼저 거세요</span>';
    // 아직 안 셌다(stale - 꺼진 채 처음 연 창 · PE 를 바꾼 뒤)도 '세는 중' - 목록을 청하면 서버가 센다.
    else if (s.computing || s.stale) count = `<span class="ecw-dim">풀</span> ${fmt(s.pool_rows)}행 <span class="ecw-dim">→</span> <span class="ecw-dim">이벤트 세는 중…</span>`;
    else {
      count = `<span class="ecw-dim">풀</span> ${fmt(s.pool_rows)}행 <span class="ecw-dim">→</span> `
        + `<b class="ecw-events">${fmt(s.events)}</b> <span class="ecw-dim">이벤트</span>`;
    }
    const html = `<span class="ecw-count">${count}</span>`
      + `<span class="ecw-ratings">${['g', 's', 'q', 'e'].map(r => `<button type="button" class="rating-btn${ratings.has(r) ? ' active' : ''}"`
        + ` data-r="${r}" data-ecw-rating="${r}">${r.toUpperCase()}</button>`).join('')}</span>`;
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  }

  // ── 컷 슬라이더 둘(사용자 지시 2026-10-23) - Search [기간 컷오프] 와 같은 두 손잡이 트랙. 눈금 = 값 목록의 번호.
  //    태그 수: 값 = 최소 … 최대 태그 수(작은 것 → 큰 것). 왼쪽 손잡이 = min_tags · 오른쪽 = max_tags.
  //    빈도:    값 = 있는 태그 빈도(큰 것 = 흔함 → 작은 것 = 희귀). 왼쪽 손잡이 = max_freq · 오른쪽 = min_freq.
  //    손잡이를 끝에 두면 null(끝까지) 로 기억한다 - 풀이 바뀌어 끝값이 달라져도 '끝까지' 가 유지된다.
  function sliderVals(kind) {
    if (kind === 'freq') return freqVals;
    const vals = [];
    for (let n = histMin; n <= histMax && histMax > 0; n += 1) vals.push(n);
    return vals;
  }

  function edgeIndex(kind, edge) {
    const vals = sliderVals(kind);
    const last = vals.length - 1;
    if (last < 0) return 0;
    if (kind === 'tags') {
      if (edge === 'lo') { const i = cut.min == null ? 0 : vals.findIndex(v => v >= cut.min); return i < 0 ? last : i; }
      if (cut.max == null) return last;
      let i = last;
      while (i > 0 && vals[i] > cut.max) i -= 1;
      return i;
    }
    if (edge === 'lo') { const i = cutFreq.max == null ? 0 : vals.findIndex(v => v <= cutFreq.max); return i < 0 ? last : i; }
    if (cutFreq.min == null) return last;
    let i = last;
    while (i > 0 && vals[i] < cutFreq.min) i -= 1;
    return i;
  }

  function setEdgeIndex(kind, edge, index) {
    const vals = sliderVals(kind);
    const last = vals.length - 1;
    if (last < 0) return;
    let i = Math.max(0, Math.min(last, Math.round(index)));
    if (edge === 'lo') i = Math.min(i, edgeIndex(kind, 'hi'));
    else i = Math.max(i, edgeIndex(kind, 'lo'));
    const v = vals[i];
    if (kind === 'tags') {
      if (edge === 'lo') cut.min = i === 0 ? null : v; else cut.max = i === last ? null : v;
    } else if (edge === 'lo') cutFreq.max = i === 0 ? null : v;
    else cutFreq.min = i === last ? null : v;
  }

  function sliderHtml(kind) {
    const vals = sliderVals(kind);
    const head = kind === 'freq' ? '빈도' : '태그 수';
    const cls = kind === 'freq' ? 'ecw-cut-one is-freq' : 'ecw-cut-one';
    if (vals.length < 2) return `<div class="${cls}"><div class="ecw-cut-head"><span>${head}</span><span class="ecw-dim">—</span></div></div>`;
    const counts = kind === 'freq' ? freqHist : hist;
    const last = vals.length - 1;
    const lo = edgeIndex(kind, 'lo');
    const hi = edgeIndex(kind, 'hi');
    const pct = i => (i / last) * 100;
    const label = v => (kind === 'freq' ? fmt(v) : String(v));
    let top = 1;
    vals.forEach(v => { top = Math.max(top, Number(counts[v]) || 0); });
    const bars = vals.map((v, i) => {
      const c = Number(counts[v]) || 0;
      const tip = kind === 'freq' ? `이벤트 ${fmt(v)}개에 나오는 태그 · ${fmt(c)}개` : `세는 태그 ${v}개 · ${fmt(c)} 이벤트`;
      return `<span class="${i >= lo && i <= hi ? 'is-in' : ''}" style="height:${c ? Math.max(6, Math.round(Math.sqrt(c / top) * 100)) : 0}%"`
        + ` title="${tip}"></span>`;
    }).join('');
    const ends = kind === 'freq'
      ? `<span>흔함 ${label(vals[0])}</span><span>희귀 ${label(vals[last])}</span>`
      : `<span>${vals[0]}</span><span>${vals[last]}</span>`;
    return `<div class="${cls}"><div class="ecw-cut-head"><span>${head}</span>`
      + `<span class="ecw-cut-range">${label(vals[lo])} – ${label(vals[hi])}</span></div>`
      + `<div class="ecw-cut-bars">${bars}</div>`
      + `<div class="ecw-cut-track" data-ecw-track="${kind}"><div class="ecw-cut-fill" style="left:${pct(lo)}%;right:${100 - pct(hi)}%"></div>`
      + `<div class="ecw-cut-handle" data-ecw-slider="${kind}" data-ecw-edge="lo" tabindex="0" style="left:${pct(lo)}%"></div>`
      + `<div class="ecw-cut-handle" data-ecw-slider="${kind}" data-ecw-edge="hi" tabindex="0" style="left:${pct(hi)}%"></div></div>`
      + `<div class="ecw-cut-ends">${ends}</div></div>`;
  }

  function renderCut() {
    const el = panel?.body.querySelector('[data-ecw-cut]');
    if (!el) return;
    const html = histMax > histMin || freqVals.length > 1 ? sliderHtml('tags') + sliderHtml('freq') : '';
    if (el._html !== html) {
      // 다시 그리면 손잡이가 새 요소다 - 키보드로 옮기던 손잡이의 초점을 되돌린다(안 하면 한 칸 뒤 끊긴다).
      const a = el.contains(doc.activeElement) ? doc.activeElement.dataset : null;
      el._html = html;
      el.innerHTML = html;
      if (a && a.ecwSlider) el.querySelector(`[data-ecw-slider="${a.ecwSlider}"][data-ecw-edge="${a.ecwEdge}"]`)?.focus();
    }
  }

  /** 'b, a, 1girl' 을 abc 차례로(사용자 지시 - 1boy, 1girl, apron …). 빈도 컷 밖이라 태그 수에서 빠진 태그는 회색(사용자 지시 2026-10-23). */
  function tagsHtml(text, uncounted) {
    const off = new Set(Array.isArray(uncounted) ? uncounted : []);
    return String(text || '').split(', ').filter(Boolean).sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
      .map(t => (off.has(t) ? `<span class="ecw-t-off" title="빈도 컷 밖 - 태그 수에 세지 않습니다">${escHtml(t)}</span>` : escHtml(t)))
      .join(', ');
  }

  function renderList() {
    const el = panel?.body.querySelector('[data-ecw-list]');
    if (!el) return;
    let html;
    if (!state || (state.computing && !items.length)) html = '<div class="ecw-empty">이벤트를 세는 중…</div>';
    else if (state.error && !items.length) html = `<div class="ecw-empty">${escHtml(state.error)}</div>`;
    else if (!items.length) {
      const filtered = query || cut.min != null || cut.max != null;
      html = `<div class="ecw-empty">${filtered ? '맞는 이벤트가 없습니다.' : '이벤트가 없습니다.'}</div>`;
    }
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
          + `${tagsHtml(it.tags, it.uncounted)}<div class="ecw-bar" style="width:${Math.max(2, Math.round(size / top * 100))}%"></div></div>`
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

  /** [커밋 · n행] = 걸러진 이벤트로 Tag Filter 를 좁힌다(새 검색처럼) · [재적용] = 칩 조건으로 다시 걸어 되돌린다(사용자 지시 2026-10-23). */
  function renderCommit() {
    const el = panel?.body.querySelector('[data-ecw-cmt]');
    if (!el) return;
    const scopeOk = !!state && state.scope === 'tag_filter' && !state.error;
    const ready = scopeOk && !state.computing && !state.stale && commitRows > 0 && !busy;
    const title = !scopeOk
      ? 'Tag Filter 가 걸려 있을 때만 커밋합니다'
      : '걸러진 이벤트(태그 수 컷 · 찾기)마다 1행으로 Tag Filter 를 좁힙니다. 다 쓰면 이 행들로 다시 채웁니다. [재적용] 으로 원래 풀로 돌아갑니다';
    const html = `<button type="button" class="ecw-commit" data-ecw-commit${ready ? '' : ' disabled'} title="${escAttr(title)}">`
      + `커밋 · ${fmt(commitRows)}행</button>`
      + `<button type="button" class="ecw-reapply" data-ecw-reapply${canReapply() && !busy ? '' : ' disabled'}`
      + ` title="Tag Filter [재적용] 과 같습니다 - 칩 조건으로 다시 걸어 원래 풀로 돌아갑니다(커밋 되돌리기)">↻ 재적용</button>`;
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  }

  function renderPe() {
    const el = panel?.body.querySelector('[data-ecw-pe]');
    if (!el) return;
    const pe = (state && state.pe) || {};
    const options = pe.options || {};
    // PE 창과 같은 칸(.pe-opt-*) - 모양이 어긋나지 않게 그 클래스를 그대로 쓴다. 칸 폭만 5열 최소 폭(.ecw-pe).
    // 머리 글(사용자 지시 2026-10-23 · 연노랑) - 여기서 켜고 끄면 PE 창 · 지금 프리셋에도 들어간다는 것을 알린다.
    const html = `<div class="ecw-pe-head">[PE 특징 제거] - 여기에서 On/Off 시 현재 프리셋에도 반영됩니다</div>`
      + `<div class="pe-opt-list ecw-pe-grid">${PE_KEYS.map(([key, label]) => `<div class="pe-opt-cell"><label class="pe-opt-row">`
        + `<input type="checkbox" class="pe-opt-input" data-ecw-pe-key="${key}"${options[key] ? ' checked' : ''}>`
        + `<span class="pe-opt-check" aria-hidden="true"></span><span class="pe-opt-label">${escHtml(label)}</span></label></div>`).join('')}</div>`;
    if (el._html !== html) { el._html = html; el.innerHTML = html; }
  }

  function renderAc() {
    const el = panel?.body.querySelector('[data-ecw-ac]');
    if (!el) return;
    if (!ac.open || !ac.items.length) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    el.innerHTML = ac.items.map((it, i) => `<button type="button" class="ecw-ac-item${i === ac.index ? ' is-on' : ''}"`
      + ` data-ecw-ac-i="${i}"><span>${escHtml(it.tag)}</span><span class="ecw-dim">${fmt(it.events)}</span></button>`).join('');
  }

  function renderWait() {
    const el = panel?.body.querySelector('[data-ecw-wait]');
    if (el) el.hidden = !waiting;
  }

  function render() {
    if (!panel) return;
    renderTop();
    renderCut();
    renderList();
    renderCommit();
    renderPe();
    renderWait();
  }

  // ── 다시 세는 동안 막기 ─────────────────────────────────────────────────────
  function startWaiting() {
    waiting = true;
    renderWait();
    clearTimeout(waitTimer);
    waitTimer = win.setTimeout(() => { waitTimer = 0; stopWaiting(); }, BUSY_CAP_MS);
  }

  function stopWaiting() {
    if (!waiting) return;
    waiting = false;
    clearTimeout(waitTimer);
    waitTimer = 0;
    renderWait();
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
    else if (!state.computing && !state.stale) stopWaiting();
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
      const params = new URLSearchParams({sort, q: query, offset: String(offset), limit: String(PAGE), ...cutParams()});
      const body = await getJson(`/api/event-compress/events?${params}`);
      if (mine !== listSeq) return;
      const got = Array.isArray(body.items) ? body.items : [];
      items = more ? items.concat(got) : got;
      total = Number(body.total) || items.length;
      if (!more) {
        commitRows = Number(body.commit_rows) || 0;
        eventsSig = String(body.events_signature || '');
      }
      if (body.tag_count_hist && typeof body.tag_count_hist === 'object') {
        hist = body.tag_count_hist;
        histMin = Number(body.tag_count_min) || 0;
        histMax = Number(body.tag_count_max) || 0;
      }
      if (body.tag_freq_hist && typeof body.tag_freq_hist === 'object') {
        freqHist = body.tag_freq_hist;
        freqVals = Object.keys(freqHist).map(Number).filter(Number.isFinite).sort((a, b) => b - a);
      }
      if (!more && open && !items.some(it => it.key === open)) open = '';
      // 목록을 청해서 서버가 다시 셌다 - 윗줄의 수도 새것으로(꺼져 있을 때는 WS 가 안 올 수 있다).
      if (!more && state && state.stale) void refreshState();
      else if (!more) stopWaiting();
    } catch (error) {
      if (mine !== listSeq) return;
      if (!more) { items = []; total = 0; stopWaiting(); }
      showToast(error.message || String(error), 'error');
    } finally {
      if (more && mine === listSeq) loadingMore = false;
    }
    renderCut();
    renderList();
    renderCommit();
  }

  async function loadAc() {
    const input = panel?.body.querySelector('[data-ecw-q]');
    if (!input) return;
    const mine = ++acSeq;
    try {
      const params = new URLSearchParams({q: input.value.trim(), limit: '12', ...cutParams()});
      const body = await getJson(`/api/event-compress/tags?${params}`);
      if (mine !== acSeq) return;
      ac = {items: Array.isArray(body.items) ? body.items : [], index: -1, open: doc.activeElement === input};
    } catch (_) {
      if (mine !== acSeq) return;
      ac = {items: [], index: -1, open: false};
    }
    renderAc();
  }

  function pickAc(i) {
    const it = ac.items[i];
    const input = panel?.body.querySelector('[data-ecw-q]');
    if (!it || !input) return;
    input.value = it.tag;
    ac = {items: [], index: -1, open: false};
    renderAc();
    clearTimeout(queryTimer);
    query = it.tag;
    void loadList(false);
  }

  // ── 손 ──────────────────────────────────────────────────────────────────
  async function commit() {
    if (busy || waiting || !commitRows) return;
    busy = 'commit';
    startWaiting();
    renderCommit();
    const cutNow = cutParams();
    try {
      const body = await postJson('/api/event-compress/commit', {
        min_tags: cutNow.min_tags != null ? Number(cutNow.min_tags) : null,
        max_tags: cutNow.max_tags != null ? Number(cutNow.max_tags) : null,
        min_freq: cutNow.min_freq != null ? Number(cutNow.min_freq) : null,
        max_freq: cutNow.max_freq != null ? Number(cutNow.max_freq) : null,
        q: query, events_signature: eventsSig,
      });
      showToast(`${fmt(body.committed)}행으로 Tag Filter 를 좁혔습니다 - [재적용] 으로 원래 풀로 돌아갑니다`, 'info');
      if (body.state) applyState(body.state); else void refreshState();
    } catch (error) {
      stopWaiting();
      showToast(error.message || String(error), 'error');
      void loadList(false);          // 풀이 바뀌어 거절됐으면(stale) 새 목록 · 새 수로
    } finally {
      busy = '';
      renderCommit();
    }
  }

  function reapply() {
    if (busy || waiting || !canReapply()) return;
    if (!reapplyTagFilter()) { showToast('다시 걸 Tag Filter 조건이 없습니다', 'error'); return; }
    // 다시 걸린 풀은 tag_filter_assigned 로 알려진다(app.js 가 refresh 를 부른다) - 그때까지 막는다.
    startWaiting();
  }

  async function act(kind) {
    if (busy || waiting || !open) return;
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
    if (waiting) return;
    if (event.target.closest('[data-ecw-commit]')) { void commit(); return; }
    if (event.target.closest('[data-ecw-reapply]')) { reapply(); return; }
    const acItem = event.target.closest('[data-ecw-ac-i]');
    if (acItem) { pickAc(Number(acItem.dataset.ecwAcI)); return; }
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
      if (waiting) { pe.checked = !pe.checked; return; }
      // 다시 세는 동안 창을 막는다(사용자 지시 2026-10-23) - 서버가 PE 를 바꾼 뒤 상태를 다시 묻는다.
      startWaiting();
      setPeOption?.(pe.dataset.ecwPeKey, pe.checked);
      win.setTimeout(() => { void refreshState(); }, 350);
    }
  }

  function onInput(event) {
    const q = event.target.closest('[data-ecw-q]');
    if (!q) return;
    clearTimeout(queryTimer);
    queryTimer = win.setTimeout(() => { queryTimer = 0; query = q.value.trim(); void loadList(false); }, 200);
    clearTimeout(acTimer);
    acTimer = win.setTimeout(() => { acTimer = 0; void loadAc(); }, 120);
  }

  function onKeyDown(event) {
    const q = event.target.closest('[data-ecw-q]');
    if (q && ac.open && ac.items.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const n = ac.items.length;
        ac.index = (ac.index + (event.key === 'ArrowDown' ? 1 : -1) + n) % n;
        renderAc();
        return;
      }
      if (event.key === 'Enter' && ac.index >= 0) { event.preventDefault(); pickAc(ac.index); return; }
      if (event.key === 'Escape') { event.preventDefault(); ac.open = false; renderAc(); return; }
    }
    const handle = event.target.closest('[data-ecw-edge]');
    if (handle && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) {
      event.preventDefault();
      const kind = handle.dataset.ecwSlider;
      const edge = handle.dataset.ecwEdge;
      setEdgeIndex(kind, edge, edgeIndex(kind, edge) + (event.key === 'ArrowRight' ? 1 : -1));
      renderCut();
      commitCut();
    }
  }

  function onFocusOut(event) {
    if (!event.target.closest('[data-ecw-q]')) return;
    // 항목을 누르는 사이 닫히지 않게 한 박자 뒤에.
    win.setTimeout(() => { if (doc.activeElement !== event.target) { ac.open = false; renderAc(); } }, 150);
  }

  function commitCut() {
    saveCut();
    void loadList(false);
  }

  /** 트랙 위 x -> 눈금 번호. */
  function indexAt(kind, clientX) {
    const track = panel.body.querySelector(`[data-ecw-track="${kind}"]`);
    if (!track) return 0;
    const rect = track.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(1, rect.width)));
    return f * Math.max(0, sliderVals(kind).length - 1);
  }

  function onPointerDown(event) {
    const handle = event.target.closest('[data-ecw-edge]');
    if (!handle || waiting) return;
    event.preventDefault();
    handle.focus();                  // preventDefault 가 초점을 막는다 - 이어서 ← → 로 한 칸씩 옮길 수 있게
    drag = {kind: handle.dataset.ecwSlider, edge: handle.dataset.ecwEdge};
    handle.classList.add('is-drag');
    const move = e => { if (drag) { setEdgeIndex(drag.kind, drag.edge, indexAt(drag.kind, e.clientX)); renderCut(); } };
    const up = () => {
      doc.removeEventListener('pointermove', move);
      doc.removeEventListener('pointerup', up);
      doc.removeEventListener('pointercancel', up);
      drag = null;
      commitCut();
    };
    doc.addEventListener('pointermove', move);
    doc.addEventListener('pointerup', up);
    doc.addEventListener('pointercancel', up);
  }

  function onScroll(event) {
    const list = event.currentTarget;
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 60) void loadList(true);
  }

  /** 앱을 켠 뒤 처음 열 때 - 아래 '특징 제거' 5칸이 딱 들어가는 최소 폭으로 접는다(사용자 지시 2026-10-23). */
  function fitMinWidth() {
    if (sizedThisLaunch || !panel) return;
    const grid = panel.body.querySelector('.ecw-pe-grid');
    // 칸 묶음은 width: max-content(.ecw-pe-grid) - 그 폭이 곧 5칸이 딱 들어가는 폭이다.
    const natural = grid ? grid.getBoundingClientRect().width : 0;
    if (!natural) return;
    sizedThisLaunch = true;
    const pe = panel.body.querySelector('[data-ecw-pe]');
    const style = win.getComputedStyle(pe);
    const pad = (Number.parseFloat(style.paddingLeft) || 0) + (Number.parseFloat(style.paddingRight) || 0);
    // 지금 칸 자리(pe 폭)와 필요한 폭의 차이만큼 창을 줄이거나 늘린다 - 창 테 · 본문 여백을 따로 셀 필요가 없다.
    const rect = panel.el.getBoundingClientRect();
    const delta = natural + pad - pe.getBoundingClientRect().width;
    panel.sizeTo(Math.ceil(rect.width + delta + 1), rect.height);
  }

  return {
    open() {
      ensurePanel();
      if (panel.isOpen()) panel.raise(); else panel.open();
      if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
      render();
      // 숨은 탭에서는 requestAnimationFrame 이 안 온다 - 한 박자 뒤 재기만 하면 된다(배치는 open 이 이미 했다).
      win.setTimeout(() => fitMinWidth(), 0);
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
    /** PE 설정 · 등급 · Tag Filter 할당이 다른 곳에서 바뀌었다 - 열려 있으면 다시 묻는다(몰려 오면 한 번). */
    refresh() {
      if (!panel || !panel.isOpen()) return;
      clearTimeout(refreshTimer);
      refreshTimer = win.setTimeout(() => { refreshTimer = 0; renderCommit(); void refreshState(); }, 250);
    },
    isOpen: () => !!(panel && panel.isOpen()),
  };
}
