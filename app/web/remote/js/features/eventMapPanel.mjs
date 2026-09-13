/* Event Map — Ctrl+E 로 여는 **이벤트 추적** 창.
 *
 * 태그를 하나 꽂으면 그것과 **같은 게시물에 실제로 함께 달린** 태그가 lift 순으로 나온다.
 * 하나를 누르면 그것이 다음 핀이 되어 한 단계 깊이 들어가고(빵부스러기 줄에 쌓인다),
 * 부스러기를 누르거나 ← 로 언제든 앞 단계로 돌아온다(사용자 스케치 2026-09-12).
 *
 * 서버가 다 계산한다(`/api/event-map/*`). 여기서는 그리기·키·삽입·복사만 한다.
 *
 * ⚠️ Fast Search(Ctrl+F)와 계약이 다르다. 저쪽은 **클립보드 전용**이고, 이 창은
 *    **삽입과 복사 둘 다** 한다(사용자 지시 2026-09-11). 삽입은 Tag Search 와 같은
 *    `insertTagIntoPrompt` 를 빌려 커서 자리에 넣는다 - 프롬프트를 덮지 않는다.
 *
 * 실측이 정한 세 가지(2026-09-12, full-20260912 색인):
 *  1. **인원 태그(1girl·solo)는 핀이 아니라 분면 필터다.** 핀으로 꽂으면 `1girl+solo`
 *     교집합이 457만건이라 1초가 걸리고 후보는 lift 2~4 짜리 잡음이다. 같은 것을 분면
 *     `1girl_solo` 로 보내면 112ms 에 같은 답이 나온다. 그래서 프롬프트의 인원 태그는
 *     `/resolve` 가 `person_group` 으로 돌려주고, 여기서 인원 필터에 넣는다.
 *  2. **프롬프트를 통째로 심으면 무너진다.** 화면의 프롬프트 13개를 전부 핀으로 꽂으니
 *     1건이 남았다. 그래서 프롬프트의 태그는 **씨앗 칩**으로만 보이고, 사용자가 하나를
 *     골라야 첫 핀이 된다. 핀이 없으면 explore 를 부르지 않는다.
 *  3. 깊이 1부터는 200ms 남짓이고 lift 30~500 으로 뜻이 있다. 추적은 거기서부터다.
 *
 * 크기 규약은 Fast Search 와 같다(결과 칸 가운데, 폭 ≤ 720, 높이 ≤ 결과 칸의 절반).
 */

import { initEventMapLibrary } from './eventMapLibrary.mjs?v=20260913-library3';

const DEBOUNCE_MS = 150;
const CANDIDATE_LIMIT = 40;
const SUGGEST_LIMIT = 12;
const SAMPLE_COUNT = 5;
const RATING_OPTIONS = [
  { id: 'g', label: 'G', title: 'General' },
  { id: 's', label: 'S', title: 'Sensitive' },
  { id: 'q', label: 'Q', title: 'Questionable' },
  { id: 'e', label: 'E', title: 'Explicit' },
];
// 인원 13분면. 묶음과 기본값은 Fast Search 와 같다(여성이 들어간 구성 전부).
const PERSON_GROUPS = [
  { g: '여성', ids: ['1girl_solo', '1girl', '2girls', 'multiple_girls'] },
  { g: '혼성', ids: ['1girl_1boy', '1girl_multiple_boys', '1boy_multiple_girls', 'multiple_girls_multiple_boys'] },
  { g: '남성', ids: ['1boy_solo', '1boy', '2boys', 'multiple_boys'] },
  { g: '기타', ids: ['other'] },
];
const PERSON_IDS = PERSON_GROUPS.flatMap(group => group.ids);
// 첫 시작 기본값(사용자 지정 2026-09-12): 여1 단독 · 여1 · 여1 남1 · 여1 남다수. 그 뒤로는
// 사용자가 바꾼 대로 브라우저에 기억한다(프롬프트의 인원 태그로 **덮어쓰지 않는다**).
// 기본 = 여1 단독 · S 등급(사용자 지정 2026-09-12 밤). 키를 v2 로 올려 기존 저장값 대신 이 기본이 한 번 먹는다.
const DEFAULT_PERSONS = ['1girl_solo'];
const DEFAULT_RATINGS = ['s'];
const PREF_KEY = 'naia_event_map_prefs_v2';

function loadPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREF_KEY) || 'null');
    if (!raw || typeof raw !== 'object') return null;
    const persons = Array.isArray(raw.persons) ? raw.persons.filter(id => PERSON_IDS.includes(id)) : [];
    const ratings = Array.isArray(raw.ratings) ? raw.ratings.filter(id => RATING_OPTIONS.some(r => r.id === id)) : [];
    const sort = SORT_MODES.some(m => m.id === raw.sort) ? raw.sort : null;
    return { persons: persons.length ? persons : null, ratings: ratings.length ? ratings : null, sort };
  } catch { return null; }
}
function savePrefs(persons, ratings, sort) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify({ persons: [...persons], ratings: [...ratings], sort })); } catch { /* 저장 못 해도 동작한다 */ }
}
// 후보 정렬(사용자 지정 2026-09-12 밤). 서버가 세운다 - 상위 40 만 내려오므로 화면에서 다시 세우면 안 된다.
const SORT_MODES = [
  { id: 'lift', label: 'lift 순', title: '핀이 있을 때 평소보다 몇 배 자주 나오나(관측/(기댓값+3)). 핀이 흔하면 희귀 태그가 위로 온다' },
  { id: 'posts', label: 'post 순', title: '핀과 함께 달린 게시물 수. 흔한 태그가 위로 온다' },
  { id: 'mix', label: 'mix 순', title: '관측 × ln(lift) - 많이 나오면서 치우친 것(G² 기여분). 둘의 절충' },
];

export function initEventMap({ insertTag, showToast, getPromptText, generateNow, onRandomLinkChange } = {}) {
  let randomLink = { enabled: false, revision: -1 }, linkPending = 0;
  let linkUncertain = false;
  let linkQueue = Promise.resolve(), linkKey = '';
  function paintRandomLink() {
    const checkbox = footEl?.querySelector('[data-em-random-link]');
    if (checkbox) { checkbox.checked = randomLink.enabled; checkbox.disabled = linkPending > 0; }
    onRandomLinkChange?.(randomLink.enabled, linkPending > 0 || linkUncertain);
  }
  function receiveRandomLink(state) {
    if (!state || state.revision < randomLink.revision) return;
    randomLink = state;
    linkUncertain = false;
    if (state.enabled && !linkPending) {
      pins = (state.pins || '').split(',').filter(Boolean);
      excludes = (state.exclude || '').split(',').filter(Boolean);
      ratings = new Set((state.ratings || RATING_OPTIONS.map(r => r.id).join(',')).split(','));
      persons = new Set((state.persons || PERSON_IDS.join(',')).split(','));
      const fp = filterParams();
      linkKey = JSON.stringify({ enabled: true, pins: pins.join(','), exclude: excludes.join(','), ratings: fp.ratings, persons: fp.persons });
      if (open) void explore();
    }
    paintRandomLink();
  }
  function syncRandomLink(enabled = randomLink.enabled) {
    const fp = filterParams();
    const payload = { enabled, pins: pins.join(','), exclude: excludes.join(','), ratings: fp.ratings, persons: fp.persons };
    const key = JSON.stringify(payload);
    if (key === linkKey) return linkQueue;
    linkKey = key;
    linkPending++;
    paintRandomLink();
    linkQueue = linkQueue.then(async () => {
      try { receiveRandomLink(await postJson('/api/event-map/random-link', payload, AbortSignal.timeout(20000))); }
      catch (error) {
        linkKey = '';
        toast(`랜덤 버튼 연결 실패 — ${error.message}`, 'error');
        // Never leave the backend generating from a previous selection silently.
        try { receiveRandomLink(await postJson('/api/event-map/random-link', { enabled: false }, AbortSignal.timeout(20000))); }
        catch { linkUncertain = true; toast('서버 연결을 확인해주세요. 랜덤 버튼 연결 상태를 확인할 수 없습니다.', 'error'); }
      } finally { linkPending--; paintRandomLink(); }
    });
    return linkQueue;
  }
  let overlay = null, input = null, statusEl = null, trailEl = null, bodyEl = null;
  let filtersEl = null, personBtn = null, personPopup = null, footEl = null, tabBtn = null;
  let subEl = null, subcategory = '';
  let sideEl = null;              // 실제 조합 둘째 패널
  let library = null;
  let open = false, seq = 0, suggestSeq = 0, timer = null;
  let mapState = null;            // /state 응답. 열 때마다 새로 받는다(색인이 바뀔 수 있다).
  let personLabels = new Map();   // id -> 화면 문구 (서버가 준다)
  let pins = [], excludes = [];
  const prefs = loadPrefs();
  let ratings = new Set(prefs?.ratings || DEFAULT_RATINGS);
  let persons = new Set(prefs?.persons || DEFAULT_PERSONS);
  let sortMode = prefs?.sort || 'mix';   // 기본 = mix(사용자 지정 2026-09-12 밤 - 밸런스)
  let roles = new Set();          // 대분류 필터(갈래 id). 비면 전부
  let group = '';                 // 첫 화면에서 고른 대분류(핀이 없을 때만 뜻이 있다)
  let moreRequest = null, moreError = '';
  let browse = null;              // 마지막 browse 결과
  let result = null;              // 마지막 explore
  let suggest = null;             // 마지막 suggest (검색 칸에 글자가 있을 때만)
  let samples = null;             // 실제 조합
  // 프롬프트 엔지니어링 설정(Auto-Hide · Remove ...)이 지우는 태그 -> 라운드 이름. **실제 조합에서만**
  // 진한 회색으로 칠하고 넣기·복사에서 뺀다(후보 목록에도 칠했다가 되돌렸다 - 사용자 지정 2026-09-12 밤).
  // 조합을 뽑을 때마다 다시 묻는다 - 패널을 열어 둔 채 설정을 바꿀 수 있다.
  let peHidden = new Map();
  // 행 툴팁(Interactive 칩 툴팁 꼴 + 썸네일 + 포함/제외 수). 설명은 태그별 캐시, 썸네일 표는 세션에 한 번.
  let tipEl = null, tipOwner = null;
  let dlTimer = null, dlFailed = false, dlError = '';   // 색인 자동 내려받기(사용자 결정 2026-09-13)
  let busyEl = null, busyCount = 0;   // 질의 중 덮개(반투명 검정). 겹치는 요청은 세어서 마지막이 걷는다.
  const QUERY_TIMEOUT_MS = 20000;
  const tipInfo = new Map();        // tag -> {desc, group, count} | null(없음)
  const tipAsked = new Set();
  let thumbAxis = null;             // tag -> axis (Interactive 팩). null = 아직 안 받음
  let thumbAsked = false;
  let rows = [];                  // 키보드 이동 단위(지금 보이는 목록)
  let active = -1;
  let heightCaps = { base: 0, hard: 0 };

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const fmt = n => Number(n || 0).toLocaleString('en-US');
  const toast = (message, kind) => { if (typeof showToast === 'function') showToast(message, kind || 'info'); };

  // ── 프롬프트 -> 태그 목록 ────────────────────────────────────────────────
  /** 프롬프트 칸의 글을 태그로 쪼갠다. 가중치(`0.8::x ::`·`-0.25::y`)는 벗기고, `#주석` 줄과
   *  빈 조각은 버린다. 무엇이 맵에 있는지는 서버(`/resolve`)가 정한다. */
  // ── 서버 ─────────────────────────────────────────────────────────────────
  async function getJson(path, params) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params || {})) {
      if (value !== '' && value != null) query.set(key, String(value));
    }
    // 흔한 태그(rating S 의 breasts 등)는 몇 초가 걸린다 - 그래도 영영 기다리진 않는다(20초).
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), QUERY_TIMEOUT_MS);
    let res;
    try {
      res = await fetch(`${path}?${query.toString()}`, { cache: 'no-store', signal: ctl.signal });
    } catch (error) {
      if (error && error.name === 'AbortError') throw Object.assign(new Error(`시간 초과 (${QUERY_TIMEOUT_MS / 1000}초)`), { code: 'timeout' });
      throw error;
    } finally { clearTimeout(timer); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(body.message || res.statusText), { code: body.code, body });
    return body;
  }
  /** 질의 중 덮개. 머리줄(검색 칸)은 남기고 그 아래를 덮는다 - 타이핑은 되고 클릭만 막힌다. */
  function setBusy(on) {
    busyCount = Math.max(0, busyCount + (on ? 1 : -1));
    if (subEl) subEl.inert = busyCount > 0;
    if (!busyEl) return;
    const bar = overlay?.querySelector('.em-bar');
    if (bar) busyEl.style.top = `${bar.offsetHeight}px`;
    busyEl.classList.toggle('open', busyCount > 0);
  }

  function filterParams() {
    return {
      ratings: ratings.size === RATING_OPTIONS.length ? '' : RATING_OPTIONS.map(r => r.id).filter(id => ratings.has(id)).join(','),
      persons: persons.size === PERSON_IDS.length ? '' : PERSON_IDS.filter(id => persons.has(id)).join(','),
      groups: roles.size ? [...roles].join(',') : '',
      subcategory: selectedCategory() ? subcategory : '',
    };
  }

  async function loadState() {
    try {
      mapState = await getJson('/api/event-map/state', {});
    } catch (error) {
      mapState = { state: 'missing', message: String(error && error.message || error) };
    }
    personLabels = new Map((mapState.persons || []).map(p => [p.id, p.label]));
    return mapState;
  }

  /** 이 태그들 중 지금 PE 설정이 지우는 것을 서버에 묻는다. 실패하면 조용히 '아무것도 안 지움'. */
  async function loadPeHidden(tags) {
    const list = [...new Set((tags || []).filter(Boolean))].slice(0, 400);
    if (!list.length) { peHidden = new Map(); return; }
    try {
      const body = await getJson('/api/event-map/pe-filter', { tags: list.join(',') });
      peHidden = new Map(Object.entries(body.hidden || {}));
    } catch { peHidden = new Map(); }
  }
  const peTitle = tag => peHidden.has(tag) ? ` · 프롬프트 엔지니어링 설정(${peHidden.get(tag)})이 지웁니다` : '';

  async function loadBrowse() {
    if (randomLink.enabled) void syncRandomLink();
    moreRequest = null; moreError = '';
    active = -1;
    browse = null;
    if (bodyEl) bodyEl.scrollTop = 0;
    const mine = ++seq;
    setStatus('찾는 중…', 'busy');
    setBusy(true);
    try {
      const body = await getJson('/api/event-map/browse', { group, limit: CANDIDATE_LIMIT, ...filterParams(), groups: '' });
      if (mine !== seq) return;
      browse = body;
    } catch (error) {
      if (mine !== seq) return;
      browse = { status: 'error', message: error.message, candidates: [] };
    } finally { setBusy(false); }
    render();
  }

  async function explore() {
    if (randomLink.enabled) void syncRandomLink();
    moreRequest = null; moreError = '';
    active = -1;
    ++seq; // 핀이 전부 사라져도 이전 응답을 무효화한다.
    result = null;
    if (bodyEl) bodyEl.scrollTop = 0;
    samples = null;
    if (!pins.length) {
      result = null;
      if (group) { void loadBrowse(); return; }
      render(); return;
    }
    const mine = ++seq;
    setStatus('찾는 중…', 'busy');
    setBusy(true);
    try {
      const body = await getJson('/api/event-map/explore', {
        pins: pins.join(','), exclude: excludes.join(','), limit: CANDIDATE_LIMIT, sort: sortMode, ...filterParams(),
      });
      if (mine !== seq) return;
      result = body;
    } catch (error) {
      if (mine !== seq) return;
      result = { status: 'error', message: error.message, code: error.code, candidates: [] };
    } finally { setBusy(false); }
    render();
  }

  function currentCandidates() {
    if (!open || mapState?.state !== 'ready' || input?.value.trim()) return null;
    return pins.length ? result : (group ? browse : null);
  }

  function moreHtml() {
    const source = currentCandidates();
    if (!source?.has_more) return '';
    return `<div class="em-cap" data-em-more role="status">${moreRequest ? '40개 더 불러오는 중…' : moreError
      ? '<button type="button" class="em-mini" data-em-more-retry>불러오기 실패 · 다시 시도</button>'
      : '아래로 스크롤하면 40개 더 표시합니다'}</div>`;
  }

  async function loadMore() {
    const source = currentCandidates();
    if (!source?.has_more || moreRequest || busyCount) return;
    const mine = seq;
    const ticket = {};
    moreRequest = ticket; moreError = '';
    const footer = bodyEl.querySelector('[data-em-more]');
    if (footer) footer.outerHTML = moreHtml();
    const exploring = pins.length > 0;
    const params = { limit: CANDIDATE_LIMIT, offset: source.next_offset, ...filterParams() };
    if (exploring) Object.assign(params, { pins: pins.join(','), exclude: excludes.join(','), sort: sortMode });
    else Object.assign(params, { group, groups: '' });
    try {
      const page = await getJson(`/api/event-map/${exploring ? 'explore' : 'browse'}`, params);
      if (mine !== seq || moreRequest !== ticket || currentCandidates() !== source) return;
      // 구형 서버가 offset을 무시해 첫 페이지를 다시 보내면 중복해서 붙이지 않는다.
      if (page.offset !== params.offset) throw new Error('서버를 재시작한 뒤 다시 시도해 주세요.');
      source.candidates.push(...(page.candidates || []));
      source.has_more = page.has_more;
      source.next_offset = page.next_offset;
    } catch (error) {
      if (mine !== seq || moreRequest !== ticket || currentCandidates() !== source) return;
      moreError = error.message;
      toast(`추가 목록을 불러오지 못했습니다 — ${error.message}`, 'error');
    } finally {
      if (moreRequest === ticket) {
        moreRequest = null;
        if (mine === seq && currentCandidates() === source) render(true);
      }
    }
  }

  function scheduleSuggest() {
    moreRequest = null; moreError = '';
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { suggest = null; render(); return; }
    timer = setTimeout(async () => {
      const mine = ++suggestSeq;
      try {
        const body = await getJson('/api/event-map/suggest', { q, limit: SUGGEST_LIMIT });
        if (mine !== suggestSeq) return;
        suggest = body;
      } catch (error) {
        if (mine !== suggestSeq) return;
        suggest = { items: [], error: error.message };
      }
      render();
    }, DEBOUNCE_MS);
  }

  async function drawSamples() {
    library?.close();
    if (!pins.length) return;
    const mine = ++seq;
    setStatus('실제 조합을 뽑는 중…', 'busy');
    setBusy(true);
    try {
      const body = await getJson('/api/event-map/sample', {
        pins: pins.join(','), exclude: excludes.join(','), n: SAMPLE_COUNT,
        seed: Date.now() % 1000003, ...filterParams(),
      });
      if (mine !== seq) return;
      await loadPeHidden((body.samples || []).flatMap(s => s.tags || []));
      if (mine !== seq) return;
      samples = body;
    } catch (error) {
      if (mine !== seq) return;
      samples = { status: 'error', message: error.message, samples: [] };
    } finally { setBusy(false); }
    render();
  }

  // ── 상태 조작 ────────────────────────────────────────────────────────────
  function pin(tag) {
    if (!pins.length) subcategory = '';
    const clean = String(tag || '').trim();
    if (!clean || pins.includes(clean)) return;
    const max = Number(mapState?.limits?.max_pins || 16);
    if (pins.length >= max) { toast(`핀은 ${max}개까지입니다.`, 'warning'); return; }
    pins.push(clean);
    excludes = excludes.filter(t => t !== clean);
    input.value = ''; suggest = null;
    void explore();
  }
  function exclude(tag) {
    const clean = String(tag || '').trim();
    if (!clean || excludes.includes(clean)) return;
    excludes.push(clean);
    pins = pins.filter(t => t !== clean);
    void explore();
  }
  function goTo(depth) {
    subcategory = '';          // depth = 남길 핀 개수
    pins = pins.slice(0, Math.max(0, depth));
    void explore();
  }
  function goBack() {
    subcategory = '';
    if (pins.length) { goTo(pins.length - 1); return; }
    if (group) { group = ''; browse = null; render(); }
  }
  function pickGroup(id) { subcategory = ''; group = id; browse = null; void loadBrowse(); }
  function clearExclude(tag) { excludes = excludes.filter(t => t !== tag); void explore(); }

  function currentPrompt() { return pins.join(', '); }
  /** [넣기] = 랜덤 대치(사용자 지정 2026-09-13): 고른 핀을 Random 과 같은 파이프라인에 태워 메인 프롬프트를
   *  **갈아끼운다**(/api/event-map/apply). 전에는 커서 자리에 끼워 넣었다. 등급은 지금 고른 등급이 하나면 그것, 아니면 s. */
  async function applyPins(btn) {
    if (!pins.length) return;
    const rating = ratings.size === 1 ? [...ratings][0] : 's';
    if (btn) btn.disabled = true;
    try {
      await postJson('/api/event-map/apply', { tags: pins.slice(), rating });
      toast(`메인 프롬프트를 대치했습니다 — ${pins.join(', ').slice(0, 40)}`, 'success');
    } catch (error) {
      toast(`대치 실패 — ${error.message}`, 'error');
    } finally { if (btn) btn.disabled = !pins.length; }
  }
  // ── 행 툴팁 ──────────────────────────────────────────────────────────────
  function ensureTip() {
    if (tipEl && document.body.contains(tipEl)) return tipEl;
    tipEl = document.createElement('div');
    tipEl.className = 'em-tip';
    document.body.appendChild(tipEl);    // body 직계 - 패널 안에 두면 overflow 에 잘린다
    return tipEl;
  }
  async function askTipInfo(tag) {
    if (tipInfo.has(tag) || tipAsked.has(tag)) return;
    tipAsked.add(tag);
    try {
      const r = await fetch(`/api/tag/lookup?tag=${encodeURIComponent(tag)}`);
      const d = r.ok ? await r.json() : null;
      tipInfo.set(tag, d && d.tag ? { desc: d.desc || '', group: d.group || '', count: d.count || 0 } : null);
    } catch { tipInfo.set(tag, null); }
    if (tipOwner && tipOwner.dataset.emPin === tag) paintTip(tipOwner);
  }
  async function ensureThumbIndex() {
    if (thumbAxis || thumbAsked) return;
    thumbAsked = true;
    try {
      const r = await fetch('/api/interactive-thumb/index');
      const axes = r.ok ? (await r.json()).axes || {} : {};
      thumbAxis = new Map();
      for (const [axis, tags] of Object.entries(axes)) for (const t of tags) if (!thumbAxis.has(t)) thumbAxis.set(t, axis);
    } catch { thumbAxis = new Map(); }
    if (tipOwner) paintTip(tipOwner);
  }
  function tipComboLine(row) {
    // 포함 = 이 태그도 달린 게시물(후보의 observed) · 제외 = 지금 조건의 게시물 - 포함. 왕복 없이 계산.
    const src = pins.length ? result : browse;
    const total = Number(src?.observed_posts || 0);
    const inc = Number(row.dataset.emEst || 0);
    if (!total || !inc) return '';
    const approx = src?.sampled ? '≈' : '';
    return `<div class="em-tip-combo"><span>포함 <b>${approx}${fmt(inc)}</b></span><span>제외 <b>${approx}${fmt(Math.max(0, total - inc))}</b></span></div>
      <div class="em-tip-combo-note">${pins.length ? '핀 조합' : '이 분면'}의 게시물 ${fmt(total)}건 중</div>`;
  }
  function paintTip(row) {
    const tip = ensureTip();
    const tag = row.dataset.emPin || '';
    const info = tipInfo.get(tag);
    const axis = thumbAxis?.get(tag);
    const thumb = axis ? `<img class="em-tip-thumb" alt="" src="/api/interactive-thumb?axis=${encodeURIComponent(axis)}&tag=${encodeURIComponent(tag)}">` : '';
    tip.innerHTML = `<div class="em-tip-row">
      <div class="em-tip-main">
        <div class="em-tip-head"><span class="em-tip-tag">${esc(tag)}</span><span class="em-tip-src">${esc(roleLabel(row.dataset.emG || 'unsorted'))}</span></div>
        ${info?.desc ? `<div class="em-tip-desc">${esc(info.desc)}</div>` : (info === undefined ? '<div class="em-tip-desc em-tip-wait">…</div>' : '')}
        <div class="em-tip-stats">lift ${esc(row.dataset.emLift || '')}${info?.count ? ` · Danbooru ${fmt(info.count)}` : ''}</div>
        <div class="em-tip-foot">${tipComboLine(row)}<div class="em-tip-hint">클릭 꽂기 · 우클릭 제외</div></div>
      </div>${thumb}</div>`;
    tip.classList.add('open');
    // **항상 같은 자리**: 행 가운데의 살짝 오른쪽, 행 바로 아래(사용자 지정 2026-09-12 밤 - 창 크기에
    // 따라 좌우로 튀던 것). 아래가 모자라면 위로만 올린다. 좌우는 화면 밖으로 나가지 않게만 민다.
    const a = row.getBoundingClientRect(), b = tip.getBoundingClientRect();
    const gap = 6, margin = 8;
    let left = a.left + a.width * 0.5 + 16;
    left = Math.max(margin, Math.min(left, window.innerWidth - b.width - margin));
    let top = a.bottom + gap;
    if (top + b.height > window.innerHeight - margin) top = a.top - b.height - gap;
    top = Math.max(margin, top);
    tip.style.left = `${Math.round(left)}px`; tip.style.top = `${Math.round(top)}px`;
  }
  function showTip(row) {
    if (!row || row === tipOwner) return;
    tipOwner = row;
    void askTipInfo(row.dataset.emPin || '');
    void ensureThumbIndex();
    paintTip(row);
  }
  function hideTip() {
    tipOwner = null;
    if (tipEl) tipEl.classList.remove('open');
  }

  /** [랜덤 프롬프트 할당] - 고른 분면(핀·제외가 있으면 그 안)에서 게시물 하나 → [적용] 과 같은 길. */
  async function randomAssign(btn, andGenerate = false) {
    const group = btn?.closest('.em-actions');
    group?.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      const fp = filterParams();
      const body = await getJson('/api/event-map/sample', {
        pins: pins.join(','), exclude: excludes.join(','), n: 1, seed: Date.now() % 1000003,
        ratings: fp.ratings, persons: fp.persons,
      });
      const s = (body.samples || [])[0];
      if (!s || !s.tags?.length) { toast(body.status === 'no_match' ? '이 조건에 맞는 게시물이 없습니다' : '뽑지 못했습니다', 'error'); return; }
      const where = String(s.partition || '').replace(/_/g, ' ');
      if (andGenerate) {
        await applyThenGenerate(s.tags, String(s.partition || 's').slice(0, 1));
        toast(`랜덤 프롬프트를 적용하고 생성을 눌렀습니다 (${where})`, 'success');
      } else {
        await postJson('/api/event-map/apply', { tags: s.tags, rating: String(s.partition || 's').slice(0, 1) });
        toast(`랜덤 프롬프트를 할당했습니다 (${where})`, 'success');
      }
    } catch (error) {
      toast(`랜덤 프롬프트 실패 — ${error.message}`, 'error');
    } finally {
      group?.querySelectorAll('button').forEach(b => { b.disabled = false; });
    }
  }
  /** 적용 → prompt_generated 가 WS 로 와서 칸을 채운 뒤(최대 2초) → Generate 버튼과 같은 길. 실패는 throw. */
  async function applyThenGenerate(tags, rating) {
    const applied = await postJson('/api/event-map/apply', { tags, rating });
    const want = String(applied.prompt || '').trim();
    const read = () => (typeof getPromptText === 'function' ? String(getPromptText() || '') : '').trim();
    for (let n = 0; n < 20 && want && read() !== want; n++) await new Promise(r => setTimeout(r, 100));
    if (typeof generateNow !== 'function') throw new Error('생성 단추가 연결되지 않았습니다');
    generateNow();
  }
  /** 실제 조합 i 를 파이프라인에 태운다. 회색(PE 가 지울 것)도 **그대로 보낸다** - 파이프라인이
   *  스스로 지우는 것이 '랜덤 프롬프트와 같은 방식' 이다. */
  async function postJson(path, body, signal) {
    const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) { const e = new Error(data.message || `HTTP ${res.status}`); e.code = data.code; throw e; }
    return data;
  }
  // ── 색인 자동 내려받기 ───────────────────────────────────────────────────
  //
  // 색인(879MB)은 배포본에 없다. 사용자에게 단추를 보여 주고 누르게 하지 않는다 -
  // 패널을 열면 그 자리에서 받기 시작하고, 받는 동안 화면이 진행 막대가 된다.
  // ⚠️ 시작은 **루프백에서만** 된다(폰으로 연 화면은 879MB 를 시킬 수 없다) - 그때는
  //    can_start:false 로 오므로 안내만 한다. 다른 다운로드가 도는 중이면 줄을 선다.
  async function autoDownload() {
    const info = mapState?.install;
    if (!info || info.ready || !info.downloadable) return;
    if (info.active || info.busy_other || !info.can_start || dlFailed) return;
    // 실패했거나(회선 끊김) 사용자가 취소한 뒤다. 여기서 안 멈추면 폴링이 2초마다 처음부터
    // 다시 받는다 - 879MB 를 무한히 되풀이한다. 패널을 닫았다 다시 열면 그때 다시 시도한다.
    const last = info.download || {};
    if (last.error && String(last.phase || '') === 'event_map') {
      dlFailed = true;
      dlError = String(last.error);
      return;
    }
    try {
      await postJson('/api/install-manager/event-map/download', {});
    } catch (error) {
      // 여기서 멈춰 세우지 않으면 폴링이 2초마다 같은 실패를 되풀이한다.
      dlFailed = true;
      dlError = String(error && error.message || error);
    }
    await loadState();
  }
  function stopDlPoll() { if (dlTimer) { clearInterval(dlTimer); dlTimer = null; } }
  /** 받는 동안만 돈다. 다 받으면 스스로 멈추고 패널을 되살린다(닫았다 열 필요 없다). */
  function startDlPoll() {
    if (dlTimer) return;
    dlTimer = setInterval(async () => {
      if (!open) { stopDlPoll(); return; }
      await loadState();
      if (mapState?.state === 'ready') {
        stopDlPoll();
        render();
        focusInput();
        return;
      }
      await autoDownload();
      render();
    }, 1500);
  }
  /** 색인이 준비되기 전에는 검색 칸·조건 줄·발줄을 못 만지게 한다. */
  function setLocked(on) {
    if (!overlay) return;
    overlay.classList.toggle('em-locked', !!on);
    if (input) input.disabled = !!on;
  }
  function downloadHtml() {
    const info = mapState?.install;
    const dl = info?.download || {};
    const pct = Math.max(0, Math.min(100, Number(dl.percent || 0)));
    const size = info?.approx_mb ? `${fmt(info.approx_mb)}MB` : '';
    let note;
    if (dlFailed) note = `내려받기에 실패했습니다 — ${esc(dlError)}`;
    else if (info?.active) note = `${pct}% ${dl.total_mb ? `(${dl.downloaded_mb} / ${dl.total_mb} MB)` : ''}`;
    else if (info?.busy_other) note = '다른 데이터를 받는 중입니다 — 끝나면 이어서 받습니다.';
    else if (info && !info.can_start) note = '이 기기에서는 시작할 수 없습니다. NAIA 를 켠 PC 에서 열면 자동으로 받습니다.';
    else if (info) note = '내려받기를 시작하는 중…';
    else note = esc(mapState?.message || '색인을 찾지 못했습니다.');
    const bar = info?.active
      ? `<div class="em-dl-bar"><i style="width:${pct}%"></i></div>` : '';
    return `<div class="em-missing"><b>이벤트 맵 색인을 준비하는 중입니다.</b>
      <div class="em-note">${size ? `약 ${size} · ` : ''}한 번만 받습니다. 이 창을 닫아도 계속 받습니다.</div>
      ${bar}<div class="em-dl-note">${note}</div></div>`;
  }
  async function runSample(i, mode, btn) {
    const s = (samples?.samples || [])[i];
    if (!s || !s.tags?.length) return;
    const body = { tags: s.tags, rating: String(s.partition || 's').slice(0, 1) };
    const box = btn?.closest('.em-sample-run');
    box?.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      if (mode === 'generate') {
        await postJson('/api/event-map/generate', body);
        toast('이 조합으로 생성을 요청했습니다 (메인 프롬프트는 그대로)', 'success');
        return;
      }
      if (mode === 'apply') {
        await postJson('/api/event-map/apply', body);
        toast('메인 프롬프트에 적용했습니다', 'success'); return;
      }
      await applyThenGenerate(body.tags, body.rating);
      toast('적용 후 생성을 눌렀습니다', 'success');
    } catch (error) {
      toast(`${mode === 'generate' ? '생성' : '적용'} 실패 — ${error.message}`, 'error');
    } finally {
      box?.querySelectorAll('button').forEach(b => { b.disabled = false; });
    }
  }
  /** 화면용 순서: 남는 태그 먼저, 회색(PE 가 지울) 태그는 뒤로(사용자 지정). 보내는 순서는 원본 그대로다. */
  function sampleTagsForDisplay(s) {
    const tags = s.tags || String(s.prompt || '').split(', ');
    return [...tags.filter(t => !peHidden.has(t)), ...tags.filter(t => peHidden.has(t))];
  }
  /** 실제 조합 i 를 넣거나 복사할 문자열 - PE 설정이 지우는 태그는 뺀다(화면의 회색과 같은 것). */
  function samplePrompt(i) {
    const s = (samples?.samples || [])[i];
    if (!s) return '';
    const tags = s.tags || String(s.prompt || '').split(', ');
    return tags.filter(t => t && !peHidden.has(t)).join(', ');
  }
  function insertText(text) {
    const clean = String(text || '').trim();
    if (!clean) return;
    const ok = typeof insertTag === 'function' && insertTag(clean);
    toast(ok === false ? '프롬프트에 넣지 못했습니다.' : `프롬프트에 넣었습니다 — ${clean.slice(0, 40)}`,
      ok === false ? 'error' : 'success');
  }
  async function copyText(text) {
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch { ok = false; }
    if (!ok) {
      try {
        const scratch = document.createElement('textarea');
        scratch.value = text; scratch.setAttribute('readonly', '');
        scratch.style.cssText = 'position:fixed;top:-1000px;opacity:0';
        document.body.append(scratch); scratch.select();
        ok = document.execCommand('copy'); scratch.remove();
      } catch { ok = false; }
    }
    toast(ok ? `복사했습니다 — ${text.slice(0, 40)}` : '복사가 막혔습니다. 직접 선택해 Ctrl+C 하세요.',
      ok ? 'success' : 'error');
  }

  // ── 그리기 ───────────────────────────────────────────────────────────────
  function setStatus(text, kind, title) {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.title = title || '';
    statusEl.className = `em-status${kind ? ` is-${kind}` : ''}`;
  }

  function paintTrail() {
    const crumbs = pins.map((tag, i) =>
      `<span class="em-crumb${i === pins.length - 1 ? ' is-last' : ''}">`
      + `<button type="button" class="em-crumb-go" data-em-goto="${i + 1}" title="이 단계로 돌아가기">${esc(tag)}</button>`
      + `<button type="button" class="em-crumb-x" data-em-unpin="${esc(tag)}" aria-label="${esc(tag)} 빼기">×</button></span>`)
      .join('<span class="em-sep">›</span>');
    const ex = excludes.map(tag =>
      `<button type="button" class="em-ex" data-em-unexclude="${esc(tag)}" title="제외 풀기">− ${esc(tag)}</button>`).join('');
    const g = group ? groupInfo(group) : null;
    const groupCrumb = g ? `<span class="em-crumb em-crumb-group em-g-${esc(group)}"><button type="button" class="em-crumb-go" data-em-group-back
        title="이 대분류의 목록으로">${esc(g.label)}</button></span>${crumbs ? '<span class="em-sep">›</span>' : ''}` : '';
    trailEl.innerHTML = `
      <button type="button" class="em-back" data-em-back ${(pins.length || group) ? '' : 'disabled'} title="한 단계 위로 (Backspace)">←</button>
      <div class="em-crumbs">${groupCrumb}${crumbs || (group ? '' : '<span class="em-crumb-empty">대분류를 고르거나 태그를 찾아 시작합니다</span>')}${ex}</div>`;
    paintActions();
  }
  function groupInfo(id) { return (mapState?.groups || []).find(g => g.id === id) || null; }

  /** 동작 단추는 발줄 오른쪽에 산다 - 부스러기 줄에 두면 핀이 셋만 돼도 겹쳤다. */
  function paintActions() {
    if (!footEl) return;
    const on = pins.length > 0;
    // 넣기/복사/실제 조합 셋 다 조건 줄 오른쪽에 산다(사용자 지정 2026-09-12 밤 - 발줄에선 못 찾았다)
    overlay.querySelectorAll('[data-em-insert], [data-em-copy]').forEach(b => { b.disabled = !on; });
    const sb = overlay.querySelector('[data-em-samples]');
    if (sb) { sb.disabled = !on; sb.classList.toggle('is-on', !!samples); }
  }

  function paintFilters() {
    filtersEl.innerHTML = `
      <button type="button" class="em-person-btn" data-em-person aria-haspopup="dialog" aria-expanded="false"
              title="인원 구성 고르기"><b data-em-person-count></b></button>
      <span class="em-rating-bar" role="group" aria-label="등급">${RATING_OPTIONS.map(r =>
        `<button type="button" class="em-rating-btn${ratings.has(r.id) ? ' active' : ''}" data-em-r="${r.id}"
                 aria-pressed="${ratings.has(r.id)}" title="${r.title}">${r.label}</button>`).join('')}</span>
      <span class="em-actions em-actions-right"><button type="button" data-em-insert disabled
              title="지금 고른 태그로 메인 프롬프트를 대치한다 (Random 과 같은 길)">넣기</button><button type="button" data-em-copy disabled
              title="지금 고른 태그 전부를 클립보드로">복사</button><button type="button" data-em-samples disabled
              title="핀을 전부 포함하는 실제 게시물의 조합">실제 조합</button></span>`;
    personBtn = filtersEl.querySelector('[data-em-person]');
    paintPersonButton();
    paintActions();
  }

  /** 카테고리 탭 줄. 서버가 준 갈래별 후보 수로 그린다(접힌 팝업 대신 - 사용자 지정 2026-09-12).
   *  핀이 있으면 탭 = 후보 필터, 대분류 목록이면 탭 = 대분류 바꾸기. */
  function catsHtml(counts, activeId, total) {
    // 갈래는 **항상 전부** 그린다(핀을 고른 뒤에도 - 사용자 지정 2026-09-12). counts 는 있으면 얹는다;
    // 없으면(옛 백엔드) 수 없이 그리고, 0 인 갈래는 흐리게 두고 못 누른다.
    const groups = (mapState?.groups || []).filter(g => g.id !== 'unsorted' && g.tags > 0);
    if (!groups.length) return '';
    const byId = counts ? new Map(counts.map(r => [r.id, r.count])) : null;
    const tab = (id, label, n, on) => {
      const empty = byId != null && id && !n;
      return `<button type="button" class="em-cat em-g-${esc(id)}${on ? ' is-on' : ''}${empty ? ' is-empty' : ''}" data-em-cat="${esc(id)}"
        ${empty ? 'disabled' : ''} title="${esc(label)}${n != null ? ' · ' + fmt(n) : ''}"><span class="em-tag">${esc(label)}</span>${n != null ? `<span class="em-cat-n">${fmt(n)}</span>` : ''}</button>`;
    };
    return `<div class="em-cats" role="tablist">${total != null ? tab('', '전체', total, !activeId) : ''}${groups.map(g => tab(g.id, g.label, byId ? (byId.get(g.id) || 0) : null, g.id === activeId)).join('')}</div>`;
  }

  /** 접기 표의 대분류 12개(서버가 준다). 첫 화면 축(depth1)과 나머지로 묶는다. */
  function roleOptions() {
    const all = (mapState?.groups || []).filter(g => g.tags > 0);
    return [{ g: '축', items: all.filter(g => g.depth1) }, { g: '함께 오는 것', items: all.filter(g => !g.depth1) }]
      .filter(x => x.items.length);
  }

  function paintPersonButton() {
    if (!personBtn) return;
    const count = personBtn.querySelector('[data-em-person-count]');
    const all = persons.size === PERSON_IDS.length;
    if (persons.size === 1) count.textContent = personLabels.get([...persons][0]) || [...persons][0];
    else count.textContent = all ? '전체' : `${persons.size}/${PERSON_IDS.length}`;
    personBtn.classList.toggle('is-filtered', !all);
  }

  function candidateRow(c, i) {
    const lift = Number(c.lift || 0);
    const liftText = lift >= 100 ? `×${Math.round(lift)}` : `×${lift.toFixed(lift >= 10 ? 0 : 1)}`;
    const obs = c.observed_estimate != null && c.observed_estimate !== c.observed
      ? `≈${fmt(c.observed_estimate)}` : fmt(c.observed);
    const est = c.observed_estimate != null ? c.observed_estimate : c.observed;
    return `<div class="em-row em-g-${esc(c.group || 'unsorted')}${i === active ? ' is-active' : ''}" data-em-row="${i}" data-em-pin="${esc(c.tag)}"
        data-em-g="${esc(c.group || 'unsorted')}" data-em-est="${Number(est) || 0}" data-em-lift="${liftText}" role="option">
      <span class="em-tag">${esc(c.tag)}</span>
      <span class="em-lift">${liftText}</span>
      <span class="em-obs">${obs}</span>
      <button type="button" class="em-row-x" data-em-exclude="${esc(c.tag)}" title="이 태그가 없는 게시물만">−</button>
    </div>`;
  }
  function roleLabel(id) {
    const found = (mapState?.groups || []).find(g => g.id === id);
    return found ? found.label : id;
  }

  function suggestHtml() {
    if (!suggest) return '';
    const items = suggest.items || [];
    if (!items.length) return `<div class="em-empty">${esc(suggest.error || '맞는 태그가 없습니다')}</div>`;
    let k = 0;
    return `<div class="em-cap">검색${suggest.translated?.length ? `<span class="em-note">한글 → ${esc(suggest.translated.slice(0, 3).join(', '))}</span>` : ''}</div>
      ${items.map(it => {
        const usable = !it.blocked && !pins.includes(it.tag);
        const i = usable ? k++ : -1;
        return `<div class="em-row em-g-${esc(it.group || 'unsorted')}${usable ? '' : ' is-off'}${i === active ? ' is-active' : ''}" ${usable ? `data-em-row="${i}" data-em-pin="${esc(it.tag)}"` : ''} role="option">
          <span class="em-tag" title="${esc(roleLabel(it.group || 'unsorted'))}">${esc(it.tag)}</span>
          <span class="em-obs">${fmt(it.observed)}</span>${it.blocked ? `<span class="em-blocked">${esc(it.blocked)}</span>` : ''}
        </div>`;
      }).join('')}`;
  }

  /** 첫 화면의 대분류 단추. 축(depth1) 넷이 크게, 나머지는 작게. 태그 수 0 이면 흐리게. */
  function groupsHtml() {
    const all = mapState?.groups || [];
    if (!all.length) return `<div class="em-empty">대분류 표가 없습니다 (KR_tags.parquet 를 못 찾음)</div>`;
    const btn = g => `<button type="button" class="em-group em-g-${esc(g.id)}" data-em-group="${esc(g.id)}"
        ${g.tags ? '' : 'disabled'} title="태그 ${fmt(g.tags)} · 관측 ${fmt(g.observed)}">
        <span class="em-group-label">${esc(g.label)}</span><span class="em-group-n">${fmt(g.tags)}</span></button>`;
    return `<div class="em-cap">대분류 <span class="em-note">고른 인원·등급에서 특징적인 태그를 봅니다</span></div>
      <div class="em-groups">${all.filter(g => g.depth1).map(btn).join('')}</div>
      <div class="em-cap em-cap-sub">함께 오는 것</div>
      <div class="em-groups em-groups-rest">${all.filter(g => !g.depth1 && g.id !== 'unsorted').map(btn).join('')}</div>`;
  }

  /** 대분류를 고른 뒤: 그 분면에서 특징적인 태그. 행을 누르면 첫 핀이 된다. */
  function browseHtml() {
    if (!browse) return '';
    if (browse.status === 'error') { setStatus('오류', 'error'); return `<div class="em-empty">${esc(browse.message || '실패')}</div>`; }
    const cs = browse.candidates || [];
    rows = cs.map(c => c.tag);
    setStatus(`${fmt(browse.observed_posts)}건${browse.sampled ? ' · 표본' : ''}`, 'ok',
      `${Math.round(browse.elapsed_ms || 0)}ms · 이 분면에서의 비율 ÷ 코퍼스 전체에서의 비율`);
    const tabs = (mapState?.groups || []).filter(g => g.tags > 0 && g.id !== 'unsorted').map(g => ({ id: g.id, count: g.tags }));
    return catsHtml(tabs, group, null)
      + `<div class="em-cap">${esc(roleLabel(group))} <span class="em-note">이 인원·등급에서 특징적인 순 · ${cs.length}개</span></div>`
      + (cs.length ? cs.map(candidateRow).join('') : `<div class="em-empty">이 분면에서 5건 이상인 태그가 없습니다.</div>`);
  }

  /** 실제 조합은 본문 아래가 아니라 **오른쪽 둘째 패널**에 그린다(사용자 지정 2026-09-12) -
   *  아래에 붙이면 후보 목록을 지나 스크롤해야 보였다. 창을 닫거나 핀이 바뀌면 같이 사라진다. */
  function paintSide() {
    if (!sideEl) return;
    if (!samples || !open) { sideEl.hidden = true; sideEl.innerHTML = ''; return; }
    const list = samples.samples || [];
    sideEl.hidden = false;
    sideEl.innerHTML = `<div class="em-bar em-side-bar">
        <span class="em-side-title">실제 조합</span>
        <span class="em-status">${samples.status === 'error' ? esc(samples.message) : `${fmt(samples.observed_posts)}건 중 ${list.length}개`}</span>
        <button type="button" class="em-mini" data-em-samples-again title="다시 뽑기">↻</button>
        <button type="button" class="em-close" data-em-side-close aria-label="닫기">×</button>
      </div>
      <div class="em-side-note">핀을 전부 포함하는 게시물 하나에 <b>실제로 함께 달린</b> 태그입니다. 이어 붙인 것이 아닙니다.${
        peHidden.size ? ' <span class="em-pe-hidden">회색</span>은 프롬프트 엔지니어링 설정이 지우는 태그 - 넣기·복사에서 빠집니다.' : ''}</div>
      <div class="em-body em-side-body">${list.map((s, i) => `
        <div class="em-sample">
          <div class="em-sample-tags">${sampleTagsForDisplay(s).map(t =>
            peHidden.has(t) ? `<span class="em-pe-hidden" title="${esc(peTitle(t).slice(3))}">${esc(t)}</span>` : esc(t)).join(', ')}</div>
          <div class="em-sample-actions">
            <span class="em-actions em-sample-run">
              <button type="button" data-em-sample-apply="${i}" title="이 조합을 Random 과 같은 파이프라인에 태워 메인 프롬프트로">적용</button>
              <button type="button" data-em-sample-generate="${i}" title="메인 프롬프트는 두고, 이 조합으로 바로 생성(바이패스)">생성</button>
              <button type="button" data-em-sample-apply-generate="${i}" title="적용한 뒤 Generate">적용+생성</button>
            </span>
            <span class="em-note">${esc(String(s.partition || '').replace(/_/g, ' '))}</span>
            <button type="button" data-em-sample-insert="${i}">넣기</button>
            <button type="button" data-em-sample-copy="${i}">복사</button>
          </div>
        </div>`).join('') || '<div class="em-empty">조합이 없습니다</div>'}</div>`;
    positionSide();
  }
  function selectedCategory() {
    return pins.length ? (roles.size === 1 ? [...roles][0] : '') : group;
  }

  function paintSubcategories() {
    if (!subEl) return;
    const gid = selectedCategory();
    const source = currentCandidates();
    subEl.hidden = !open || !gid || !!input?.value.trim() || mapState?.state !== 'ready';
    if (subEl.hidden) return;
    const previousScroll = subEl.querySelector('.em-sublist')?.scrollTop || 0;
    const focused = subEl.contains(document.activeElement) ? document.activeElement.dataset.emSub : undefined;
    const rows = source?.subcategories || [];
    const total = source?.subcategory_total ?? source?.candidate_pool ?? 0;
    const button = (id, label, count) => `<button type="button" class="em-subitem${id === subcategory ? ' is-on' : ''}"
      data-em-sub="${esc(id)}" aria-pressed="${id === subcategory}" title="${esc(label)}">
      <span>${esc(label)}</span><span class="em-subcount">${fmt(count)}</span></button>`;
    subEl.innerHTML = `<button type="button" class="em-subheading" data-em-sub-toggle aria-expanded="${subEl.dataset.expanded === 'true'}">
        <span>${esc(roleLabel(gid))}<small>소분류</small></span><span class="em-subchevron">⌄</span></button>
      <div class="em-sublist" role="group" aria-label="${esc(roleLabel(gid))} 소분류">
        ${button('', '전체', total)}
        ${rows.map(row => button(row.id, row.label, row.count)).join('')}
        ${!source ? '<div class="em-subempty">불러오는 중…</div>' : !rows.length ? '<div class="em-subempty">이 조건에 맞는 소분류가 없습니다.</div>' : ''}
      </div>`;
    subEl.inert = busyCount > 0;
    positionSubcategories();
    subEl.querySelector('.em-sublist').scrollTop = previousScroll;
    if (focused !== undefined) {
      [...subEl.querySelectorAll('[data-em-sub]')].find(button => button.dataset.emSub === focused)?.focus({ preventScroll: true });
    }
  }

  function positionSubcategories() {
    if (library?.isOpen()) { if (subEl) subEl.hidden = true; return; }
    if (!subEl || subEl.hidden || !overlay) return;
    const r = overlay.getBoundingClientRect();
    // 실제 조합 패널이 열려 있으면 레일이 그것을 밀어내지 않도록 메인 패널 안으로 들어간다(사용자 제보).
    const sideOpen = !!(sideEl && !sideEl.hidden);
    const inline = sideOpen || window.innerWidth - r.right < 156;
    if (inline) {
      if (subEl.parentElement !== overlay) overlay.insertBefore(subEl, bodyEl);
      subEl.classList.add('is-inline');
      for (const key of ['left', 'top', 'width', 'height']) subEl.style[key] = '';
    } else {
      if (subEl.parentElement !== document.body) document.body.append(subEl);
      subEl.classList.remove('is-inline');
      const top = Math.min(bodyEl.getBoundingClientRect().top, window.innerHeight - 160);
      // Keep the rail independent of the candidate list shrinking after a filter.
      const viewerBottom = document.querySelector('#resultViewer')?.getBoundingClientRect().bottom;
      const bottom = Math.min(window.innerHeight - 16, viewerBottom > top ? viewerBottom - 14 : window.innerHeight - 16);
      const contentHeight = (subEl.querySelector('.em-subheading')?.offsetHeight || 0)
        + (subEl.querySelector('.em-sublist')?.scrollHeight || 0) + 2;
      const height = Math.max(100, Math.min(contentHeight, bottom - top));
      Object.assign(subEl.style, { left: `${Math.round(r.right + 8)}px`, top: `${Math.round(top)}px`,
        width: '140px', height: `${Math.round(height)}px` });
    }
  }

  function positionSide() {
    if (library?.isOpen()) { if (sideEl) sideEl.hidden = true; library.position(); return; }
    if (!sideEl || sideEl.hidden || !overlay) return;
    // 레일이 아직 바깥에 떠 있으면 먼저 안으로 들인다(열리는 순서와 무관하게 같은 배치).
    if (subEl && !subEl.hidden && !subEl.classList.contains('is-inline')) positionSubcategories();
    const r = overlay.getBoundingClientRect();
    const railRight = subEl && !subEl.hidden && !subEl.classList.contains('is-inline')
      ? subEl.getBoundingClientRect().right : r.right;
    const width = Math.round(Math.min(360, Math.max(240, window.innerWidth - railRight - 24)));
    // Use the left side if there is no room beside the subcategory rail.
    const sideLeft = railRight + 8 + width <= window.innerWidth - 8 ? railRight + 8
      : Math.max(8, r.left - width - 8);
    // 높이는 메인 패널이 아니라 결과 칸(호스트) 바닥까지 — 메인 패널이 짧아도 조합 목록은 길게 본다(사용자 제보).
    const host = document.querySelector('#resultViewer')?.getBoundingClientRect();
    const bottom = Math.min(window.innerHeight - 16, host && host.bottom > r.top + 160 ? host.bottom - 14 : window.innerHeight - 16);
    sideEl.style.left = `${Math.round(sideLeft)}px`;
    sideEl.style.top = `${Math.round(r.top)}px`;
    sideEl.style.width = `${width}px`;
    sideEl.style.height = `${Math.round(Math.max(r.height, bottom - r.top))}px`;
  }

  function render(preserveScroll = false) {
    if (!overlay) return;
    const scrollTop = bodyEl.scrollTop;
    hideTip();                      // 행이 다시 그려지면 주인이 사라진다 - 유령 툴팁을 막는다
    library?.update();
    paintTrail();
    paintFilters();
    rows = [];
    let html = '';
    // 색인이 없으면 화면은 **내려받기 진행 표면**이 된다(사용자 결정 2026-09-13). 단추도 직접
    // 빌드 안내도 두지 않는다 - 열면 알아서 받는다. 그 동안 검색·조건·발줄은 잠근다.
    setLocked(mapState?.state !== 'ready');
    if (!mapState || mapState.state !== 'ready') {
      if (subEl) subEl.hidden = true;
      bodyEl.innerHTML = downloadHtml();
      const info = mapState?.install;
      const pct = Number(info?.download?.percent || 0);
      setStatus(info?.active ? `내려받는 중 ${pct}%` : '색인 준비 중', info?.active ? 'busy' : 'error');
      return;
    }
    if (input.value.trim()) {
      html += suggestHtml();
      rows = (suggest?.items || []).filter(it => !it.blocked && !pins.includes(it.tag)).map(it => it.tag);
    } else if (!pins.length && group) {
      html += browseHtml();
    } else if (!pins.length) {
      html += groupsHtml();
      setStatus(`태그 ${fmt(mapState.tags)} · 게시물 ${fmt(mapState.posts)}`);
    } else if (result) {
      if (result.status === 'error') {
        html += `<div class="em-empty">${esc(result.message || '실패')}</div>`;
        setStatus('오류', 'error');
      } else if (result.status === 'unknown_tag') {
        html += `<div class="em-empty">맵에 없는 태그: ${esc((result.unknown_pins || []).join(', '))}</div>`;
        setStatus('모르는 태그', 'error');
      } else if (!result.observed_posts) {
        html += `<div class="em-empty">이 조합으로 달린 게시물이 없습니다. ← 로 한 단계 올라가 보세요.</div>`;
        setStatus('0건', 'error');
      } else {
        const cs = result.candidates || [];
        rows = cs.map(c => c.tag);
        const gc = result.group_counts || null;   // 옛 백엔드(재시작 전)는 이 키가 없다 - 그래도 탭은 그린다
        html += catsHtml(gc, roles.size ? [...roles][0] : '', gc ? gc.reduce((n, r) => n + r.count, 0) : null);
        const sm = SORT_MODES.find(m => m.id === sortMode) || SORT_MODES[0];
        html += `<div class="em-cap">함께 달린 태그 <button type="button" class="em-sort" data-em-sort title="${esc(sm.title)} · 눌러서 바꾸기">${esc(sm.label)} ▾</button><span class="em-note">${cs.length}개${result.sampled ? ' · 표본으로 셈' : ''}</span></div>`;
        html += cs.length ? cs.map(candidateRow).join('') : `<div class="em-empty">5건 이상 함께 달린 태그가 없습니다.</div>`;
        setStatus(`${fmt(result.observed_posts)}건${result.sampled ? ' · 표본' : ''}`, 'ok',
          `${Math.round(result.elapsed_ms || 0)}ms${result.sampled ? ' · 교집합이 커서 표본으로 셌다(건수는 정확하다)' : ''}`);
      }
    }
    bodyEl.innerHTML = html + moreHtml();
    paintSubcategories();
    paintSide();
    if (active >= rows.length) active = rows.length - 1;
    paintActive(!preserveScroll);
    fitHeight();
    if (preserveScroll) bodyEl.scrollTop = scrollTop;
  }

  function paintActive(scroll = true) {
    bodyEl.querySelectorAll('[data-em-row]').forEach(el => {
      el.classList.toggle('is-active', Number(el.dataset.emRow) === active);
    });
    const el = bodyEl.querySelector(`[data-em-row="${active}"]`);
    if (el && scroll) el.scrollIntoView({ block: 'nearest' });
  }

  // ── 인원 팝업 (Fast Search 와 같은 체크 목록) ────────────────────────────
  function ensurePersonPopup() {
    if (personPopup) return personPopup;
    personPopup = document.createElement('div');
    personPopup.className = 'em-person-popup';
    personPopup.hidden = true;
    personPopup.setAttribute('role', 'dialog');
    document.body.append(personPopup);
    personPopup.addEventListener('click', event => {
      const quick = event.target.closest('[data-em-quick]');
      if (quick) {
        const which = quick.dataset.emQuick;
        if (which === 'all') persons = new Set(PERSON_IDS);
        else if (which === 'default') persons = new Set(DEFAULT_PERSONS);
        else { const g = PERSON_GROUPS.find(x => x.g === which); if (g) persons = new Set(g.ids); }
      } else {
        const row = event.target.closest('[data-em-person-id]');
        if (!row) return;
        const id = row.dataset.emPersonId;
        if (persons.has(id)) { if (persons.size > 1) persons.delete(id); } else persons.add(id);
      }
      personPopup.innerHTML = personPopupHtml();
      paintPersonButton();
      savePrefs(persons, ratings, sortMode);
      void explore();
    });
    return personPopup;
  }
  function personPopupHtml() {
    return `<div class="em-person-head"><span>인원 구성</span><span class="em-person-quick">
        <button type="button" data-em-quick="default">기본</button><button type="button" data-em-quick="all">전체</button>
        ${PERSON_GROUPS.map(g => `<button type="button" data-em-quick="${esc(g.g)}">${esc(g.g)}</button>`).join('')}</span></div>
      <div class="em-person-list">${PERSON_GROUPS.map(g => `<div class="em-person-group">${esc(g.g)}</div>`
        + g.ids.map(id => `<button type="button" class="em-person-row${persons.has(id) ? ' is-on' : ''}" data-em-person-id="${esc(id)}">
            <span class="em-person-check">${persons.has(id) ? '✓' : ''}</span><span>${esc(personLabels.get(id) || id.replace(/_/g, ' '))}</span></button>`).join('')).join('')}</div>`;
  }
  function openPersonPopup() {
    const popup = ensurePersonPopup();
    popup.innerHTML = personPopupHtml();
    popup.hidden = false;
    personBtn.setAttribute('aria-expanded', 'true');
    const rect = personBtn.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - pr.width - 8));
    let top = rect.bottom + 6;
    if (top + pr.height > window.innerHeight - 8) top = Math.max(8, rect.top - pr.height - 6);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
    document.addEventListener('pointerdown', onPersonOutside, true);
  }
  function closePersonPopup() {
    if (!personPopup || personPopup.hidden) return;
    personPopup.hidden = true; personPopup.innerHTML = '';
    if (personBtn) personBtn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', onPersonOutside, true);
  }
  function onPersonOutside(event) {
    if (personPopup && personPopup.contains(event.target)) return;
    if (event.target.closest?.('[data-em-person]')) return;
    closePersonPopup();
  }


  // ── 창 ───────────────────────────────────────────────────────────────────
  function build() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'em-overlay';
    overlay.hidden = true;
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', '이벤트 맵');
    overlay.innerHTML = `
      <div class="em-bar">
        <span class="em-icon" aria-hidden="true">E</span>
        <input class="em-input" type="search" autocomplete="off" spellcheck="false"
               aria-label="태그 찾기" placeholder="태그 찾기…">
        <span class="em-status" role="status" aria-live="polite"></span>
        <button type="button" class="em-close" aria-label="닫기">×</button>
      </div>
      <div class="em-trail"></div>
      <div class="em-filters"></div>
      <div class="em-library-bar"><button type="button" data-library-mode="save" aria-expanded="false">이 조합 저장하기</button><button type="button" data-library-mode="load" aria-expanded="false">조합 불러오기</button></div>
      <div class="em-library-panel" hidden></div>
      <div class="em-body" role="listbox"></div>
      <div class="em-foot">
        <span class="em-actions"><button type="button" class="em-random" data-em-random="select"
            title="지금 고른 인원·등급(핀이 있으면 그 안)에서 게시물 하나를 뽑아 Random 과 같은 파이프라인으로 메인 프롬프트에">랜덤 선택</button><button type="button" class="em-random" data-em-random="generate"
            title="랜덤 선택 뒤 바로 Generate">랜덤+생성</button></span>
        <span class="em-keys" title="↑↓ 이동 · Enter 꽂기 · − 제외 · Backspace 위로 · Esc 닫기">우클릭 = 제외</span>
        <label class="em-random-link" title="메인 Random과 Auto Gen이 현재 핀·제외·인원·등급을 사용합니다. 패널을 닫아도 연결됩니다."><input type="checkbox" data-em-random-link>랜덤 버튼 연결</label>
      </div>`;
    busyEl = document.createElement('div');
    busyEl.className = 'em-busy';
    busyEl.innerHTML = '<span class="em-busy-label">찾는 중…</span>';
    busyEl.addEventListener('pointerdown', event => { event.preventDefault(); event.stopPropagation(); });
    overlay.append(busyEl);
    document.body.append(overlay);
    input = overlay.querySelector('.em-input');
    statusEl = overlay.querySelector('.em-status');
    trailEl = overlay.querySelector('.em-trail');
    filtersEl = overlay.querySelector('.em-filters');
    bodyEl = overlay.querySelector('.em-body');
    footEl = overlay.querySelector('.em-foot');
    library = initEventMapLibrary({
      bar: overlay.querySelector('.em-library-bar'), panel: overlay.querySelector('.em-library-panel'), anchor: overlay,
      onClose: () => paintSubcategories(),
      onOpen: () => { samples = null; if (sideEl) sideEl.hidden = true; if (subEl) subEl.hidden = true; },
      getSelection: () => ({ pins: pins.slice(), exclude: excludes.slice(), ratings: [...ratings], persons: [...persons] }),
      applySelection: async selection => {
        if (linkPending || linkUncertain) throw new Error('랜덤 연결 상태를 확인한 뒤 다시 불러와주세요.');
        pins = selection.pins.slice(); excludes = selection.exclude.slice();
        ratings = new Set(selection.ratings); persons = new Set(selection.persons);
        group = ''; roles.clear(); subcategory = ''; samples = null; browse = null;
        input.value = ''; suggest = null; ++suggestSeq; clearTimeout(timer);
        savePrefs(persons, ratings, sortMode);
        if (randomLink.enabled) await syncRandomLink();
        await explore();
      }, toast, resize: fitHeight,
    });
    paintRandomLink();
    footEl.querySelector('[data-em-random-link]').addEventListener('change', event => {
      void syncRandomLink(event.target.checked);
    });

    overlay.querySelector('.em-close').addEventListener('click', close);
    input.addEventListener('input', () => { active = -1; scheduleSuggest(); });
    input.addEventListener('keydown', onKeyDown);

    trailEl.addEventListener('click', event => {
      const t = event.target;
      const goto = t.closest('[data-em-goto]');
      if (goto) { goTo(Number(goto.dataset.emGoto)); return; }
      const unpin = t.closest('[data-em-unpin]');
      if (unpin) { pins = pins.filter(x => x !== unpin.dataset.emUnpin); void explore(); return; }
      const unex = t.closest('[data-em-unexclude]');
      if (unex) { clearExclude(unex.dataset.emUnexclude); return; }
      if (t.closest('[data-em-group-back]')) { subcategory = ''; pins = []; excludes = []; browse = null; void loadBrowse(); return; }
      if (t.closest('[data-em-back]')) { goBack(); return; }
    });
    footEl.addEventListener('click', event => {
      const t = event.target;
      const rb = t.closest('[data-em-random]');
      if (rb) { void randomAssign(rb, rb.dataset.emRandom === 'generate'); return; }
    });
    filtersEl.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-em-insert]')) { void applyPins(t.closest('[data-em-insert]')); return; }
      if (t.closest('[data-em-copy]')) { void copyText(currentPrompt()); return; }
      if (t.closest('[data-em-samples]')) { if (samples) { samples = null; render(); } else void drawSamples(); return; }
      if (t.closest('[data-em-person]')) {
        if (personPopup && !personPopup.hidden) closePersonPopup(); else openPersonPopup();
        return;
      }

      const pill = t.closest('[data-em-r]');
      if (pill) {
        const id = pill.dataset.emR;
        if (ratings.has(id) && ratings.size === 1) return;      // 최소 하나는 남긴다
        if (ratings.has(id)) ratings.delete(id); else ratings.add(id);
        savePrefs(persons, ratings, sortMode);
        void explore(); return;
      }
    });
    bodyEl.addEventListener('click', event => {
      if (event.target.closest('[data-em-more-retry]')) { void loadMore(); return; }
      const t = event.target;
      const ex = t.closest('[data-em-exclude]');
      if (ex) { event.stopPropagation(); exclude(ex.dataset.emExclude); return; }
      const again = t.closest('[data-em-samples-again]');
      if (again) { void drawSamples(); return; }
      const si = t.closest('[data-em-sample-insert]');
      if (si) { insertText(samplePrompt(Number(si.dataset.emSampleInsert))); return; }
      const sc = t.closest('[data-em-sample-copy]');
      if (sc) { void copyText(samplePrompt(Number(sc.dataset.emSampleCopy))); return; }
      const gb = t.closest('[data-em-group]');
      if (gb) { pickGroup(gb.dataset.emGroup); return; }
      const sb = t.closest('[data-em-sort]');
      if (sb) {
        const i = SORT_MODES.findIndex(m => m.id === sortMode);
        sortMode = SORT_MODES[(i + 1) % SORT_MODES.length].id;
        savePrefs(persons, ratings, sortMode);
        void explore();
        return;
      }
      const cat = t.closest('[data-em-cat]');
      if (cat) {
        const id = cat.dataset.emCat;
        if (pins.length) { subcategory = ''; roles = id ? new Set([id]) : new Set(); void explore(); }
        else if (id) pickGroup(id);
        return;
      }
      const row = t.closest('[data-em-pin]');
      if (row) pin(row.dataset.emPin);
    });
    bodyEl.addEventListener('pointerover', event => {
      const row = event.target.closest ? event.target.closest('.em-row[data-em-pin]') : null;
      if (row) showTip(row);
    });
    bodyEl.addEventListener('pointerout', event => {
      const row = event.target.closest ? event.target.closest('.em-row[data-em-pin]') : null;
      if (!row) return;
      if (event.relatedTarget && row.contains(event.relatedTarget)) return;
      hideTip();
    });
    bodyEl.addEventListener('scroll', () => {
      hideTip();
      if (!moreError && bodyEl.scrollHeight > bodyEl.clientHeight
          && bodyEl.scrollHeight - bodyEl.clientHeight - bodyEl.scrollTop <= 8) void loadMore();
    }, { passive: true });
    // 우클릭 = 제외(시험대와 같은 손버릇).
    bodyEl.addEventListener('contextmenu', event => {
      const row = event.target.closest('[data-em-pin]');
      if (!row) return;
      event.preventDefault();
      exclude(row.dataset.emPin);
    });
    bodyEl.addEventListener('mousedown', event => {
      // 행을 눌러도 포커스는 검색 칸에 남긴다(키보드가 계속 먹게).
      if (event.target.closest('button, input')) return;
      event.preventDefault();
    });
    window.addEventListener('resize', position);
    // Generation Info 를 끌어 키우면 뷰어가 줄어든다 - 창 크기가 아니라 뷰어 크기를 따라간다.
    const viewer = document.querySelector('#resultViewer');
    if (viewer && typeof ResizeObserver === 'function') new ResizeObserver(() => position()).observe(viewer);

    subEl = document.createElement('div');
    subEl.className = 'em-subpanel';
    subEl.hidden = true;
    subEl.dataset.expanded = 'false';
    subEl.setAttribute('aria-label', '소분류 선택');
    document.body.append(subEl);
    subEl.addEventListener('click', event => {
      const toggle = event.target.closest('[data-em-sub-toggle]');
      if (toggle) {
        if (subEl.classList.contains('is-inline')) {
          subEl.dataset.expanded = subEl.dataset.expanded === 'true' ? 'false' : 'true';
          toggle.setAttribute('aria-expanded', subEl.dataset.expanded);
          fitHeight();
        }
        return;
      }
      const button = event.target.closest('[data-em-sub]');
      if (!button || busyCount || button.dataset.emSub === subcategory) return;
      subcategory = button.dataset.emSub;
      if (pins.length) void explore(); else void loadBrowse();
    });

    sideEl = document.createElement('div');
    sideEl.className = 'em-overlay em-side';
    sideEl.hidden = true;
    sideEl.setAttribute('role', 'dialog');
    sideEl.setAttribute('aria-label', '실제 조합');
    document.body.append(sideEl);
    sideEl.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-em-side-close]')) { samples = null; render(); return; }
      if (t.closest('[data-em-samples-again]')) { void drawSamples(); return; }
      const si = t.closest('[data-em-sample-insert]');
      if (si) { insertText(samplePrompt(Number(si.dataset.emSampleInsert))); return; }
      const sc = t.closest('[data-em-sample-copy]');
      if (sc) { void copyText(samplePrompt(Number(sc.dataset.emSampleCopy))); return; }
      const sa = t.closest('[data-em-sample-apply]');
      if (sa) { void runSample(Number(sa.dataset.emSampleApply), 'apply', sa); return; }
      const sg = t.closest('[data-em-sample-generate]');
      if (sg) { void runSample(Number(sg.dataset.emSampleGenerate), 'generate', sg); return; }
      const sag = t.closest('[data-em-sample-apply-generate]');
      if (sag) { void runSample(Number(sag.dataset.emSampleApplyGenerate), 'apply+generate', sag); }
    });
    return overlay;
  }

  function onKeyDown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!rows.length) return;
      event.preventDefault();
      active = event.key === 'ArrowDown' ? Math.min(rows.length - 1, active + 1) : Math.max(0, active - 1);
      paintActive();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (!rows.length) return;
      pin(rows[active >= 0 ? active : 0]);
      return;
    }
    if (event.key === '-' && rows.length && active >= 0) {
      event.preventDefault();
      exclude(rows[active]);
      return;
    }
    if (event.key === 'Backspace' && !input.value) {
      event.preventDefault();
      goBack();
    }
  }

  /** 결과 칸의 **왼쪽**에 붙는다(사용자 지정 2026-09-12): 폭은 Fast Search 의 절반(≤ 360),
   *  높이는 빈 화면이면 결과 칸의 절반, 목록이 길면 결과 칸 높이까지 자란다(한 번에 보이는 태그를
   *  늘리자는 사용자 지정 2026-09-12). 이미지 왼편 가장자리를 살짝 가리는 정도. */
  function position() {
    if (!overlay || overlay.hidden) return;
    // 뷰어(이미지 칸)만 호스트다 - #rightTabResult 로 재면 Generation Info 위까지 내려간다(사용자 제보).
    const host = document.querySelector('#resultViewer') || document.querySelector('#rightTabResult') || document.querySelector('.app-layout');
    const r = host ? host.getBoundingClientRect() : null;
    if (!r || r.width < 240 || r.height < 160) {
      overlay.style.left = '16px'; overlay.style.transform = 'none'; overlay.style.top = '64px';
      overlay.style.width = 'min(360px, calc(100vw - 32px))';
      heightCaps = { base: Math.min(440, window.innerHeight - 96), hard: window.innerHeight - 32 };
      fitHeight(); return;
    }
    const pad = 14;
    // E 단추(반구, 24px)가 왼쪽 가장자리에 있으니 그 오른쪽부터 시작한다.
    const width = Math.round(Math.min(360, Math.max(240, (r.width - pad * 2) / 2)));
    overlay.style.transform = 'none';
    overlay.style.left = `${Math.round(r.left + pad + 20)}px`;
    overlay.style.top = `${Math.round(r.top + pad)}px`;
    overlay.style.width = `${width}px`;
    heightCaps = { base: Math.round(Math.min(r.height - pad * 2, Math.max(280, r.height * 0.5))),
                   hard: Math.round(r.height - pad * 2) };
    fitHeight();
  }
  function fitHeight() {
    if (!overlay || overlay.hidden || !heightCaps.base) return;
    // 몸통이 내용만큼 자란다(hard 를 넘지 않게). 8줄 상한은 걷어냈다 - 사용자가 더 보고 싶어했다.
    let want = heightCaps.base;
    const chrome = overlay.offsetHeight - bodyEl.clientHeight;
    want = Math.max(want, Math.ceil(chrome + bodyEl.scrollHeight + 4));
    overlay.style.maxHeight = `${Math.round(Math.min(heightCaps.hard, want))}px`;
    positionSubcategories();
    positionSide();
    library?.position();
  }

  async function show() {
    build();
    overlay.hidden = false;
    open = true;
    if (tabBtn) tabBtn.setAttribute('aria-pressed', 'true');
    position();
    focusInput();                   // 열자마자 - 바로 칠 수 있게(사용자 지정 2026-09-12 밤)
    setStatus('여는 중…', 'busy');
    dlFailed = false; dlError = '';      // 다시 열면 다시 시도한다
    await loadState();
    if (mapState?.state !== 'ready') { await autoDownload(); startDlPoll(); }
    render();
    if (mapState?.state === 'ready' && pins.length) void explore();
    position();
    focusInput();                   // 그려진 뒤 한 번 더(그 사이 누가 가져갔어도)
  }
  function focusInput() {
    if (!input || !open) return;
    input.focus({ preventScroll: true });
    requestAnimationFrame(() => { if (open && document.activeElement !== input) input.focus({ preventScroll: true }); });
  }
  function close() {
    library?.close();
    moreRequest = null; moreError = '';
    if (!overlay) return;
    closePersonPopup();
    overlay.hidden = true;
    open = false;
    if (subEl) subEl.hidden = true;
    if (sideEl) { sideEl.hidden = true; sideEl.innerHTML = ''; }
    if (tabBtn) tabBtn.setAttribute('aria-pressed', 'false');
    clearTimeout(timer);
    stopDlPoll();                   // 화면 폴링만 멈춘다 - 내려받기는 서버에서 계속 돈다
    seq += 1; suggestSeq += 1;
  }
  function toggle() { if (open) close(); else void show(); }

  // 프롬프트 옆의 작은 E 단추(index.html 의 #eventMapTab). 없어도 Ctrl+E 는 된다.
  tabBtn = document.getElementById('eventMapTab');
  if (tabBtn) {
    // 단추가 포커스를 가져가면 열린 뒤 검색 칸으로 옮겨야 한다 - 아예 안 가져가게 한다.
    tabBtn.addEventListener('mousedown', event => event.preventDefault());
    tabBtn.addEventListener('click', toggle);
  }

  // Ctrl+E. 브라우저의 기본 동작(주소창 검색)은 막는다. Esc 는 어디에 포커스가 있든 닫되,
  // 인원 팝업이 열려 있으면 그것만 먼저 닫는다.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation();
      if (personPopup && !personPopup.hidden) { closePersonPopup(); return; }
      if (library?.isOpen()) {
        library.close();
        overlay.querySelector('.em-library-bar button')?.focus();
        return;
      }
      close(); return;
    }
    const hit = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key || '').toLowerCase() === 'e';
    if (!hit) return;
    event.preventDefault();
    // Ctrl+E 를 다시 치면 닫는다(Esc 와 같다 - 사용자 지정 2026-09-12 밤). 전에는 검색 칸으로 되돌아갔다.
    if (open) { close(); return; }
    void show();
  }, true);

  // 패널 밖을 누르면 닫는다 - 빈 이미지 영역·상단 메뉴·다른 도구 어디든. 생성된 이미지를 패널이 가려
  // 바로 못 보던 문제(사용자 지정 2026-09-12 밤). **예외 하나**: 메인 프롬프트 칸은 안 닫는다 - 패널을
  // 보면서 프롬프트를 고치는 흐름이 있다. 패널·둘째 패널·인원 팝업·툴팁·E 단추 자신은 '안'이다.
  document.addEventListener('pointerdown', event => {
    if (!open) return;
    const t = event.target;
    if (!(t instanceof Element)) return;
    if (library?.contains(t) || overlay?.contains(t) || subEl?.contains(t) || sideEl?.contains(t) || personPopup?.contains(t) || tipEl?.contains(t)) return;
    if (tabBtn && (t === tabBtn || tabBtn.contains(t))) return;     // toggle 이 처리한다
    if (t.closest('#promptEdit, .prompt-highlight-wrap')) return;    // 메인 프롬프트 칸 - 예외
    close();
  }, true);

  const refreshRandomLink = () => getJson('/api/event-map/random-link').then(receiveRandomLink).catch(() => {});
  void refreshRandomLink();
  return { show, close, toggle, isOpen: () => open, pins: () => pins.slice(),
    isRandomLinked: () => randomLink.enabled, isRandomLinkPending: () => linkPending > 0 || linkUncertain,
    receiveRandomLink, refreshRandomLink };
}
