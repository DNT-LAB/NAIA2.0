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
 * 공용 Draggable Window: 제목줄 이동, 크기 조절, 바깥 클릭에도 유지.
 *
 * 화면 버전 둘(사용자 지정 2026-10-14): 머리줄의 [3단 지도 | 기존] 토글. 고른 쪽을 기억한다.
 *  · 3단 지도 = Danbooru 위키 tag_groups 를 다듬은 갈래 › 그룹 › 절 지도(`/api/event-map/tree*`).
 *    핀이 없으면 갈래 탭 · 왼쪽 나무(그룹 아래로 고른 그룹의 절이 펼쳐진다) · 오른쪽 고른 절의 태그 전부
 *    (사용자 스케치 2026-10-14 - 절마다 '+N개 더' 가 박힌 개요는 비좁아 걷었다). 핀을 꽂으면 기존과 같은 추적이되
 *    후보는 지도의 태그로만 오고(explore `tree=1`) 탭이 갈래별 후보 수가 된다. 갈래 탭에서는 같은 나무에
 *    그룹 · 절별 후보 수(0 은 숨김)와 고른 절의 후보, [전체] 탭에서는 경로가 붙은 한 줄 목록(사용자 결정 2026-10-14).
 *  · 기존 = 대분류 · 소분류 화면. 핀 · 제외 · 인원 · 등급은 두 화면이 같이 쓴다.
 */

import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

import { initEventMapLibrary } from './eventMapLibrary.mjs?v=20261014-stage1';

const DEBOUNCE_MS = 150;
// 떠 있는 창의 크기. 폭의 바닥은 예전 창과 같은 400(조건 줄이 더 길면 그만큼 넓힌다 - panelMinimumWidth),
// 높이의 바닥은 빈 화면에서도 창이 납작해지지 않을 만큼.
const EM_BASE_WIDTH = 400;
const EM_BASE_HEIGHT = 300;
const EM_MIN_HEIGHT = 220;
const EM_MANUAL_SIZE_KEY = 'naia.eventMap.manualSize';
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
// 화면 버전 · 3단 지도에서 마지막으로 본 갈래 · 그룹. 처음 여는 사람은 3단 지도(목업 승인 2026-10-14).
const VIEW_KEY = 'naia_event_map_view_v1';
function loadViewPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(VIEW_KEY) || 'null');
    return raw && typeof raw === 'object' ? raw : {};
  } catch { return {}; }
}
function saveViewPrefs(view) {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch { /* 저장 못 해도 동작한다 */ }
}
// 후보 정렬(사용자 지정 2026-09-12 밤). 서버가 세운다 - 상위 40 만 내려오므로 화면에서 다시 세우면 안 된다.
const SORT_MODES = [
  { id: 'lift', label: 'lift 순', title: '핀이 있을 때 평소보다 몇 배 자주 나오나(관측/(기댓값+3)). 핀이 흔하면 희귀 태그가 위로 온다' },
  { id: 'posts', label: 'post 순', title: '핀과 함께 달린 게시물 수. 흔한 태그가 위로 온다' },
  { id: 'mix', label: 'mix 순', title: '관측 × ln(lift) - 많이 나오면서 치우친 것(G² 기여분). 둘의 절충' },
];

export function initEventMap({ insertTag, insertAtCursor = null, showToast, getPromptText, generateNow, onRandomLinkChange,
                               openPeSlash = null, onPermanentExcludeChange = null,
                               onStage = null, onOpenSaved = null, onLibraryChange = null, isStaged = null,
                               getStagedCount = null, onOpenStaging = null } = {}) {
  let randomLink = { enabled: false, revision: -1 }, linkPending = 0;
  // 랜덤 연결은 한 갈래뿐이다(서버 상태 하나): event = 이 창의 지금 조합, staging = S 창의 스테이징 풀
  // (사용자 지시 2026-10-14 - 한쪽을 켜면 다른 쪽이 꺼진다). 이 창의 체크박스 · 핀 동기화는 event 갈래일 때만.
  const eventLinked = () => randomLink.enabled && randomLink.mode !== 'staging';
  let linkUncertain = false;
  let linkQueue = Promise.resolve(), linkKey = '';
  function paintRandomLink() {
    const checkbox = footEl?.querySelector('[data-em-random-link]');
    if (checkbox) { checkbox.checked = eventLinked(); checkbox.disabled = linkPending > 0; }
    onRandomLinkChange?.(randomLink.enabled, linkPending > 0 || linkUncertain);
  }
  function receiveRandomLink(state) {
    if (!state || state.revision < randomLink.revision) return;
    randomLink = state;
    linkUncertain = false;
    // 이 창의 조합이 연결된 것이 아니면(꺼짐 · 스테이징) 마지막으로 보낸 열쇠를 잊는다 - 안 그러면 다시 켤 때
    // '보낸 것과 같다' 로 보고 요청을 건너뛴다.
    if (!eventLinked()) linkKey = '';
    if (eventLinked() && !linkPending) {
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
  function syncRandomLink(enabled = eventLinked()) {
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
  let widenNote = '';             // 고른 분류가 비어 전체로 되돌렸을 때 한 번 보여 주는 문구
  let sideEl = null;              // 실제 조합 둘째 패널
  let library = null;
  let open = false, seq = 0, suggestSeq = 0, timer = null;
  let panel = null;
  let manualSize = readManualSize();   // 손잡이로 크기를 잡았는가 - 잡은 뒤로는 내용에 맞춰 높이를 바꾸지 않는다
  let mapState = null;            // /state 응답. 열 때마다 새로 받는다(색인이 바뀔 수 있다).
  let personLabels = new Map();   // id -> 화면 문구 (서버가 준다)
  let pins = [], excludes = [];
  const prefs = loadPrefs();
  let ratings = new Set(prefs?.ratings || DEFAULT_RATINGS);
  let persons = new Set(prefs?.persons || DEFAULT_PERSONS);
  let sortMode = prefs?.sort || 'mix';   // 기본 = mix(사용자 지정 2026-09-12 밤 - 밸런스)
  let relaxOne = false;                  // [-1 허용]: 핀 n개 중 n-1개만 있는 게시물까지(사용자 지정 2026-09-13)
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
  // 3단 지도. 골격(/tree)은 열 때마다 새로 받는다(색인이 바뀌면 절의 태그 수가 바뀐다).
  const viewPrefs = loadViewPrefs();
  let viewMode = viewPrefs.mode === 'classic' ? 'classic' : 'tree';
  let treeMap = null, treeError = '';
  let treeSel = { d1: String(viewPrefs.d1 || ''), d2: String(viewPrefs.d2 || ''), d3: '' };
  const treeLastD2 = new Map();   // 갈래 -> 마지막으로 본 그룹(이번 실행 동안)
  let treeData = null;            // 핀이 없을 때: 고른 절의 결과(쪽 단위 · 같은 그룹의 절마다 후보 수)
  // 단순 검색 모드(사용자 지시 2026-10-14): 줄을 눌러도 핀을 꽂지 않는다(탐사 없이 보기만) · lift 자리에 [복사][삽입].
  let simpleMode = Boolean(viewPrefs.simple);
  let treeAll = false;            // 나무 맨 위 [전체] - 갈래의 태그 전부(그룹 · 절로 가두지 않는다). 갈래를 바꿔도 유지
  let treeFilter = '';            // 핀이 있을 때: 갈래 탭(비면 전체). 그 안의 그룹 · 절은 treeSel 을 같이 쓴다
  let ttabsEl = null, actsEl = null, menuEl = null;
  // 영구 제외(Search 의 붉은 줄과 **같은 글**). 서버가 이 글로 게시물을 거른다 - 화면은 고치고 보여 줄 뿐이다.
  let permText = '', permInfo = null, permOpen = false, permSaving = 0;
  let permEl = null, permInput = null, permStatus = null, chipPanel = null;
  let permQueue = Promise.resolve();   // 영구 제외 조회 · 저장은 한 줄로(늦은 응답이 새 글을 덮지 않게)
  // 영구 제외 입력 줄의 자동완성 - 이벤트 맵 색인의 태그(58,406개)만 낸다(/suggest). 항은 언제나 태그 하나 전체 일치다
  // (사용자 지시 2026-10-14 - '* 없이 항상 고정 태그 제외'). 커서 앞 쉼표 뒤의 조각이 질의다.
  let acEl = null, acItems = [], acActive = -1, acSeq = 0, acTimer = null;
  const isTree = () => viewMode === 'tree';

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
    // 덮개는 몸통 안에서 검색 줄 **아래**를 덮는다 - 찾는 동안에도 검색 칸은 칠 수 있다. 핸들 줄은 몸통 밖이다.
    const bar = panel?.body.querySelector('.em-bar');
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

  async function loadBrowse(keepWidenNote = false) {
    if (!keepWidenNote) widenNote = '';
    if (eventLinked()) void syncRandomLink();
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
    // 대분류 목록에서도 소분류가 비면 전체로 되돌린다. 여기서 대분류 자체는 '보고 있는 화면'
    // 이므로 바꾸지 않는다 - 소분류만 푼다.
    if (mine === seq && browse?.status !== 'error' && subcategory && widenEmptySelection(
      { ...browse, status: 'matched', group_counts: null })) { void loadBrowse(true); return; }
    render();
  }

  // ── 영구 제외 ─────────────────────────────────────────────────────────────
  // 입력 줄 = 태그를 **하나씩** 더한다(자동완성 = 이벤트 맵 색인의 태그만 - 고른 것만 들어간다). 목록은 [상세 보기] 의
  // 칩 창에서 보고 지운다(사용자 지시 2026-10-14 - 쉼표로 구분해 치던 칸을 없앴다). 글 자체는 Search 의 영구 제외와
  // 같은 쉼표 목록이라 저장은 언제나 글 전체를 보낸다.
  const splitTerms = text => String(text || '').split(',').map(t => t.trim()).filter(Boolean);
  const normTerm = t => String(t || '').trim().replace(/^\*+/, '').toLowerCase().replace(/_/g, ' ').replace(/\s+/g, ' ');
  function loadPermanent() {
    // 저장과 같은 줄에 선다 - 따로 가면 늦게 온 조회가 방금 저장한 글을 옛 글로 되돌리고, 다음 더하기가 그 옛 글에서
    // 만들어져 앞의 것이 사라졌다(재리뷰 2026-10-15).
    permQueue = permQueue.then(async () => {
      try { permInfo = await getJson('/api/event-map/permanent-exclude', {}); permText = String(permInfo.text || ''); }
      catch { permInfo = null; }
      paintPermanent();
    }).catch(() => {});
    return permQueue;
  }
  function paintPermanent() {
    const btn = filtersEl?.querySelector('[data-emt-perm]');
    const n = splitTerms(permText).length;
    if (btn) {
      btn.textContent = `영구 제외${n ? ` · ${n}` : ''}`;
      btn.classList.toggle('is-on', n > 0 || permOpen);
      btn.setAttribute('aria-expanded', String(permOpen));
    }
    if (permStatus) {
      const tags = permInfo?.tags || [];
      permStatus.textContent = permSaving ? '저장 중…' : (permInfo ? `걸린 태그 ${fmt(permInfo.tag_count || 0)}` : '');
      permStatus.title = tags.length ? `${tags.join(', ')}${permInfo.tag_count > tags.length ? ' …' : ''}` : '';
    }
    paintChips();
  }
  function closeAc() {
    clearTimeout(acTimer); ++acSeq;
    acItems = []; acActive = -1;
    if (acEl) { acEl.hidden = true; acEl.innerHTML = ''; }
  }
  const fmtK = n => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n || 0));
  function paintAc() {
    if (!acEl) {
      acEl = document.createElement('div');
      acEl.className = 'emt-ac';
      acEl.setAttribute('role', 'listbox');
      document.body.append(acEl);
      acEl.addEventListener('mousedown', event => event.preventDefault());   // 입력 칸이 초점을 잃지 않게
      acEl.addEventListener('click', event => {
        const row = event.target.closest('[data-ac]');
        if (row) chooseAc(Number(row.dataset.ac));
      });
    }
    if (!acItems.length || !permOpen) { acEl.hidden = true; return; }
    acEl.innerHTML = acItems.map((it, i) => `<div class="emt-ac-row${i === acActive ? ' is-active' : ''}${it.blocked === '영구 제외' ? ' is-off' : ''}" data-ac="${i}" role="option">
        <span class="emt-ac-tag">${esc(it.tag)}</span><span class="emt-ac-kind">${esc(it.blocked === '영구 제외' ? '이미 제외' : (it.role_label || (it.group && it.group !== 'unsorted' ? roleLabel(it.group) : '')))}</span><span class="emt-ac-n">${fmtK(it.observed)}</span></div>`).join('');
    acEl.hidden = false;
    acEl.style.zIndex = String(Number(overlay.style.zIndex) + 2);
    const r = permInput.getBoundingClientRect();
    acEl.style.left = `${Math.round(r.left)}px`;
    acEl.style.top = `${Math.round(r.bottom + 2)}px`;
    acEl.style.width = `${Math.round(Math.max(260, Math.min(r.width, 380)))}px`;
  }
  function scheduleAc() {
    clearTimeout(acTimer);
    const q = permInput.value.trim();
    if (!q) { closeAc(); return; }
    acTimer = setTimeout(async () => {
      const mine = ++acSeq;
      try {
        const body = await getJson('/api/event-map/suggest', { q, limit: 8 });
        if (mine !== acSeq) return;
        acItems = body.items || [];
        acActive = acItems.findIndex(it => it.blocked !== '영구 제외');
      } catch { if (mine === acSeq) { acItems = []; acActive = -1; } }
      paintAc();
    }, DEBOUNCE_MS);
  }
  /** 자동완성에서 고른 태그를 영구 제외에 더한다(곧바로 저장). 칸은 비워 다음 태그를 칠 수 있게. */
  function chooseAc(i) {
    const it = acItems[i];
    if (!it) return;
    closeAc();
    if (it.blocked === '영구 제외') { toast(`이미 영구 제외에 있습니다 — ${it.tag}`, 'info'); return; }
    permInput.value = '';
    queuePermanent(() => [...splitTerms(permText), it.tag], `영구 제외에 더했습니다 — ${it.tag}`);
  }

  function openPermanent(on) {
    if (!permEl) return;
    permOpen = !!on && isTree();
    permEl.hidden = !permOpen;
    if (!permOpen) closeAc();
    if (permOpen) { permInput.value = ''; permInput.focus({ preventScroll: true }); }
    paintPermanent();
    fitHeight();
  }
  // 저장은 한 줄로 선다. 목록은 **차례가 왔을 때** 그때의 글에서 만든다 - 앞 저장의 응답 전에 다음 태그를 고르면
  // 둘 다 옛 글에서 만들어 앞의 것이 사라졌다(리뷰 2026-10-14).
  function queuePermanent(makeTerms, done) {
    permQueue = permQueue.then(() => savePermanentTerms(makeTerms(), done)).catch(() => {});
  }
  /** 영구 제외 글을 저장한다(항 목록 -> 쉼표 글). 저장되면 Search 창의 영구 제외 칸도 같은 글로(같은 화면 안). */
  async function savePermanentTerms(terms, done) {
    const text = terms.join(', ');
    if (text === permText.trim()) return;
    permSaving++; paintPermanent();
    try {
      permInfo = await postJson('/api/event-map/permanent-exclude', { text });
      permText = String(permInfo.text || '');
      if (typeof onPermanentExcludeChange === 'function') onPermanentExcludeChange(permText);
      toast(done || (permText ? `영구 제외를 저장했습니다 — 걸린 태그 ${fmt(permInfo.tag_count || 0)}개` : '영구 제외를 비웠습니다'), 'success');
      if (open && mapState?.state === 'ready') void explore();   // 걸러지는 게시물이 바뀌었다 - 지금 화면을 다시 묻는다
    } catch (error) {
      toast(`영구 제외 저장 실패 — ${error.message}`, 'error');
    } finally { permSaving--; paintPermanent(); }
  }

  // [상세 보기] = 영구 제외 칩 창. 칩의 × 로 하나씩 지운다. 이벤트 맵에서 걸리는 태그가 없는 항(Search 전용 문법
  // `~x` · 없는 태그)은 흐리게 - 지우지 않아도 이벤트 맵에는 영향이 없다.
  function ensureChips() {
    if (chipPanel) return chipPanel;
    chipPanel = createDraggablePanel({
      document, window, id: 'permExcludeWindow', title: '영구 제외', variant: 'em-overlay em-window emt-chips-window',
      storageKey: 'event-map-permanent', width: 340, height: 300, minWidth: 260, minHeight: 160, maxWidth: 700,
      // 처음 자리 = 이벤트 맵 창 오른쪽(겹치면 입력 줄을 가린다). 그 뒤로는 옮긴 자리를 기억한다.
      initial: (r => ({ x: Math.round(Math.min(r.right + 8, window.innerWidth - 348)), y: Math.round(r.top) }))(overlay.getBoundingClientRect()),
      resizable: true,
    });
    chipPanel.body.innerHTML = `<div class="emt-chips-head"></div><div class="emt-chips"></div>
      <div class="emt-chips-note">흐린 칩 = 이벤트 맵에서는 걸리는 태그가 없다(Search 전용 문법 · 없는 태그). 지우면 Search 의 영구 제외에서도 빠진다.</div>`;
    chipPanel.body.addEventListener('click', event => {
      const x = event.target.closest('[data-chip-x]');
      if (!x || permSaving) return;
      const gone = splitTerms(permText)[Number(x.dataset.chipX)];
      if (gone == null) return;
      // 차례가 왔을 때의 글에서 그 항을 뺀다(번호가 아니라 글자로 - 그 사이에 목록이 바뀌어도 맞는 것을 뺀다).
      queuePermanent(() => { const terms = splitTerms(permText); const at = terms.indexOf(gone);
        return at < 0 ? terms : terms.filter((_, i) => i !== at); }, `영구 제외에서 뺐습니다 — ${gone}`);
    });
    return chipPanel;
  }
  function paintChips() {
    if (!chipPanel || !chipPanel.isOpen()) return;
    const terms = splitTerms(permText);
    const hits = new Map((permInfo?.terms || []).map(t => [t.term, t.tags || []]));
    chipPanel.setTitle(`영구 제외 · ${terms.length}`);
    chipPanel.body.querySelector('.emt-chips-head').textContent = permInfo ? `이벤트 맵에서 걸린 태그 ${fmt(permInfo.tag_count || 0)}` : '';
    chipPanel.body.querySelector('.emt-chips').innerHTML = terms.length ? terms.map((t, i) => {
      const tags = hits.get(t);
      const dead = Array.isArray(tags) && !tags.length;
      return `<span class="emt-chip${dead ? ' is-dead' : ''}" title="${esc(dead ? '이벤트 맵에서는 걸리는 태그가 없다' : `걸리는 태그: ${(tags || [normTerm(t)]).join(', ')}`)}">${esc(t)}<button type="button" data-chip-x="${i}" aria-label="${esc(t)} 빼기">×</button></span>`;
    }).join('') : '<div class="st-empty">영구 제외 태그가 없습니다. 입력 줄에서 태그를 쳐서 더한다.</div>';
    chipPanel.body.inert = permSaving > 0;
  }
  function openChips() {
    ensureChips();
    if (chipPanel.isOpen()) { chipPanel.close(); return; }
    chipPanel.open();
    chipPanel.el.style.zIndex = String(Number(overlay.style.zIndex) + 1);
    paintChips();
    void loadPermanent();   // 항마다 걸리는 태그를 새로(색인이 열린 뒤라야 칩이 흐림을 안다)
  }

  // ── 3단 지도 ──────────────────────────────────────────────────────────────
  function rememberView() { saveViewPrefs({ mode: viewMode, d1: treeSel.d1, d2: treeSel.d2, simple: simpleMode }); }
  const treeBranch = id => (treeMap?.d1 || []).find(b => b.id === id) || null;
  function treeGroupOf(d2) {
    for (const b of treeMap?.d1 || []) { const g = b.d2.find(x => x.id === d2); if (g) return g; }
    return null;
  }
  const treeSectionOf = (d2, d3) => treeGroupOf(d2)?.d3.find(x => x.id === d3) || null;
  /** 핀 질의에 얹는 지도 조건. 대분류(groups · subcategory)는 기존 화면의 것이라 비운다. */
  function treeParams() {
    if (!isTree()) return {};
    const here = treeFilter && treeSel.d1 === treeFilter && !treeAll;
    return { groups: '', subcategory: '', tree: 1, d1: treeFilter, d2: here ? treeSel.d2 : '', d3: here ? treeSel.d3 : '' };
  }
  /** 핀 화면의 갈래 · 그룹 · 절을 고른다. 응답의 그룹 · 절별 수(가두기 전의 풀이라 어느 자리의 응답이든 같다)로
   *  후보가 있는 자리만 고른다 - 바라는 그룹이 비었으면 그 갈래의 첫 비지 않은 그룹, 바라는 절이 비었으면 그 그룹 전체.
   *  바뀌었으면 true. */
  function choosePinnedSlot(d1, d2 = treeSel.d2, d3 = treeSel.d3) {
    const b = treeBranch(d1);
    const counts = result?.tree_counts;
    if (!b || !counts?.d2) return false;
    const c3 = (g, x) => counts.d3?.[`${g}\t${x}`] || 0;
    const g = b.d2.find(x => x.id === d2 && counts.d2[x.id]) || b.d2.find(x => counts.d2[x.id]);
    if (!g) return false;
    // 절을 안 골랐거나 그 절이 비었으면 그룹 전체('') - 그룹을 누르면 그 그룹 전부다(사용자 지시 2026-10-14).
    const x = g.id === d2 && d3 ? g.d3.find(r => r.id === d3 && c3(g.id, r.id)) : null;
    const next = { d1: b.id, d2: g.id, d3: x?.id || '' };
    if (next.d1 === treeSel.d1 && next.d2 === treeSel.d2 && next.d3 === treeSel.d3) return false;
    treeSel = next;
    treeLastD2.set(b.id, g.id);
    rememberView();
    return true;
  }
  function treeFilterParams() { const fp = filterParams(); return { ratings: fp.ratings, persons: fp.persons }; }

  async function loadTreeMap() {
    try { treeMap = await getJson('/api/event-map/tree', {}); treeError = ''; }
    catch (error) { treeMap = null; treeError = String(error && error.message || error); }
    // 기억한 자리가 지도에서 사라졌으면(지도 판이 바뀌었다) 첫 자리로.
    const b = treeBranch(treeSel.d1) || treeMap?.d1?.[0];
    if (!b) { treeSel = { d1: '', d2: '', d3: '' }; return; }
    const g = b.d2.find(x => x.id === treeSel.d2) || b.d2[0];
    treeSel = { d1: b.id, d2: g?.id || '', d3: g?.d3.some(x => x.id === treeSel.d3) ? treeSel.d3 : '' };
  }

  /** 핀이 없을 때의 3단 지도: 고른 절 하나 · 그룹 전체(절 = '') · 갈래 전체([전체]) - 모두 쪽 단위. */
  async function loadTree() {
    if (eventLinked()) void syncRandomLink();
    moreRequest = null; moreError = '';
    active = -1;
    treeData = null;
    if (bodyEl) bodyEl.scrollTop = 0;
    const mine = ++seq;
    if (!treeMap) {
      setStatus('지도를 여는 중…', 'busy');
      await loadTreeMap();
      if (mine !== seq) return;
    }
    if (!treeSel.d2) { render(); return; }
    setStatus('찾는 중…', 'busy');
    setBusy(true);
    try {
      const where = treeAll ? { d1: treeSel.d1, flat: 1 } : treeSel.d3 ? { d2: treeSel.d2, d3: treeSel.d3 }
        : { d2: treeSel.d2, flat: 1 };
      const body = await getJson('/api/event-map/tree/browse', { ...where, limit: CANDIDATE_LIMIT, ...treeFilterParams() });
      if (mine !== seq) return;
      treeData = body;
    } catch (error) {
      if (mine !== seq) return;
      // fetch 자체가 실패하면(서버가 꺼졌다) 브라우저 문구 'Failed to fetch' 대신 우리 말로.
      treeData = { status: 'error', candidates: [], sections: [],
        message: error instanceof TypeError ? '서버에 연결하지 못했습니다' : error.message };
    } finally { setBusy(false); }
    render();
  }
  function pickTree(d1, d2 = '', d3 = '') {
    const b = treeBranch(d1);
    if (!b) return;
    const g = b.d2.find(x => x.id === d2) || b.d2.find(x => x.id === treeLastD2.get(d1)) || b.d2[0];
    treeSel = { d1: b.id, d2: g?.id || '', d3: g?.d3.some(x => x.id === d3) ? d3 : '' };
    if (g) treeLastD2.set(b.id, g.id);
    rememberView();
    void loadTree();
  }
  /** 줄 아래 경로를 눌렀다 - 그 갈래 [전체] / 그룹 [전체] / 절로 간다. 핀이 있으면 그 자리의 핀 결과. */
  function goToSlot(d1, d2 = '', d3 = '') {
    const b = treeBranch(d1);
    if (!b) return;
    const g = b.d2.find(x => x.id === d2) || b.d2.find(x => x.id === treeLastD2.get(d1)) || b.d2[0];
    treeAll = !d2;
    treeSel = { d1: b.id, d2: g?.id || '', d3: d2 && g?.d3.some(x => x.id === d3) ? d3 : '' };
    if (g) treeLastD2.set(b.id, g.id);
    rememberView();
    if (pins.length) { treeFilter = b.id; void explore(); } else void loadTree();
  }
  /** 고른 갈래 탭에 후보가 없으면 전체로(기존 화면의 widenEmptySelection 과 같은 규칙). */
  function widenTreeFilter(r) {
    if (!treeFilter || !r || r.status !== 'matched') return false;
    const counts = r.tree_counts?.d1 || [];
    const mine = counts.find(x => x.id === treeFilter);
    if (mine && mine.count) return false;
    const elsewhere = counts.some(x => x.count > 0);
    const label = mine?.ko || treeFilter;
    treeFilter = '';
    widenNote = elsewhere ? `${label} → 전체 (비어서 자동 전환)` : '';
    return elsewhere;
  }

  /** 고른 갈래·소분류에 후보가 **하나도 없으면 전체로 되돌린다**(사용자 지정 2026-09-18).
   *
   *  핀을 더할수록 좁아지다 보면 "고른 분류에만" 후보가 없는 자리에 닿는다. 거기서 빈 목록을
   *  보여 주면 사용자는 **조합 자체에 데이터가 없다**고 읽는다 - 실제로는 다른 갈래에 남아 있다.
   *  갈래별·소분류별 개수는 **갈래 필터를 걸기 전 풀**에서 나오므로(service `_pool`) 이 응답
   *  하나로 판정할 수 있다. 되돌린 뒤 다시 물어야 그 후보들이 실려 온다.
   *  ⚠️ 전체로 가도 빈 화면이면 되돌리지 않는다 - 그때는 정말로 후보가 없는 것이고,
   *     괜히 사용자가 고른 갈래만 잃는다.
   *  되돌린 자리는 `roles`/`subcategory` 가 이미 비어 있으니 두 번 돌 수 없다. */
  function widenEmptySelection(r) {
    if (!r || r.status !== 'matched') return false;
    const gid = roles.size === 1 ? [...roles][0] : '';
    const counts = Array.isArray(r.group_counts)
      ? new Map(r.group_counts.map(g => [g.id, Number(g.count) || 0])) : null;
    if (gid && counts && !counts.get(gid)) {
      const elsewhere = [...counts].some(([id, n]) => n > 0 && (id !== 'unsorted' || r.unclassified_available));
      roles.delete(gid); subcategory = '';
      widenNote = elsewhere ? `${roleLabel(gid)} → 전체 (비어서 자동 전환)` : '';
      return elsewhere;
    }
    if (subcategory) {
      const row = (r.subcategories || []).find(s => s.id === subcategory);
      if (!row || !row.count) {
        const label = row?.label || subcategory;
        subcategory = '';
        const elsewhere = (r.subcategory_total || 0) > 0;
        widenNote = elsewhere ? `${label} → 전체 (비어서 자동 전환)` : '';
        return elsewhere;
      }
    }
    return false;
  }

  async function explore(keepWidenNote = false) {
    if (!keepWidenNote) widenNote = '';
    if (pins.length < 2 && roles.has('unsorted')) { roles.delete('unsorted'); subcategory = ''; }
    if (eventLinked()) void syncRandomLink();
    moreRequest = null; moreError = '';
    active = -1;
    ++seq; // 핀이 전부 사라져도 이전 응답을 무효화한다.
    result = null;
    if (bodyEl) bodyEl.scrollTop = 0;
    samples = null;
    if (!pins.length) {
      result = null;
      if (isTree()) { void loadTree(); return; }
      if (group) { void loadBrowse(); return; }
      render(); return;
    }
    const mine = ++seq;
    if (isTree() && !treeMap) { await loadTreeMap(); if (mine !== seq) return; }
    setStatus('찾는 중…', 'busy');
    setBusy(true);
    try {
      const body = await getJson('/api/event-map/explore', {
        pins: pins.join(','), exclude: excludes.join(','), limit: CANDIDATE_LIMIT, sort: sortMode,
        relax: relaxOne && canRelax() ? 1 : 0, ...filterParams(), ...treeParams(),
      });
      if (mine !== seq) return;
      result = body;
    } catch (error) {
      if (mine !== seq) return;
      result = { status: 'error', message: error.message, code: error.code, candidates: [] };
    } finally { setBusy(false); }
    if (mine === seq && (isTree() ? widenTreeFilter(result) || (result?.status === 'matched' && treeFilter && !treeAll
        && choosePinnedSlot(treeFilter)) : widenEmptySelection(result))) { void explore(true); return; }
    render();
    // Open actual posts only when the whole candidate pool is exhausted,
    // not merely when the selected category has no candidates.
    const counts = isTree() ? result?.tree_counts?.d1 : result?.group_counts;
    if (mine === seq && open && result?.observed_posts > 0
        && Array.isArray(counts)
        && !counts.some(g => Number(g.count) > 0
          && (isTree() || g.id !== 'unsorted' || result.unclassified_available))) {
      void drawSamples();
    }
  }

  function currentCandidates() {
    if (!open || mapState?.state !== 'ready' || input?.value.trim()) return null;
    if (isTree()) return pins.length ? result : (['section', 'group_list', 'branch_list'].includes(treeData?.mode) ? treeData : null);
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
    let params = { limit: CANDIDATE_LIMIT, offset: source.next_offset, ...filterParams() };
    if (exploring) Object.assign(params, { pins: pins.join(','), exclude: excludes.join(','), sort: sortMode,
      relax: relaxOne && canRelax() ? 1 : 0 }, treeParams());
    else if (isTree()) params = { limit: CANDIDATE_LIMIT, offset: source.next_offset, ...treeFilterParams(),
      ...(treeAll ? { d1: treeSel.d1, flat: 1 } : treeSel.d3 ? { d2: treeSel.d2, d3: treeSel.d3 } : { d2: treeSel.d2, flat: 1 }) };
    else Object.assign(params, { group, groups: '' });
    const route = exploring ? 'explore' : (isTree() ? 'tree/browse' : 'browse');
    try {
      const page = await getJson(`/api/event-map/${route}`, params);
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
    if (!pins.length) { subcategory = ''; treeFilter = isTree() ? treeSel.d1 : ''; }
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
    // 꽂기와 같이 검색을 닫는다 - 글자가 남으면 결과가 와도 검색 목록만 그려 창이 멈춘 것처럼 보였다(사용자 제보 2026-10-14).
    input.value = ''; suggest = null; ++suggestSeq; clearTimeout(timer);
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
    if (isTree()) return;   // 그룹 · 절은 왼쪽 나무에서 고른다 - 핀이 없으면 돌아갈 단계가 없다
    if (group) { group = ''; browse = null; render(); }
  }
  function pickGroup(id) { subcategory = ''; group = id; browse = null; void loadBrowse(); }
  function clearExclude(tag) { excludes = excludes.filter(t => t !== tag); void explore(); }

  function currentPrompt() { return pins.join(', '); }
  const currentSelection = () => ({ pins: pins.slice(), exclude: excludes.slice(), ratings: [...ratings], persons: [...persons] });
  /** [넣기] = 랜덤 대치(사용자 지정 2026-09-13): 고른 핀을 Random 과 같은 파이프라인에 태워 메인 프롬프트를
   *  **갈아끼운다**(/api/event-map/apply). 전에는 커서 자리에 끼워 넣었다. 등급은 지금 고른 등급이 하나면 그것, 아니면 s. */
  /** [넣기] = 고른 핀으로 메인 프롬프트를 대치한다. [생성] = 같은 대치 뒤 Generate(사용자 지정 2026-10-08 -
   *  [랜덤+생성] · 실제 조합의 [적용+생성] 과 같은 길, applyThenGenerate). */
  async function applyPins(btn, andGenerate = false) {
    if (!pins.length) return;
    const rating = ratings.size === 1 ? [...ratings][0] : 's';
    if (btn) btn.disabled = true;
    try {
      if (andGenerate) {
        await applyThenGenerate(pins.slice(), rating);
        toast(`메인 프롬프트를 대치하고 생성을 눌렀습니다 — ${pins.join(', ').slice(0, 40)}`, 'success');
      } else {
        await postJson('/api/event-map/apply', { tags: pins.slice(), rating });
        toast(`메인 프롬프트를 대치했습니다 — ${pins.join(', ').slice(0, 40)}`, 'success');
      }
    } catch (error) {
      toast(`${andGenerate ? '생성' : '대치'} 실패 — ${error.message}`, 'error');
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
    if (tipOwner && (tipOwner.dataset.emPin || tipOwner.dataset.emTipTag) === tag) paintTip(tipOwner);
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
    const src = pins.length ? result : (isTree() ? treeData : browse);
    const total = Number(src?.observed_posts || 0);
    const inc = Number(row.dataset.emEst || 0);
    if (!total || !inc) return '';
    const approx = src?.sampled ? '≈' : '';
    return `<div class="em-tip-combo"><span>포함 <b>${approx}${fmt(inc)}</b></span><span>제외 <b>${approx}${fmt(Math.max(0, total - inc))}</b></span></div>
      <div class="em-tip-combo-note">${pins.length ? '핀 조합' : '이 분면'}의 게시물 ${fmt(total)}건 중</div>`;
  }
  function paintTip(row) {
    const tip = ensureTip();
    const tag = row.dataset.emPin || row.dataset.emTipTag || '';
    const returning = row.hasAttribute('data-em-goto');
    const info = tipInfo.get(tag);
    const axis = thumbAxis?.get(tag);
    const thumb = axis ? `<img class="em-tip-thumb" alt="" src="/api/interactive-thumb?axis=${encodeURIComponent(axis)}&tag=${encodeURIComponent(tag)}">` : '';
    tip.innerHTML = `<div class="em-tip-row">
      <div class="em-tip-main">
        <div class="em-tip-head"><span class="em-tip-tag">${esc(tag)}</span>${row.dataset.emPath ? ''
          : `<span class="em-tip-src">${esc(roleLabel(row.dataset.emG || info?.group || 'unsorted'))}</span>`}</div>
        ${row.dataset.emPath ? `<div class="em-tip-path">${esc(row.dataset.emPath)}</div>` : ''}
        ${info?.desc ? `<div class="em-tip-desc">${esc(info.desc)}</div>` : (info === undefined ? '<div class="em-tip-desc em-tip-wait">…</div>' : '')}
        <div class="em-tip-stats">${row.dataset.emLift ? `lift ${esc(row.dataset.emLift)} · ` : ''}${info?.count ? `Danbooru ${fmt(info.count)}` : ''}</div>
        <div class="em-tip-foot">${returning ? "" : tipComboLine(row)}<div class="em-tip-hint">${returning ? "이 단계로 돌아가기" : (simpleMode && row.classList.contains('emt-row') ? "단순 검색 모드 - [복사] · [삽입]" : "클릭 꽂기 · 우클릭 제외")}</div></div>
      </div>${thumb}</div>`;
    // 툴팁은 곁에 뜨는 창들(소분류 · 옆 패널 · 인원 팝업, 모두 overlay+1)보다 **한 칸 위**다. 같은 칸이면
    // body 에 나중에 붙은 쪽이 이겨, 창을 다시 열면 소분류 창이 툴팁을 덮었다(사용자 제보 2026-10-07).
    tip.style.zIndex = String(Number(overlay.style.zIndex) + 2);
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
    void askTipInfo(row.dataset.emPin || row.dataset.emTipTag || '');
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
        if (isTree() || pins.length) void explore();
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
  /** [삽입] - 마지막으로 초점이 있던 프롬프트 칸의 커서 자리에 ', 태그'(앞이 비었거나 쉼표로 끝나면 쉼표는 안 붙인다). */
  function insertOne(tag) {
    const done = typeof insertAtCursor === 'function' ? insertAtCursor(tag) : insertTag?.(tag);
    toast(done === false ? '프롬프트에 넣지 못했습니다.' : `프롬프트에 넣었습니다 — ${tag}`, done === false ? 'error' : 'success');
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
      + `<button type="button" class="em-crumb-go" data-em-goto="${i + 1}" data-em-tip-tag="${esc(tag)}" aria-label="${esc(tag)}: 이 단계로 돌아가기">${esc(tag)}</button>`
      + `<button type="button" class="em-crumb-x" data-em-unpin="${esc(tag)}" aria-label="${esc(tag)} 빼기">×</button></span>`)
      .join('<span class="em-sep">›</span>');
    const ex = excludes.map(tag =>
      `<button type="button" class="em-ex" data-em-unexclude="${esc(tag)}" title="제외 풀기">− ${esc(tag)}</button>`).join('');
    if (isTree() && !pins.length) { paintTreeTrail(ex); return; }
    const g = isTree() ? null : (group ? groupInfo(group) : null);
    const groupCrumb = g ? `<span class="em-crumb em-crumb-group em-g-${esc(group)}"><button type="button" class="em-crumb-go" data-em-group-back
        title="이 대분류의 목록으로">${esc(g.label)}</button></span>${crumbs ? '<span class="em-sep">›</span>' : ''}` : '';
    trailEl.innerHTML = `
      <button type="button" class="em-back" data-em-back ${(pins.length || group) ? '' : 'disabled'} title="한 단계 위로">←</button>
      <div class="em-crumbs">${groupCrumb}${crumbs || (group ? '' : '<span class="em-crumb-empty">대분류를 고르거나 태그를 찾아 시작합니다</span>')}${ex}</div>`;
    paintActions();
  }
  function groupInfo(id) { return (mapState?.groups || []).find(g => g.id === id) || null; }
  /** 핀이 없을 때의 3단 지도 부스러기: 갈래 › 그룹 › 절(지금 보고 있는 자리 - 고르기는 왼쪽 나무에서). */
  function paintTreeTrail(ex) {
    const b = treeBranch(treeSel.d1), g = treeAll ? null : treeGroupOf(treeSel.d2);
    const s = !treeAll && treeSel.d3 ? treeSectionOf(treeSel.d2, treeSel.d3) : null;
    const parts = [b && `<span class="emt-crumb">${esc(b.ko)}</span>`, g && `<span class="emt-crumb">${esc(g.ko)}</span>`,
      s && `<b class="emt-crumb">${esc(s.ko)}</b>`, (treeAll || (g && !s)) && b && '<b class="emt-crumb">전체</b>'].filter(Boolean);
    trailEl.innerHTML = `
      <button type="button" class="em-back" data-em-back disabled title="한 단계 위로">←</button>
      <div class="em-crumbs emt-crumbs">${parts.join('<span class="em-sep">›</span>')
        || `<span class="em-crumb-empty">${treeError ? '지도를 열지 못했습니다' : '지도를 여는 중…'}</span>`}${ex}</div>
      ${parts.length ? '<span class="em-note emt-hint">이 인원·등급에서 특징적인 순</span>' : ''}`;
    paintActions();
  }

  /** 고른 것을 한 번에 비운다: 핀 · 제외 · 소분류 · 대분류. 등급/인원은 **그대로 둔다**
   *  (그건 한 번 눌러 두는 취향이지, 하나씩 닫아야 하는 것이 아니다 - 사용자 지정 2026-09-13). */
  function resetSelection() {
    subcategory = '';
    pins = [];
    excludes = [];
    browse = null;
    samples = null;
    if (isTree()) { treeFilter = ''; void loadTree(); return; }
    void loadBrowse();
  }

  /** 동작 단추는 발줄 오른쪽에 산다 - 부스러기 줄에 두면 핀이 셋만 돼도 겹쳤다. */
  function paintActions() {
    if (!footEl) return;
    const on = pins.length > 0;
    // 넣기/복사/실제 조합 셋 다 조건 줄 오른쪽에 산다(사용자 지정 2026-09-12 밤 - 발줄에선 못 찾았다)
    overlay.querySelectorAll('[data-em-insert], [data-em-insert-generate], [data-em-copy]').forEach(b => { b.disabled = !on; });
    const sb = overlay.querySelector('[data-em-samples]');
    if (sb) { sb.disabled = !on; sb.classList.toggle('is-on', !!samples); }
    const rs = overlay.querySelector('[data-em-reset]');
    if (rs) rs.disabled = isTree() ? !(pins.length || excludes.length)
      : !(pins.length || excludes.length || subcategory || group);
    // [스테이징] - 핀이 있고 아직 스테이징에 없는 조합일 때만(이미 있으면 미리 끈다 - 사용자 지시 2026-10-14).
    const sg = overlay.querySelector('[data-emt-stage]');
    if (sg) {
      const staged = on && Boolean(isStaged?.(currentSelection()));
      sg.disabled = !on || staged;
      sg.title = staged ? '이미 스테이징에 있는 조합입니다' : '이 조합을 얼려 스테이징(S)에 넣는다 - 랜덤 버튼을 스테이징에 연결하면 그중 하나에서 뽑는다';
    }
    const so = overlay.querySelector('[data-emt-stage-open]');
    if (so) {
      const n = Number(getStagedCount?.()) || 0;
      so.hidden = !n;
      so.textContent = String(n);
    }
    // 3단 지도: 넣기 · 생성 · 복사 · 실제 조합은 발줄 오른쪽에, **핀이 있을 때만** 보인다(목업).
    if (actsEl) actsEl.hidden = !(isTree() && on);
  }

  const ACTION_BUTTONS = `<button type="button" data-em-insert disabled
              title="지금 고른 태그로 메인 프롬프트를 대치한다 (Random 과 같은 길)">넣기</button><button type="button" data-em-insert-generate disabled
              title="지금 고른 태그로 메인 프롬프트를 대치한 뒤 바로 Generate">생성</button><button type="button" data-em-copy disabled
              title="지금 고른 태그 전부를 클립보드로">복사</button><button type="button" data-em-samples disabled
              title="핀을 전부 포함하는 실제 게시물의 조합">실제 조합</button>`;
  function filterHeadHtml() {
    return `
      <button type="button" class="em-person-btn" data-em-person aria-haspopup="dialog" aria-expanded="false"
              title="인원 구성 고르기"><b data-em-person-count></b></button>
      <span class="em-rating-bar" role="group" aria-label="등급">${RATING_OPTIONS.map(r =>
        `<button type="button" class="em-rating-btn${ratings.has(r.id) ? ' active' : ''}" data-em-r="${r.id}"
                 aria-pressed="${ratings.has(r.id)}" title="${r.title}">${r.label}</button>`).join('')}</span>`;
  }
  /** 3단 지도의 조건 줄: 인원 · 등급 · [초기화] · [영구 제외] · [⋯]. PE설정 · 조합 저장/불러오기는 [⋯] 안으로,
   *  넣기 · 생성 · 복사 · 실제 조합은 발줄로(목업 승인 2026-10-14). */
  function paintTreeFilters() {
    // [초기화] 는 자주 누른다 - [⋯] 에서 꺼내 등급 오른쪽에 둔다(사용자 지시 2026-10-14, 기존 화면과 같은 자리).
    filtersEl.innerHTML = `${filterHeadHtml()}
      <button type="button" class="em-reset" data-em-reset
              title="핀 · 제외를 한 번에 비우고 지도로 돌아간다">초기화</button>
      <button type="button" class="em-reset emt-perm-btn" data-emt-perm aria-expanded="false"
              title="영구 제외 - 이 태그가 달린 게시물은 이벤트 맵이 세지 않는다(Search 의 영구 제외와 같은 목록)">영구 제외</button>
      <button type="button" class="em-reset emt-menu-btn" data-emt-menu aria-haspopup="menu" aria-expanded="false"
              title="PE설정 · 조합 저장/불러오기">⋯</button>`;
    personBtn = filtersEl.querySelector('[data-em-person]');
    paintPersonButton();
    paintPermanent();
    paintActions();
  }
  function paintFilters() {
    if (actsEl) actsEl.innerHTML = isTree() ? ACTION_BUTTONS : '';
    if (isTree()) { paintTreeFilters(); return; }
    filtersEl.innerHTML = `${filterHeadHtml()}
      <button type="button" class="em-reset" data-em-reset
              title="핀 · 제외 · 소분류를 한 번에 비우고 대분류로 돌아간다">초기화</button>
      <button type="button" class="em-reset em-pe" data-em-pe-settings
              title="Prompt Engineering — prefix · postfix · autohide · 옵션 (메인 프롬프트의 /pe 와 같은 목록)">PE설정</button>
      <span class="em-actions em-actions-right">${ACTION_BUTTONS}</span>`;
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

  function rowNumbers(c) {
    const lift = Number(c.lift || 0);
    const liftText = lift >= 100 ? `×${Math.round(lift)}` : `×${lift.toFixed(lift >= 10 ? 0 : 1)}`;
    const obs = c.observed_estimate != null && c.observed_estimate !== c.observed
      ? `≈${fmt(c.observed_estimate)}` : fmt(c.observed);
    const est = c.observed_estimate != null ? c.observed_estimate : c.observed;
    return { liftText, obs, est };
  }
  /** 3단 지도의 줄. 핀 결과에서는 줄 아래에 경로(갈래 › 그룹 › 절)를 적는다 - 기존 화면의 색 대신. */
  function treeRow(c, i, path = '', showPath = false) {
    const { liftText, obs, est } = rowNumbers(c);
    const where = c.path?.ko || path;
    const here = treeFilter || treeSel.d1;
    // 경로 조각마다 자리(갈래 · 그룹 · 절) - 누르면 그리로 간다. 보고 있는 갈래 · 그룹 이름은 뗀다.
    const ids = c.path ? [c.path.d1, c.path.d2, c.path.d3] : [];
    let parts = String(where || '').split(' › ').map((ko, level) => ({ ko, level }));
    if (c.path && c.path.d1 === here) {
      parts = parts.slice(1);
      if (!treeAll && c.path.d2 === treeSel.d2) parts = parts.slice(1);
    }
    const link = p => {
      if (!c.path || !ids[p.level]) return `<span>${esc(p.ko)}</span>`;
      const at = `data-emt-go-d1="${esc(ids[0])}"${p.level >= 1 ? ` data-emt-go-d2="${esc(ids[1])}"` : ''}${p.level >= 2 ? ` data-emt-go-d3="${esc(ids[2])}"` : ''}`;
      const what = ['갈래 전체', '그룹 전체', '절'][p.level];
      return `<button type="button" class="emt-go" data-emt-go ${at} title="${esc(p.ko)} - ${what}로 가기">${esc(p.ko)}</button>`;
    };
    const shown = parts.map(link).join('<span class="emt-go-sep">›</span>');
    return `<div class="em-row emt-row${i === active ? ' is-active' : ''}" data-em-row="${i}" data-em-pin="${esc(c.tag)}"
        data-em-est="${Number(est) || 0}" data-em-lift="${liftText}"${where ? ` data-em-path="${esc(where)}"` : ''} role="option">
      <span class="em-tag">${esc(c.tag)}</span>
      ${simpleMode ? `<span class="emt-quick"><button type="button" data-emt-copy="${esc(c.tag)}" title="이 태그를 클립보드로">복사</button><button type="button" data-emt-insert="${esc(c.tag)}" title="프롬프트 커서 자리에 ', 태그'">삽입</button></span>`
        : `<span class="em-lift">${liftText}</span>`}
      <span class="em-obs">${obs}</span>
      <button type="button" class="em-row-x" data-em-exclude="${esc(c.tag)}" title="이 태그가 없는 게시물만">−</button>
      ${showPath && shown ? `<span class="emt-path">${shown}</span>` : ''}
    </div>`;
  }
  /** 핀이 없을 때의 3단 지도: 왼쪽 = 나무(갈래의 그룹 · 고른 그룹 아래로 그 절), 오른쪽 = 고른 절의 태그 전부.
   *  나무는 지도 골격(/tree)으로 그린다 - 서버 응답을 기다리지 않는다. 절마다 이 조건의 후보 수는 절 응답이
   *  같은 그룹 것을 함께 실어 온다(`sections[].live`). 0 이면 흐리게. */
  function treeBodyHtml() {
    if (!treeMap) {
      return `<div class="em-empty">${treeError
        ? `3단 지도를 열지 못했습니다 — ${esc(treeError)}<br>머리줄의 <b>기존</b> 으로 바꾸면 예전 화면을 씁니다.` : '지도를 여는 중…'}</div>`;
    }
    const b = treeBranch(treeSel.d1);
    if (!b) return '<div class="em-empty">지도가 비었습니다</div>';
    const live = treeData?.d2 === treeSel.d2 && Array.isArray(treeData.sections)
      ? new Map(treeData.sections.map(r => [r.id, r.live])) : null;
    const groupLive = g => (treeData?.mode === 'group_list' && treeData.d2 === g.id ? treeData.candidate_pool : null);
    return `<div class="emt-grid">${treeNavHtml(b, null, x => live?.get(x.id), null, groupLive)}
      <div class="emt-right">${treeRightHtml()}</div></div>`;
  }
  /** 왼쪽 나무. 펼치는 것은 고른 그룹 하나다.
   *  · 핀이 없을 때(`pinned` = null): 그룹 = 태그 수, 절 = `이 조건의 후보 / 태그 수`(0 이면 흐리게).
   *  · 핀 화면(`pinned` = 그룹 id -> 후보 수): 그룹 · 절 = 핀과 함께 달린 후보 수, **0 은 숨긴다**(사용자 결정). */
  function treeNavHtml(b, pinned, sectionCount, allCount = null, groupLive = null) {
    const all = `<button type="button" class="emt-d2 emt-all${treeAll ? ' is-on' : ''}" data-emt-all aria-pressed="${treeAll}"
      title="${esc(b.ko)} 의 태그 전부 - 그룹 · 절을 가리지 않고 한 줄로"><span><i class="emt-caret">≡</i>전체</span>${allCount != null ? `<small>${fmt(allCount)}</small>` : ''}</button>`;
    const items = b.d2.map(g => {
      const gn = pinned ? (pinned[g.id] || 0) : g.tags;
      if (pinned && !gn) return '';
      const openGroup = !treeAll && g.id === treeSel.d2;
      const head = `<button type="button" class="emt-d2${openGroup ? ' is-open' : ''}" data-emt-d2="${esc(g.id)}"
        aria-expanded="${openGroup}" title="${esc(g.ko)} 전부 보기 · ${pinned ? `핀과 함께 달린 후보 ${fmt(gn)}` : `절 ${g.d3.length}개 · 태그 ${fmt(g.tags)}`}"><span><i class="emt-caret">${openGroup ? '▾' : '▸'}</i>${esc(g.ko)}</span><small>${fmt(gn)}</small></button>`;
      if (!openGroup) return head;
      const groupAllOn = !treeSel.d3;
      const gl = groupLive?.(g);
      const groupAll = `<button type="button" class="emt-d3i emt-gall${groupAllOn ? ' is-on' : ''}" data-emt-gall aria-pressed="${groupAllOn}"
        title="${esc(g.ko)} 의 태그 전부 - 절을 가리지 않고 한 줄로"><span>전체</span><small>${pinned ? fmt(gn) : `${gl != null ? `${fmt(gl)} / ` : ''}${fmt(g.tags)}`}</small></button>`;
      return head + groupAll + g.d3.map(x => {
        const n = sectionCount(x, g);
        if (pinned && !n) return '';
        const on = x.id === treeSel.d3;
        const empty = !pinned && n === 0;
        const label = pinned ? fmt(n) : `${n != null ? `${fmt(n)} / ` : ''}${fmt(x.tags)}`;
        return `<button type="button" class="emt-d3i${on ? ' is-on' : ''}${empty ? ' is-empty' : ''}" data-emt-d3="${esc(x.id)}"
          aria-pressed="${on}" title="${esc(x.ko)}${empty ? ' · 이 인원·등급에 없음' : ''}"><span>${esc(x.ko)}</span><small>${label}</small></button>`;
      }).join('');
    }).join('');
    return `<nav class="emt-left" aria-label="${esc(b.ko)} 그룹 · 절">${all}${items}</nav>`;
  }
  /** 핀 화면의 갈래 탭: 왼쪽 나무(빈 그룹 · 절은 숨김) + 오른쪽 고른 절의 후보(정렬 · -1 허용 · 더 보기 그대로). */
  function pinnedTreeHtml(cs) {
    const b = treeBranch(treeFilter);
    const counts = result?.tree_counts || {};
    if (!b || !counts.d2) return '';
    const x = treeAll ? null : treeSectionOf(treeSel.d2, treeSel.d3);
    const n = x ? (counts.d3?.[`${treeSel.d2}\t${x.id}`] || 0) : 0;
    const d1n = (counts.d1 || []).find(r => r.id === b.id)?.count || 0;
    const g = treeAll ? null : treeGroupOf(treeSel.d2);
    const head = treeAll ? `<div class="emt-d3h"><span>${esc(b.ko)} 전체</span><small>후보 ${fmt(d1n)}</small></div>`
      : x ? `<div class="emt-d3h"><span>${esc(x.ko)}</span><small>후보 ${fmt(n)}</small></div>`
      : g ? `<div class="emt-d3h"><span>${esc(g.ko)} 전체</span><small>후보 ${fmt(counts.d2?.[g.id] || 0)}</small></div>` : '';
    const right = head
      + candidateCapHtml(result, cs.length)
      + (cs.length ? cs.map((c, i) => treeRow(c, i, '', !x)).join('')
        : `<div class="em-empty">${floorPhrase(result, '이 절에 함께 달린 태그가 없습니다.')}</div>`)
      + moreHtml();
    return `<div class="emt-grid">${treeNavHtml(b, counts.d2, (r, g) => counts.d3?.[`${g.id}\t${r.id}`] || 0, d1n)}
      <div class="emt-right">${right}</div></div>`;
  }
  /** 나무를 다시 그려도 스크롤 자리를 지키고, 펼친 그룹(머리 + 절)이 칸 밖이면 보이게 민다 - 아래쪽 그룹을 펼치면
   *  절이 칸 아래로 숨었다(라이브 확인 2026-10-14). 머리가 위로 밀려나지 않는 만큼만 내린다. */
  function keepTreeInView(prev) {
    const nav = bodyEl.querySelector('.emt-left');
    if (!nav) return;
    nav.scrollTop = prev;
    const head = nav.querySelector('.emt-d2.is-open');
    if (!head) return;
    const items = nav.querySelectorAll('.emt-d3i');
    const last = items[items.length - 1] || head;
    const box = nav.getBoundingClientRect(), top = head.getBoundingClientRect().top, bottom = last.getBoundingClientRect().bottom;
    if (top < box.top) nav.scrollTop -= box.top - top;
    else if (bottom > box.bottom) nav.scrollTop += Math.min(bottom - box.bottom, top - box.top);
  }
  function treeRightHtml() {
    const d = treeData;
    if (!d) return '<div class="em-empty">불러오는 중…</div>';
    if (d.status === 'error') {
      setStatus('오류', 'error');
      return `<div class="emt-error"><span>${esc(d.message || '실패')}</span>
        <button type="button" class="em-mini" data-emt-retry>다시 시도</button></div>`;
    }
    setStatus(`${fmt(d.observed_posts)}건${d.sampled ? ' · 표본' : ''}`, 'ok',
      `${Math.round(d.elapsed_ms || 0)}ms · 이 분면에서의 비율 ÷ 코퍼스 전체에서의 비율`);
    const cs = d.candidates || [];
    rows = cs.map(c => c.tag);
    const path = (d.path || []).join(' › ');
    const flat = d.mode === 'branch_list' || d.mode === 'group_list';
    const title = flat ? `${(d.path || []).slice(-1)[0] || ''} 전체` : (d.path || [])[2] || treeSel.d3;
    return `<div class="emt-d3h"><span>${esc(title)}</span>
        <small>${fmt(d.candidate_pool ?? cs.length)} / ${fmt(d.tags)}</small></div>`
      + (cs.length ? cs.map((c, i) => treeRow(c, i, path, flat)).join('')
        : `<div class="em-empty">이 인원·등급에 ${floorPhrase(d, '나온 태그가 없습니다.')}</div>`)
      + moreHtml();
  }
  /** 갈래 탭. 핀이 없으면 = 갈래 바꾸기, 핀이 있으면 = 후보 필터(갈래별 후보 수 · 0 이면 흐림). */
  function paintTreeTabs() {
    if (!ttabsEl) return;
    const show = isTree() && open && mapState?.state === 'ready' && !input?.value.trim() && !!treeMap;
    ttabsEl.hidden = !show;
    if (!show) { ttabsEl.innerHTML = ''; return; }
    const pinned = pins.length > 0;
    const counts = pinned && Array.isArray(result?.tree_counts?.d1)
      ? new Map(result.tree_counts.d1.map(r => [r.id, Number(r.count) || 0])) : null;
    const tab = (id, label, n, on) => {
      const empty = counts != null && id && !n;
      return `<button type="button" class="em-cat emt-tab${on ? ' is-on' : ''}${empty ? ' is-empty' : ''}" data-emt-d1="${esc(id)}"
        role="tab" aria-selected="${on}" ${empty ? 'disabled' : ''}><span class="em-tag">${esc(label)}</span>${n != null ? `<span class="em-cat-n">${fmt(n)}</span>` : ''}</button>`;
    };
    ttabsEl.innerHTML = (pinned ? tab('', '전체', null, !treeFilter) : '')
      + treeMap.d1.map(b => tab(b.id, b.ko, counts ? (counts.get(b.id) || 0) : null,
        pinned ? b.id === treeFilter : b.id === treeSel.d1)).join('')
      + `<label class="emt-simple" title="켜면 줄을 눌러도 핀을 꽂지 않는다 - 고른 인원 · 등급의 태그를 보기만 하고 [복사] · [삽입] 으로 쓴다">
          <input type="checkbox" data-emt-simple ${simpleMode ? 'checked' : ''}>단순 검색 모드</label>`;
  }

  function candidateRow(c, i) {
    const unclassified = c.group === 'unsorted';
    const { liftText, obs, est } = rowNumbers(c);
    return `<div class="em-row em-g-${esc(c.group || 'unsorted')}${unclassified ? ' em-row-unclassified' : ''}${i === active ? ' is-active' : ''}" data-em-row="${i}" data-em-pin="${esc(c.tag)}"
        data-em-g="${esc(c.group || 'unsorted')}" data-em-est="${Number(est) || 0}" data-em-lift="${liftText}" role="option">
      <span class="em-tag">${esc(c.tag)}</span>
      <span class="em-lift">${liftText}</span>
      <span class="em-obs${unclassified ? ' em-obs-detail' : ''}">${unclassified ? `함께 ${obs}건<small>전체 ${fmt(c.observed_total)}건</small>` : obs}</span>
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
    return `<div class="em-cap"><span class="em-cap-label">검색</span>${suggest.translated?.length ? '<span class="em-note">한글 검색 · 관련도 순</span>' : ''}</div>
      ${items.map(it => {
        const usable = !it.blocked && !pins.includes(it.tag);
        const i = usable ? k++ : -1;
        return `<div class="em-row em-g-${esc(it.group || 'unsorted')}${usable ? '' : ' is-off'}${i === active ? ' is-active' : ''}" data-em-g="${esc(it.group || 'unsorted')}" ${usable ? `data-em-row="${i}" data-em-pin="${esc(it.tag)}"` : ''} role="option">
          <span class="em-tag">${esc(it.tag)}</span>
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
      + `<div class="em-cap">${esc(roleLabel(group))} <span class="em-note">이 인원·등급에서 특징적인 순 · ${cs.length}개${widenNote ? ` · ${esc(widenNote)}` : ''}</span></div>`
      + (cs.length ? cs.map(candidateRow).join('') : `<div class="em-empty">이 분면에 ${floorPhrase(browse, '나온 태그가 없습니다.')}</div>`);
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
            `<span class="${peHidden.has(t) ? 'em-pe-hidden ' : ''}${pins.includes(t) ? 'em-query-tag' : ''}"${peHidden.has(t) ? ` title="${esc(peTitle(t).slice(3))}"` : ''}>${esc(t)}</span>`).join(', ')}</div>
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
    if (isTree() || roles.has('unsorted')) return '';
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
      if (subEl.parentElement !== panel.body) panel.body.insertBefore(subEl, bodyEl);
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
    // ⚠️ 접힌 동안 소분류 레일은 CSS 로 숨는다(`hidden` 은 그대로) - 그때 레일의 상자는 0 이라, 그 오른쪽에 붙이면
    //    실제 조합 창이 화면 왼쪽 끝으로 튄다. 접혀 있으면 레일이 없는 것으로 본다.
    const railRight = subEl && !subEl.hidden && !subEl.classList.contains('is-inline') && !panel?.isCollapsed()
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

  /** 핀이 둘 이상이어야 '하나 빼기' 가 뜻이 있다. */
  function canRelax() { return pins.length >= 2; }

  /** 후보 문턱은 **교집합이 작으면 백엔드가 낮춘다**(1~5건). 그러니 문구에 숫자를 박지 말고
   *  응답이 말한 값을 쓴다 - 5로 박아 두면 "5건 이상 없습니다" 가 거짓말이 된다. */
  function floorOf(r) { return Math.max(1, Number(r?.min_posts) || 5); }
  function floorPhrase(r, tail) { const n = floorOf(r); return n > 1 ? `${n}건 이상 ${tail}` : tail; }

  /** 후보 목록 머리줄: [정렬 ▾] 개수·완화 안내 [-1 허용]. **0건일 때도 그린다** - 넓히는 단추가
   *  거기 있어야 한다(사용자 제보 2026-09-13). */
  function candidateCapHtml(result, count) {
    const sm = SORT_MODES.find(m => m.id === sortMode) || SORT_MODES[0];
    const relaxNote = result.relaxed
      ? ` · ${pins.length - 1}/${pins.length} 일치 · 정확 ${fmt(result.strict_posts || 0)}건` : '';
    return `<div class="em-cap"><span class="em-cap-label">함께 달린 태그</span> <button type="button" class="em-sort" data-em-sort title="${esc(sm.title)} · 눌러서 바꾸기">${esc(sm.label)} ▾</button>`
      + `<span class="em-note">${count}개${result.sampled ? ' · 표본으로 셈' : ''}${relaxNote}${widenNote ? ` · ${esc(widenNote)}` : ''}</span>`
      + `<button type="button" class="em-relax${relaxOne ? ' is-on' : ''}" data-em-relax aria-pressed="${relaxOne}" ${canRelax() ? '' : 'disabled'} title="핀 ${pins.length}개 중 ${Math.max(1, pins.length - 1)}개만 있는 게시물까지 센다 - 정확한 교집합이 쪼그라들 때">-1 허용</button></div>`;
  }

  function render(preserveScroll = false) {
    if (!overlay) return;
    const scrollTop = bodyEl.scrollTop;
    hideTip();                      // 행이 다시 그려지면 주인이 사라진다 - 유령 툴팁을 막는다
    library?.update();
    paintTrail();
    paintFilters();
    paintTreeTabs();
    rows = [];
    let html = '';
    let treeBody = false;
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
      rows = (suggest?.items || []).filter(it => !it.blocked && !pins.includes(it.tag)).map(it => it.tag);
      // ⭐ 친 글자와 **정확히 같은** 태그가 있으면 그 줄을 미리 짚는다(사용자 제보
      //    2026-09-19: `pig` 를 치고 Enter 를 누르면 `pigeon-toed` 가 꽂혔다).
      //    목록은 게시물 수 순이라 정확히 맞는 것이 맨 위에 있으리란 보장이 없다 -
      //    `pigeon-toed` 10,575 > `pig` 3,286 이었다.
      // ⚠️ 사용자가 ↑↓ 로 고른 줄이 있으면 건드리지 않는다(그쪽이 더 분명한 뜻이다).
      // ⚠️ **`suggestHtml()` 보다 먼저** 정해야 한다 - 그 함수가 `active` 를 읽어
      //    `is-active` 를 박는다. 뒤에 정하면 값은 맞는데 화면에는 안 보인다.
      if (active < 0) active = exactRowIndex();
      html += suggestHtml();
      // 이 갈래는 상태 글을 안 쓴다 - 검색 중에 다시 찾은(조건 칩 · 제외) 요청이 끝났으면 '찾는 중…' 을 걷는다.
      if (!busyCount && statusEl?.classList.contains('is-busy')) {
        const n = pins.length && result?.status === 'matched' ? Number(result.observed_posts) || 0 : 0;
        setStatus(n ? `${fmt(n)}건` : '', n ? 'ok' : '');
      }
    } else if (!pins.length && isTree()) {
      html += treeBodyHtml();
      treeBody = true;
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
        // ⚠️ 0건이야말로 [-1 허용] 이 필요한 자리다 - 캡 줄을 같이 그린다(사용자 제보 2026-09-13).
        html += candidateCapHtml(result, 0);
        html += `<div class="em-empty">이 조합으로 달린 게시물이 없습니다. ${canRelax() && !relaxOne
          ? '위의 <b>-1 허용</b> 을 켜면 핀 하나를 뺀 조합까지 봅니다.' : '← 로 한 단계 올라가 보세요.'}</div>`;
        setStatus('0건', 'error');
      } else {
        const cs = result.candidates || [];
        rows = cs.map(c => c.tag);
        const gc = result.group_counts || null;   // 옛 백엔드(재시작 전)는 이 키가 없다 - 그래도 탭은 그린다
        // 3단 지도에서는 갈래 탭(ttabsEl)이 후보 필터다 - 대분류 탭 · 미분류 입구는 기존 화면의 것.
        if (!isTree()) html += catsHtml(gc, roles.size ? [...roles][0] : '', gc ? gc.reduce((n, r) => n + (r.id === 'unsorted' ? 0 : r.count), 0) : null);
        if (!isTree() && result.unclassified_available && result.unclassified_count > 0) {
          const expanded = roles.has('unsorted');
          html += `<div class="em-unclassified"><button type="button" class="em-mini" data-em-unclassified aria-expanded="${expanded}">${expanded ? '▾ 미분류 후보 접기' : '▸ 미분류 후보 더 보기'} · ${fmt(result.unclassified_count)}</button>${expanded
            ? `<span class="em-note">${result.sampled ? '표본 집계 · 범위를 좁히면 전체 집계' : '전체 집계'}${floorOf(result) > 1 ? ` · ${floorOf(result)}건 이상 함께 등장` : ''} · 분류 검토 중</span>` : ''}</div>`;
        }
        const pinnedTree = isTree() && treeFilter ? pinnedTreeHtml(cs) : '';
        if (pinnedTree) { html += pinnedTree; treeBody = true; }
        else {
          html += candidateCapHtml(result, cs.length);
          html += cs.length ? cs.map((c, i) => (isTree() ? treeRow(c, i, '', true) : candidateRow(c, i))).join('') : `<div class="em-empty">${!isTree() && result.unclassified_count > 0 && !roles.has('unsorted')
            ? (result.unclassified_available ? '분류된 후보가 없습니다. 미분류 후보 또는 실제 조합을 확인하세요.' : '분류된 후보가 없습니다. 실제 조합을 확인하세요.') : floorPhrase(result, '함께 달린 태그가 없습니다.')}</div>`;
        }
        setStatus(`${fmt(result.observed_posts)}건${result.sampled ? ' · 표본' : ''}`, 'ok',
          `${Math.round(result.elapsed_ms || 0)}ms${result.sampled ? ' · 교집합이 커서 표본으로 셌다(건수는 정확하다)' : ''}`);
      }
    }
    const navTop = bodyEl.querySelector('.emt-left')?.scrollTop || 0;
    bodyEl.innerHTML = treeBody ? html : html + moreHtml();   // 3단 지도의 [더 보기] 는 오른쪽 칸 안에 있다
    if (treeBody) keepTreeInView(navTop);
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
    popup.style.zIndex = String(Number(overlay.style.zIndex) + 1);
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


  // ── 3단 지도: [⋯] 메뉴 · 버전 토글 ────────────────────────────────────────
  function openTreeMenu(btn) {
    if (!menuEl) {
      menuEl = document.createElement('div');
      menuEl.className = 'emt-menu';
      menuEl.hidden = true;
      menuEl.setAttribute('role', 'menu');
      document.body.append(menuEl);
      menuEl.addEventListener('click', event => {
        const item = event.target.closest('[data-emt-act]');
        if (!item || item.disabled) return;
        const act = item.dataset.emtAct;
        closeTreeMenu();
        if (act === 'pe') openPeSettings();
        // 저장/불러오기는 기존 저장 줄의 단추를 그대로 누른다 - 저장 패널은 하나다(줄은 3단 지도에서 숨는다).
        else overlay.querySelector(`.em-library-bar [data-library-mode="${act}"]`)?.click();
      });
    }
    menuEl.innerHTML = `
      <button type="button" role="menuitem" data-emt-act="pe">PE설정<small>메인 프롬프트의 /pe 와 같은 목록</small></button>
      <button type="button" role="menuitem" data-emt-act="save" ${pins.length ? '' : 'disabled'}>이 조합 저장하기</button>
      <button type="button" role="menuitem" data-emt-act="load">저장된 조합 (S)</button>`;
    menuEl.hidden = false;
    menuEl.style.zIndex = String(Number(overlay.style.zIndex) + 1);
    btn.setAttribute('aria-expanded', 'true');
    const r = btn.getBoundingClientRect(), m = menuEl.getBoundingClientRect();
    const left = Math.max(8, Math.min(r.right - m.width, window.innerWidth - m.width - 8));
    let top = r.bottom + 4;
    if (top + m.height > window.innerHeight - 8) top = Math.max(8, r.top - m.height - 4);
    menuEl.style.left = `${Math.round(left)}px`;
    menuEl.style.top = `${Math.round(top)}px`;
    document.addEventListener('pointerdown', onMenuOutside, true);
  }
  function closeTreeMenu() {
    if (!menuEl || menuEl.hidden) return;
    menuEl.hidden = true;
    filtersEl?.querySelector('[data-emt-menu]')?.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', onMenuOutside, true);
  }
  function onMenuOutside(event) {
    if (menuEl?.contains(event.target) || event.target.closest?.('[data-emt-menu]')) return;
    closeTreeMenu();
  }
  function paintViewToggle() {
    if (!panel?.slot) return;
    const views = [['tree', '3단 지도', 'Danbooru 위키 tag_groups 를 다듬은 갈래 › 그룹 › 절 지도'],
      ['classic', '기존', '대분류 · 소분류 화면']];
    panel.slot.innerHTML = `<span class="emt-seg" role="group" aria-label="화면 버전">${views.map(([id, label, title]) =>
      `<button type="button" data-em-view="${id}" class="${viewMode === id ? 'is-on' : ''}" aria-pressed="${viewMode === id}"
        title="${esc(title)}">${label}</button>`).join('')}</span>`;
    overlay?.classList.toggle('em-tree', isTree());
  }
  /** 버전을 바꾼다. 핀 · 제외 · 인원 · 등급은 그대로 - 핀이 있으면 그 핀으로 새 화면에서 다시 묻는다. */
  function setViewMode(mode) {
    if (mode === viewMode || (mode !== 'tree' && mode !== 'classic')) return;
    viewMode = mode;
    rememberView();
    closeTreeMenu(); closePersonPopup(); hideTip();
    if (permOpen) openPermanent(false);
    if (library?.isOpen()) library.close();
    samples = null; widenNote = ''; result = null; browse = null; treeData = null;
    treeFilter = isTree() && pins.length ? treeSel.d1 : '';
    paintViewToggle();
    if (mapState?.state !== 'ready' || input.value.trim()) { render(); return; }
    void explore();
  }

  // ── 창 ───────────────────────────────────────────────────────────────────
  function build() {
    if (overlay) return overlay;
    panel = createDraggablePanel({
      document, window, id: 'eventMapWindow', title: '이벤트 맵',
      variant: 'em-overlay em-window', storageKey: 'event-map',
      width: EM_BASE_WIDTH, height: EM_BASE_HEIGHT, minWidth: EM_BASE_WIDTH, minHeight: EM_MIN_HEIGHT, maxWidth: 1000,
      initial: {x: 16, y: 64}, resizable: true,
      // 접기(머리줄 더블클릭 · [–])는 다른 떠 있는 창과 같다. 다만 접혀도 **검색 줄 · 부스러기 줄 · 조건 줄 · 랜덤
      // 발줄은 남긴다**(사용자 지정 2026-10-08 · 10-11) - 접은 채로 고른 태그를 보고 넣기 · 생성 · [랜덤] 을 누를 수
      // 있다. 무엇을 남기는지는 style.css 의 `.em-window.is-collapsed` 짝 규칙이 정한다.
      onCollapse: syncCollapsed,
      onClose: close, onMove: () => { closePersonPopup(); closeTreeMenu(); hideTip(); fitHeight(); },
    });
    overlay = panel.el;
    overlay.setAttribute('aria-label', '이벤트 맵');
    // 맨 위 = **얇은 핸들 줄**(창의 머리줄: 점 여섯 · 작은 이름 · ×), 그 아래가 검색 줄이다(사용자 지정
    // 2026-10-06: "위에 핸들 영역을 하나 더 붙이고, 태그 찾기를 한 칸 내립시다"). 검색 줄을 머리줄에 합쳐 두면
    // 잡을 자리가 검색 칸과 상태 글 사이의 틈뿐이라 창을 끌기 어렵다. 핸들 줄은 통째로 손잡이다 -
    // 두껍게 두지 않는다(공용 창의 기본 제목줄을 그대로 쓰면 머리가 두 겹으로 무거워진다: CSS 의 `.em-window`).
    panel.body.innerHTML = `
      <div class="em-bar">
        <span class="em-icon" aria-hidden="true">E</span>
        <input class="em-input" type="search" autocomplete="off" spellcheck="false"
               aria-label="태그 찾기" placeholder="태그 찾기…">
        <!-- [스테이징] = 건수 바로 왼쪽(사용자 지시 2026-10-14 - 지금 보이는 조합을 얼린다는 것이 건수 곁에서 바로 읽힌다).
             3단 지도 · 기존 두 화면 모두. 켜짐은 paintActions 가 정한다(핀이 있고 아직 스테이징에 없는 조합일 때만). -->
        <button type="button" class="em-reset emt-stage-btn" data-emt-stage disabled
                title="이 조합을 얼려 스테이징(S)에 넣는다 - 랜덤 버튼을 스테이징에 연결하면 그중 하나에서 뽑는다">스테이징</button>
        <!-- 스테이징 수 = 스테이징 창 열기. 스테이징이 있으면 늘 누를 수 있다(S 단추를 숨겨도 여기서 연다 - 사용자 지시 2026-10-14). -->
        <button type="button" class="emt-stage-count" data-emt-stage-open hidden
                title="스테이징된 조합 - 눌러서 스테이징 창 열기"></button>
        <span class="em-status" role="status" aria-live="polite"></span>
      </div>
      <div class="emt-perm" hidden>
        <span class="em-icon emt-perm-icon" aria-hidden="true">−</span>
        <input class="em-input emt-perm-input" type="text" autocomplete="off" spellcheck="false"
               aria-label="영구 제외에 더할 태그" placeholder="영구 제외에 더할 태그 - 치면 고를 태그가 뜬다">
        <span class="em-status emt-perm-status" role="status"></span>
        <button type="button" class="em-mini emt-perm-detail" data-emt-perm-detail title="영구 제외 태그를 칩으로 보고 지운다">상세 보기</button>
      </div>
      <div class="em-trail"></div>
      <div class="em-filters"></div>
      <div class="em-cats emt-tabs" role="tablist" aria-label="갈래" hidden></div>
      <div class="em-library-bar"><button type="button" data-library-mode="save" aria-expanded="false">이 조합 저장하기</button><button type="button" data-library-mode="load" aria-expanded="false">조합 불러오기</button></div>
      <div class="em-library-panel" hidden></div>
      <div class="em-body" role="listbox"></div>
      <div class="em-foot">
        <span class="em-actions"><button type="button" class="em-random" data-em-random="select"
            title="지금 고른 인원·등급(핀이 있으면 그 안)에서 게시물 하나를 뽑아 Random 과 같은 파이프라인으로 메인 프롬프트에">랜덤 선택</button><button type="button" class="em-random" data-em-random="generate"
            title="랜덤 선택 뒤 바로 Generate">랜덤+생성</button></span>
        <span class="em-keys" title="↑↓ 이동 · Enter 꽂기 · − 제외 · Esc 닫기">우클릭 = 제외</span>
        <label class="em-random-link" title="메인 Random과 Auto Gen이 현재 핀·제외·인원·등급을 사용합니다. 패널을 닫아도 연결됩니다."><input type="checkbox" data-em-random-link><span class="em-link-long">랜덤 버튼 </span>연결</label>
        <span class="em-actions emt-acts" hidden></span>
      </div>`;
    busyEl = document.createElement('div');
    busyEl.className = 'em-busy';
    busyEl.innerHTML = '<span class="em-busy-label">찾는 중…</span>';
    busyEl.addEventListener('pointerdown', event => { event.preventDefault(); event.stopPropagation(); });
    panel.body.append(busyEl);
    overlay.addEventListener('pointerdown', () => queueMicrotask(fitHeight));
    overlay.querySelector('.dragpanel-grip')?.addEventListener('pointerdown', () => setManualSize(true), true);
    input = overlay.querySelector('.em-input');
    statusEl = overlay.querySelector('.em-status');
    trailEl = overlay.querySelector('.em-trail');
    filtersEl = overlay.querySelector('.em-filters');
    bodyEl = overlay.querySelector('.em-body');
    footEl = overlay.querySelector('.em-foot');
    ttabsEl = overlay.querySelector('.emt-tabs');
    actsEl = overlay.querySelector('.emt-acts');
    permEl = overlay.querySelector('.emt-perm');
    permInput = overlay.querySelector('.emt-perm-input');
    permStatus = overlay.querySelector('.emt-perm-status');
    // Enter = 저장하고 닫기 · Esc = 되돌리고 닫기(창의 Esc 처리기가 먼저 받는다 - 거기서 이 줄을 닫는다) · 칸을 떠나면 저장.
    permInput.addEventListener('input', scheduleAc);
    permInput.addEventListener('keydown', event => {
      if (event.isComposing || event.keyCode === 229) return;
      const acOpen = acEl && !acEl.hidden && acItems.length;
      if (acOpen && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
        event.preventDefault();
        acActive = (acActive + (event.key === 'ArrowDown' ? 1 : -1) + acItems.length) % acItems.length;
        paintAc();
        return;
      }
      if (acOpen && (event.key === 'Enter' || event.key === 'Tab') && acActive >= 0) {
        event.preventDefault();
        chooseAc(acActive);
        return;
      }
      if (event.key !== 'Enter') return;
      event.preventDefault();
      // 고를 태그가 없으면 더하지 않는다 - 이벤트 맵 색인의 태그만 들어간다(사용자 지시 2026-10-14).
      if (permInput.value.trim()) toast('목록에서 태그를 골라 주세요 (이벤트 맵에 있는 태그만 더한다)', 'info');
      else { openPermanent(false); focusInput(); }
    });
    permInput.addEventListener('blur', () => closeAc());
    permEl.querySelector('[data-emt-perm-detail]').addEventListener('click', openChips);
    paintViewToggle();
    panel.slot.addEventListener('click', event => {
      const v = event.target.closest('[data-em-view]');
      if (v) setViewMode(v.dataset.emView);
    });
    ttabsEl.addEventListener('change', event => {
      if (!event.target.matches('[data-emt-simple]')) return;
      simpleMode = event.target.checked;
      rememberView();
      render(true);
      focusInput();
    });
    ttabsEl.addEventListener('click', event => {
      const t = event.target.closest('[data-emt-d1]');
      if (!t || t.disabled || busyCount) return;
      const id = t.dataset.emtD1;
      if (pins.length) {
        if (id === treeFilter) return;
        treeFilter = id;
        if (id && treeAll) {
          const b = treeBranch(id);
          const g = b?.d2.find(x => x.id === treeLastD2.get(id)) || b?.d2[0];
          if (b) treeSel = { d1: b.id, d2: g?.id || '', d3: '' };
        } else if (id) choosePinnedSlot(id, treeLastD2.get(id) || '', '');
        void explore();
        return;
      }
      if (id && id !== treeSel.d1) pickTree(id);
    });
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
        if (eventLinked()) await syncRandomLink();
        await explore();
      }, toast, resize: fitHeight, onLoad: onOpenSaved, onChange: onLibraryChange,
    });
    paintRandomLink();
    footEl.querySelector('[data-em-random-link]').addEventListener('change', event => {
      void syncRandomLink(event.target.checked);
    });
    input.addEventListener('input', () => {
      // 접은 채로 검색 칸에 치면 펼친다 - 후보 목록은 몸통에 뜬다
      if (panel.isCollapsed()) panel.expand();
      active = -1; scheduleSuggest();
    });
    input.addEventListener('keydown', onKeyDown);
    overlay.querySelector('[data-emt-stage]').addEventListener('click', () => onStage?.(currentSelection()));
    overlay.querySelector('[data-emt-stage-open]').addEventListener('click', () => onOpenStaging?.());

    trailEl.addEventListener('click', event => {
      const t = event.target;
      const goto = t.closest('[data-em-goto]');
      if (goto) { goTo(Number(goto.dataset.emGoto)); return; }
      const unpin = t.closest('[data-em-unpin]');
      if (unpin) { pins = pins.filter(x => x !== unpin.dataset.emUnpin); void explore(); return; }
      const unex = t.closest('[data-em-unexclude]');
      if (unex) { clearExclude(unex.dataset.emUnexclude); return; }
      if (t.closest('[data-em-group-back]')) { resetSelection(); return; }
      if (t.closest('[data-em-back]')) { goBack(); return; }
    });
    // 넣기 · 생성 · 복사 · 실제 조합 - 기존 화면은 조건 줄에, 3단 지도는 발줄에 있다.
    function onActionClick(t) {
      if (t.closest('[data-em-insert]')) { void applyPins(t.closest('[data-em-insert]')); return true; }
      if (t.closest('[data-em-insert-generate]')) { void applyPins(t.closest('[data-em-insert-generate]'), true); return true; }
      if (t.closest('[data-em-copy]')) { void copyText(currentPrompt()); return true; }
      if (t.closest('[data-em-samples]')) { if (samples) { samples = null; render(); } else void drawSamples(); return true; }
      return false;
    }
    footEl.addEventListener('click', event => {
      const t = event.target;
      const rb = t.closest('[data-em-random]');
      if (rb) { void randomAssign(rb, rb.dataset.emRandom === 'generate'); return; }
      onActionClick(t);
    });
    filtersEl.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-emt-perm]')) { openPermanent(!permOpen); return; }
      const menuBtn = t.closest('[data-emt-menu]');
      if (menuBtn) { if (menuEl && !menuEl.hidden) closeTreeMenu(); else openTreeMenu(menuBtn); return; }
      if (t.closest('[data-em-pe-settings]')) { openPeSettings(); return; }
      if (t.closest('[data-em-reset]')) { resetSelection(); return; }
      if (onActionClick(t)) return;
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
      const go = event.target.closest('[data-emt-go]');
      if (go) {   // 줄 아래 경로 조각 - 줄(핀 꽂기)보다 먼저 받는다
        event.stopPropagation();
        goToSlot(go.dataset.emtGoD1 || '', go.dataset.emtGoD2 || '', go.dataset.emtGoD3 || '');
        return;
      }
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
      if (t.closest('[data-emt-retry]')) { void loadTree(); return; }
      if (t.closest('[data-emt-all]')) {
        if (treeAll) return;
        treeAll = true;
        if (pins.length) void explore(); else void loadTree();
        return;
      }
      const d2 = t.closest('[data-emt-d2]');
      const gall = t.closest('[data-emt-gall]');
      if (d2 || gall) {
        // 그룹 머리 = 단추 - 누르면 그 그룹 전부(펼친 그룹 맨 위 [전체] 와 같다).
        const id = d2 ? d2.dataset.emtD2 : treeSel.d2;
        if (!treeAll && id === treeSel.d2 && !treeSel.d3) return;
        treeAll = false;
        if (pins.length) { choosePinnedSlot(treeFilter, id, ''); treeSel.d3 = ''; void explore(); return; }
        pickTree(treeSel.d1, id); return;
      }
      const d3 = t.closest('[data-emt-d3]');
      if (d3) {
        if (d3.dataset.emtD3 === treeSel.d3) return;
        if (pins.length) { treeSel.d3 = d3.dataset.emtD3; rememberView(); void explore(); return; }
        pickTree(treeSel.d1, treeSel.d2, d3.dataset.emtD3); return;
      }
      const rb = t.closest('[data-em-relax]');
      if (rb) { relaxOne = !relaxOne; void explore(); return; }
      const sb = t.closest('[data-em-sort]');
      if (sb) {
        const i = SORT_MODES.findIndex(m => m.id === sortMode);
        sortMode = SORT_MODES[(i + 1) % SORT_MODES.length].id;
        savePrefs(persons, ratings, sortMode);
        void explore();
        return;
      }
      const cat = t.closest('[data-em-cat]');
      if (t.closest('[data-em-unclassified]')) {
        if (!result?.unclassified_available) return;
        roles = roles.has('unsorted') ? new Set() : new Set(['unsorted']);
        subcategory = ''; void explore(); return;
      }
      if (cat) {
        const id = cat.dataset.emCat;
        if (pins.length) { subcategory = ''; roles = id ? new Set([id]) : new Set(); void explore(); }
        else if (id) pickGroup(id);
        return;
      }
      const cp = t.closest('[data-emt-copy]');
      if (cp) { event.stopPropagation(); void copyText(cp.dataset.emtCopy); return; }
      const ins = t.closest('[data-emt-insert]');
      if (ins) { event.stopPropagation(); insertOne(ins.dataset.emtInsert); return; }
      const row = t.closest('[data-em-pin]');
      if (row && simpleMode && row.classList.contains('emt-row')) return;   // 단순 검색 모드 - 탐사하지 않는다
      if (row) pin(row.dataset.emPin);
    });
    overlay.addEventListener('pointerover', event => {
      const row = event.target.closest ? event.target.closest('.em-row[data-em-pin], [data-em-tip-tag]') : null;
      if (row) showTip(row);
    });
    overlay.addEventListener('pointerout', event => {
      const row = event.target.closest ? event.target.closest('.em-row[data-em-pin], [data-em-tip-tag]') : null;
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
    new ResizeObserver(fitHeight).observe(overlay);

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

  /** 아무 줄도 안 짚었을 때 Enter 가 고를 자리.
   *
   *  ⭐ **친 글자와 정확히 같은 태그가 있으면 그것**이다(사용자 제보 2026-09-19).
   *     예전에는 무조건 첫 줄이었는데, 목록은 게시물 수 순이라 `pig` 를 치면
   *     `pigeon-toed`(10,575)가 `pig`(3,286)보다 위에 서서 그것이 꽂혔다.
   *     이름을 **다 친 사람**의 뜻은 그 이름이지 더 흔한 이웃이 아니다.
   *  ⚠️ 대소문자·앞뒤 공백만 무시한다. 안쪽 공백은 태그의 일부다(`pig ears`).
   */
  function exactRowIndex() {
    const want = String(input?.value || '').trim().toLowerCase();
    if (!want) return 0;
    const at = rows.findIndex(tag => String(tag || '').trim().toLowerCase() === want);
    return at >= 0 ? at : 0;
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
      if (simpleMode && isTree() && !input.value.trim()) return;   // 단순 검색 모드 - 탐사하지 않는다(클릭과 같다)
      pin(rows[active >= 0 ? active : exactRowIndex()]);
      return;
    }
    if (event.key === '-' && rows.length && active >= 0) {
      event.preventDefault();
      exclude(rows[active]);
      return;
    }
    // ⛔ 빈 검색 칸의 Backspace 로 핀을 하나씩 빼던 것은 회수했다(사용자 지시 2026-10-14 - 의도하지 않은 핀 해제).
    //    핀은 부스러기의 × 나 ← 로만 뺀다.
  }

  /** 조건 줄([인원][G S Q E][초기화][PE설정] … [넣기 복사 실제 조합])이 **한 줄에** 들어가는 폭.
   *  인원 라벨이 길어지면(`여다수 남다수`) 그만큼 넓힌다 - 줄이 꺾이면 창의 모양이 무너진다(2026-09-13 규칙). */
  function panelMinimumWidth() {
    if (!filtersEl) return EM_BASE_WIDTH;
    const css = getComputedStyle(filtersEl);
    const children = [...filtersEl.children];
    return Math.max(EM_BASE_WIDTH, Math.ceil(children.reduce((n, el) => n + el.getBoundingClientRect().width, 0)
      + Math.max(0, children.length - 1) * (parseFloat(css.columnGap) || 0)
      + (parseFloat(css.paddingLeft) || 0) + (parseFloat(css.paddingRight) || 0) + 4));
  }

  function readManualSize() {
    try { return sessionStorage.getItem(EM_MANUAL_SIZE_KEY) === '1'; } catch (_) { return false; }
  }
  function setManualSize(on) {
    manualSize = !!on;
    try { on ? sessionStorage.setItem(EM_MANUAL_SIZE_KEY, '1') : sessionStorage.removeItem(EM_MANUAL_SIZE_KEY); } catch (_) {}
  }

  /** 창의 크기를 내용에 맞춘다 - 떠 있는 창으로 옮기면서 사라진 예전 창의 규칙(사용자 지적 2026-10-06).
   *   · 폭: 조건 줄이 한 줄에 들어갈 만큼은 언제나 확보한다(사용자가 더 넓힌 것은 그대로 둔다).
   *   · 높이: 손잡이로 크기를 잡기 전까지는 **내용만큼**(바닥 EM_BASE_HEIGHT, 천장은 화면 아래 끝). 목록이
   *     길면 자라고 짧으면 줄어든다. 손잡이를 잡은 뒤로는 그 크기를 지킨다(이번 실행 동안 - 창 크기와 같은 수명). */
  function fitWindow() {
    const rect = overlay.getBoundingClientRect();
    const need = Math.min(panelMinimumWidth(), window.innerWidth - 16);
    if (rect.width < need - 0.5) overlay.style.width = `${need}px`;
    // 접혀 있으면 높이를 내용에 맞추지 않는다 - 맞추면 접은 창이 곧바로 다시 커진다(공용 창이 높이를 비워 접는다)
    if (manualSize || !bodyEl || panel?.isCollapsed()) return;
    const last = bodyEl.lastElementChild;
    const bodyRect = bodyEl.getBoundingClientRect();
    // 3단 지도의 왼쪽 목록은 몸통 높이에 묶여 있다(sticky) - 그 높이로 재면 잴 때마다 창이 자란다.
    // 두 칸 각자의 **원래 높이**로 잰다.
    const grid = last?.classList.contains('emt-grid') ? last : null;
    const content = grid ? Math.ceil((grid.getBoundingClientRect().top - bodyRect.top + bodyEl.scrollTop)
        + Math.max(...[...grid.children].map(el => el.scrollHeight)) + 8)
      : last ? Math.ceil(last.getBoundingClientRect().bottom - bodyRect.top + bodyEl.scrollTop + 8) : 0;
    const chrome = overlay.offsetHeight - bodyEl.clientHeight;
    const room = Math.max(EM_MIN_HEIGHT, window.innerHeight - Math.max(8, rect.top) - 12);
    const want = Math.round(Math.min(room, Math.max(EM_BASE_HEIGHT, chrome + content)));
    if (Math.abs(overlay.offsetHeight - want) > 1) overlay.style.height = `${want}px`;
  }

  // 창의 자리는 공용 창 관리자가 소유한다. 크기는 위의 규칙으로 맞추고, 보조 창을 정렬한다.
  function position() {
    panel?.refit();
    fitHeight();
  }
  function fitHeight() {
    if (!overlay || overlay.hidden) return;
    fitWindow();
    panel.refit();
    if (bodyEl) bodyEl.style.setProperty('--emt-h', `${Math.max(120, bodyEl.clientHeight - 10)}px`);
    const z = Number(overlay.style.zIndex) + 1;
    for (const el of [subEl, sideEl, personPopup, document.querySelector('.em-saved-panel')]) {
      if (el) el.style.zIndex = String(z);
    }
    if (tipEl) tipEl.style.zIndex = String(z + 1);   // 툴팁은 위 창들보다 한 칸 위(행 툴팁을 열 때와 같은 값)
    positionSubcategories();
    positionSide();
    library?.position();
  }

  async function show() {
    build();
    open = true;
    panel.open();
    syncCollapsed();                // 접힌 채로 기억된 창이면 보조 창 숨김 표시도 다시 건다
    if (tabBtn) tabBtn.setAttribute('aria-pressed', 'true');
    position();
    focusInput();                   // 열자마자 - 바로 칠 수 있게(사용자 지정 2026-09-12 밤)
    setStatus('여는 중…', 'busy');
    dlFailed = false; dlError = '';      // 다시 열면 다시 시도한다
    treeMap = null; treeData = null;     // 3단 지도의 골격도 열 때마다 새로(색인이 바뀌면 절의 태그 수가 바뀐다)
    void loadPermanent();                // Search 에서 바꿨을 수 있다
    await loadState();
    if (mapState?.state !== 'ready') { await autoDownload(); startDlPoll(); }
    render();
    if (mapState?.state === 'ready' && (pins.length || isTree())) void explore();
    position();
    focusInput();                   // 그려진 뒤 한 번 더(그 사이 누가 가져갔어도)
  }
  function focusInput() {
    if (!input || !open) return;
    input.focus({ preventScroll: true });
    requestAnimationFrame(() => { if (open && document.activeElement !== input) input.focus({ preventScroll: true }); });
  }
  /** 접힘 상태를 뿌리에 표시한다. 보조 창은 창 밖 body 에 따로 떠 있어 본 창과 함께 접히지 않는다 - 이 표시로 CSS 가
   *  **접힌 창에 여는 단추가 없는 것**(소분류 · 저장 패널)을 숨긴다. 각자의 hidden 은 건드리지 않으므로 펼치면 접기 전
   *  그대로 다시 보인다(접은 동안 다시 그려져도 마찬가지다). 인원 팝업 · 실제 조합 · 툴팁은 접힌 창에 남는 줄에서
   *  열리므로 숨기지 않는다 - 다만 창의 모양이 바뀌는 순간에는 떠 있던 팝업 · 툴팁을 닫고, 실제 조합은 새 자리에 다시 앉힌다. */
  function syncCollapsed(collapsed = panel?.isCollapsed()) {
    document.documentElement.classList.toggle('em-window-collapsed', !!collapsed && open);
    if (collapsed) { closePersonPopup(); closeTreeMenu(); hideTip(); if (open) queueMicrotask(positionSide); }
    else if (open) queueMicrotask(fitHeight);
  }
  function close() {
    if (!open) return;
    hideTip();
    library?.close();
    moreRequest = null; moreError = '';
    if (!overlay) return;
    closePersonPopup();
    closeTreeMenu();
    if (chipPanel?.isOpen()) chipPanel.close();
    if (permOpen) { permOpen = false; if (permEl) permEl.hidden = true; closeAc(); }
    open = false;
    if (panel.isOpen()) panel.close();
    if (subEl) subEl.hidden = true;
    if (sideEl) { sideEl.hidden = true; sideEl.innerHTML = ''; }
    if (tabBtn) tabBtn.setAttribute('aria-pressed', 'false');
    document.documentElement.classList.remove('em-window-collapsed');
    clearTimeout(timer);
    stopDlPoll();                   // 화면 폴링만 멈춘다 - 내려받기는 서버에서 계속 돈다
    seq += 1; suggestSeq += 1;
  }
  function toggle() { if (open) close(); else void show(); }

  /** [PE설정] - 메인 프롬프트의 `/pe` **그 목록**을 연다.
   *
   *  ⚠️ 여기서 목록을 다시 그리지 않는다. `/pe` 의 행들은 지금 설정을 읽어 ON/OFF 를
   *     적는데, 같은 것을 두 곳에서 그리면 한쪽이 반드시 뒤처진다(토글 하나를 고쳐도
   *     다른 쪽은 옛 값을 보여 준다). 창을 하나만 두면 그 일이 생길 수 없다.
   */
  function openPeSettings() {
    if (typeof openPeSlash !== 'function') { toast('PE 설정을 열 수 없습니다.', 'error'); return; }
    let ok = false;
    try { ok = Boolean(openPeSlash()); }
    catch (error) { toast(`PE 설정 실패 — ${error?.message || error}`, 'error'); return; }
    if (!ok) toast('메인 프롬프트 칸을 찾지 못했습니다.', 'error');
  }

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
      if (menuEl && !menuEl.hidden) { closeTreeMenu(); return; }
      if (acEl && !acEl.hidden) { closeAc(); return; }
      if (permOpen) { openPermanent(false); focusInput(); return; }
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

  async function searchCombination(item) {
    if (!Array.isArray(item.tags) || item.tags.length < 3 || item.tags.length > 8) return;
    if (!RATING_OPTIONS.some(r => r.id === item.rating) || !PERSON_IDS.includes(item.person)) return;
    if (linkPending || linkUncertain) { toast('랜덤 연결 상태를 확인한 뒤 다시 검색해주세요.', 'error'); return; }
    await show();
    library?.close();
    pins = item.tags.slice(); excludes = [];
    ratings = new Set([item.rating]); persons = new Set([item.person]);
    group = ''; roles.clear(); subcategory = ''; samples = null; browse = null;
    input.value = ''; suggest = null; ++suggestSeq; clearTimeout(timer);
    savePrefs(persons, ratings, sortMode);
    if (eventLinked()) await syncRandomLink();
    await explore();
  }
  /** S 창의 [맵에서 열기] - 저장 · 스테이징된 조합을 이 창에 그대로 편다(저장된 조합 불러오기와 같은 길). */
  async function openSelection(selection) {
    if (linkPending || linkUncertain) throw new Error('랜덤 연결 상태를 확인한 뒤 다시 열어주세요.');
    if (!open) await show();
    library?.close();
    pins = selection.pins.slice(); excludes = selection.exclude.slice();
    ratings = new Set(selection.ratings); persons = new Set(selection.persons);
    group = ''; roles.clear(); subcategory = ''; samples = null; browse = null;
    if (isTree()) { treeFilter = treeSel.d1; treeAll = false; }
    input.value = ''; suggest = null; ++suggestSeq; clearTimeout(timer);
    savePrefs(persons, ratings, sortMode);
    if (eventLinked()) await syncRandomLink();
    await explore();
  }

  const refreshRandomLink = () => getJson('/api/event-map/random-link').then(receiveRandomLink).catch(() => {});
  void refreshRandomLink();
  return { show, close, toggle, isOpen: () => open, pins: () => pins.slice(),
    isRandomLinked: () => randomLink.enabled, isRandomLinkPending: () => linkPending > 0 || linkUncertain,
    randomLinkMode: () => (randomLink.enabled ? (randomLink.mode || 'event') : ''),
    /** 스테이징이 바뀌었다(S 창) - [스테이징] 단추의 켜짐을 다시 정한다. */
    syncStaged: () => { if (overlay) paintActions(); },
    receiveRandomLink, refreshRandomLink, searchCombination, openSelection };
}
