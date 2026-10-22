/**
 * Characters 창 - 오른쪽 탭 [Characters] 를 누르면 뜨는 떠 있는 창(사용자 결정 2026-10-22 · Artist 탭처럼).
 *
 *   [ 검색(이름 · 한글 · 초성 · work:) | ALL 여 남 외 | ★ | + 필터 ]
 *   [ 특징 칩 +포함 / −제외 / work: ]
 *   [ 그룹(전부 · 보이는 만큼만) |  썸네일 격자(전부 · 보이는 만큼만 · 창 폭에 맞춘 칸 수) ]
 *   [ 고른 캐릭터 줄: 이름 · 작품 · 게시물 · 프롬프트 줄 · [+ 슬롯] [+ 풀] [생성] [★] [복사] [숨김] [⋯] ]
 *
 * 탭 규칙(Artist 와 같다): 창이 없거나 접혀 있으면 창부터 세우고 탭으로 가지 않는다. 창이 펴져 있을 때 다시 누르면 탭으로.
 * Find(퀵 패널)와는 **따로**다(사용자 결정) - 다만 같은 인프라를 쓴다: 같은 검색 라우트(`/list` · 검색 색인) · 같은 특징 자동완성 ·
 * 슬롯 담기 · 풀 · 생성은 퀵 패널의 손잡이(`getActions()`) · 생성 옵션은 Find ⚙ 와 같은 생성 설정 창.
 *
 * 격자는 `/list?...&offset=&limit=` 로 **보이는 덩어리만** 받는다(서버 결과 캐시에서 자른다 - 검색 색인 f1706ad3).
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const BLOCK = 60;                       // 한 번에 받는 칸 수
const CELL_MIN = 104;                   // 칸 최소 폭(px) - 창 폭에 맞춰 칸 수가 바뀐다
const CELL_GAP = 7;
const NAME_H = 34;                      // 칸 아래 이름 두 줄
const GROUP_ROW = 24;
const GENDER_KEY = 'naia_chw_gender';
const LANG_KEY = 'naia_chw_lang';       // 그룹(작품) 이름 [한글 | 영문] - 사용자 지시 2026-10-22
// 특수 그룹(사용자 지시 2026-10-22): 1명짜리 작품은 'etc' 한 묶음으로 모으고, original(작가 캐릭터)은 따로 -
// 둘 다 All 바로 밑에 고정한다(일반 작품과 섞이지 않게). etc 는 서버의 특수 그룹 키다.
const GROUP_ETC = '__ETC__';
const PINNED_GROUPS = ['original'];
const DRAWER_H_KEY = 'naia_chw_drawer_h';
const DRAWER_H_MIN = 260;              // 서랍 높이 - 머리 손잡이로 끈다(사용자 지시 2026-10-22 · 우하단 자유 크기는 없다)
const DRAWER_H_DEFAULT = 440;
const GENDERS = [['all', 'ALL', '전체'], ['girl', '여', '여성'], ['boy', '남', '남성'], ['other', '외', '비인간']];

export function createCharacterWindow({
  document: doc = document,
  window: win = window,
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  getActions = () => ({}),            // 퀵 패널 손잡이: addToSlot · poolAdd · generateThumb · openGenSettings · openPoolWindow · poolCount
  openCharacterPage = () => {},       // [⋯] Characters 탭에서 열기(옛 화면 - 연속 생성 등)
  openExternalUrl = null,             // [외부 브라우저] - app.js openUrlInSystemBrowser(데스크톱 셸은 기본 브라우저 · 웹은 새 탭)
} = {}) {
  let panel = null;
  const escAttr = value => escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  const readGender = () => { try { return storage?.getItem(GENDER_KEY) || 'girl'; } catch (_) { return 'girl'; } };

  // 검색 상태 - 바뀌면 결과(덩어리 캐시)를 처음부터.
  const state = {query: '', group: '__ALL__', gender: readGender(), fav: false, inc: [], exc: []};
  let total = 0;
  let genderCounts = null;
  let seq = 0;                          // 조건이 바뀔 때마다 올린다 - 옛 응답은 버린다
  let blocks = new Map();               // 덩어리 번호 -> items | 'loading'
  let stale = new Map();                // 바깥 갱신(softRefresh) 동안 보여 줄 옛 덩어리 - 새 것이 오면 그 덩어리만 바뀐다
  let aborts = new Map();
  let queryTimer = 0;
  let selected = null;                  // {group, character, count, favorite}
  let selectedLine = '';
  let selVariant = '';                  // 상세보기에서 고른 변형('' = Default) - 슬롯 · [생성] 이 그 변형으로 간다
  let busy = '';
  let groups = [];                      // [{key, name, count}]
  let groupQuery = '';
  // 필터 줄은 늘 보인다 · 추천 낱말은 칩 나열이 아니라 입력칸 아래 자동완성 목록(사용자 지시 2026-10-22).
  let feat = {open: true, line: 'inc', text: '', rows: [], seq: 0, timer: 0, active: 0, show: false};
  let lang = (() => { try { return storage?.getItem(LANG_KEY) === 'en' ? 'en' : 'ko'; } catch (_) { return 'ko'; } })();
  /** 그룹(작품) 이름 - 한글 모드면 한글 이름이 있을 때 그것(없으면 영문 그대로). */
  const groupLabel = (key, fallback = key) => (lang === 'ko' && groupKo[key]) || fallback;
  let groupKo = {};
  let failedSeq = -1;                   // 이 조건(seq)에서 이미 실패를 알렸다 - 토스트는 한 번만

  // ── 틀 ────────────────────────────────────────────────────────────────────
  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win,
      title: 'Characters',
      variant: 'chw',
      storageKey: 'character-window',
      width: 720, height: 640, minWidth: 480, minHeight: 360, maxWidth: 1600,
      resizable: true, collapsible: true,
      initial: {right: 24, y: 80},
      escHtml,
      onResize: () => layoutGrid(),
    });
    panel.slot.innerHTML = `<button type="button" class="chw-hb" data-chw-ext title="캐릭터 목록을 기본 브라우저에서 엽니다 (보기 · 검색 · 프롬프트 복사)">외부 브라우저</button>`
      + `<button type="button" class="chw-hb" data-chw-pool title="세션 와일드카드(랜덤 풀) 창">풀</button>`;
    panel.slot.addEventListener('click', onSlotClick);
    panel.body.innerHTML = `<div class="chw">`
      + `<div class="chw-tools"><input class="chw-q" type="search" data-chw-q spellcheck="false" autocomplete="off"`
      + ` placeholder="이름 · 한글 · 초성 · work:작품">`
      + `<span class="chw-seg" data-chw-seg></span>`
      + `<button type="button" class="chw-tb" data-chw-fav title="즐겨찾기만">★</button></div>`
      + `<div class="chw-feat" data-chw-feat></div>`
      + `<div class="chw-chips" data-chw-chips hidden></div>`
      + `<div class="chw-main"><div class="chw-groups"><input class="chw-gq" type="search" data-chw-gq placeholder="그룹 검색" spellcheck="false">`
      + `<div class="chw-glist" data-chw-glist><div class="chw-gspacer" data-chw-gspacer></div></div></div>`
      + `<div class="chw-grid" data-chw-grid tabindex="0"><div class="chw-count" data-chw-count></div><div class="chw-spacer" data-chw-spacer></div></div>`
      // 생성 옵션 서랍 - 창 안의 떠 있는 카드(아래에서 위로 · 좌우로 늘리지 않는다). 내용은 생성 설정 조각을 옮겨 붙인다.
      + `<div class="chw-drawer" data-chw-drawer hidden>`
      + `<div class="chw-drawer-grip" data-chw-grip data-naia-title="위아래로 끌어 높이를 바꿉니다"></div>`
      + `<div class="chw-drawer-body" data-chw-drawer-body hidden></div>`
      + `<div class="chw-drawer-detail" data-chw-detail hidden></div></div></div>`
      + `<div class="chw-sel" data-chw-sel></div></div>`;
    const body = panel.body;
    body.addEventListener('click', onClick);
    body.addEventListener('input', onInput);
    body.addEventListener('keydown', onKey);
    // 목록을 누르는 동안 입력칸 초점을 지킨다(누르기 전에 blur 로 목록이 닫히지 않게) · 칸을 떠나면 닫는다.
    body.addEventListener('mousedown', event => { if (event.target.closest('[data-chw-fdrop]')) event.preventDefault(); });
    body.addEventListener('focusin', event => {
      const input = event.target.closest('[data-chw-ft]');
      if (!input) return;
      // 칸을 옮기면 그 칸의 글로 다시 묻는다(포함 칸에 친 글이 제외 칸의 후보로 남지 않게).
      if (feat.line !== input.dataset.chwFl) {
        feat.line = input.dataset.chwFl;
        feat.text = input.value || ''; feat.rows = []; feat.active = 0;
        if (feat.text.trim()) suggest();
      }
      feat.show = true; paintFeat();
    });
    body.addEventListener('focusout', event => { if (event.target.closest('[data-chw-ft]')) { feat.show = false; paintFeat(); } });
    body.querySelector('[data-chw-grid]').addEventListener('scroll', () => paintGrid(), {passive: true});
    body.querySelector('[data-chw-grip]').addEventListener('pointerdown', onGripDown);
    body.querySelector('[data-chw-grid]').addEventListener('contextmenu', onGridContextMenu);
    body.querySelector('[data-chw-glist]').addEventListener('scroll', () => paintGroups(), {passive: true});
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => layoutGrid()).observe(body.querySelector('[data-chw-grid]'));
    return panel;
  }

  const el = sel => panel?.body.querySelector(sel);

  // ── 서버 ──────────────────────────────────────────────────────────────────
  function listParams() {
    const p = new URLSearchParams();
    if (state.group && state.group !== '__ALL__') p.set('group', state.group);
    if (state.query.trim()) p.set('query', state.query.trim());
    if (state.fav) p.set('favorites_only', 'true');
    if (state.gender !== 'all') p.append('gender', state.gender);
    const enc = term => (term.kind === 'work' ? `work:${term.tag}` : term.tag);    // Find 와 같은 꼴
    state.inc.forEach(term => p.append('inc', enc(term)));
    state.exc.forEach(term => p.append('exc', enc(term)));
    return p;
  }

  function resetResults() {
    seq += 1;
    aborts.forEach(ctrl => { try { ctrl.abort(); } catch (_) {} });
    aborts = new Map();
    blocks = new Map();
    stale = new Map();
    total = 0;
    const grid = el('[data-chw-grid]');
    if (grid) grid.scrollTop = 0;
    void loadBlock(0);
  }

  async function loadBlock(index) {
    if (blocks.has(index)) return;
    const mine = seq;
    const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    blocks.set(index, 'loading');
    if (ctrl) aborts.set(index, ctrl);
    try {
      const p = listParams();
      p.set('offset', String(index * BLOCK));
      p.set('limit', String(BLOCK));
      const res = await fetch(`/api/character-viewer/list?${p}`, {cache: 'no-store', signal: ctrl?.signal});
      if (mine !== seq) return;                     // 조건이 바뀌었다 - 본문도 읽지 않는다
      const data = await res.json().catch(() => ({}));
      if (mine !== seq) return;
      if (!res.ok) throw new Error(data.error || '목록을 불러오지 못했습니다.');
      total = Number(data.total) || 0;
      genderCounts = data.gender_counts || genderCounts;
      const items = Array.isArray(data.items) ? data.items : [];
      blocks.set(index, items);
      stale.delete(index);
      // 3. 고른 캐릭터의 ★ 를 서버 값으로 맞춘다(Find 에서 바꿨을 수 있다 - 낡은 값의 반대를 보내면 토글이 헛돈다).
      const hit = selected && items.find(it => it.group === selected.group && it.character === selected.character);
      if (hit && !!hit.favorite !== !!selected.favorite) { selected.favorite = !!hit.favorite; paintSel(); }
    } catch (error) {
      if (mine !== seq || error?.name === 'AbortError') return;
      // 'error' 로 남긴다 - 지우면 그리기가 그 덩어리를 곧바로 다시 청해 실패가 끝없이 돈다. 조건을 바꾸거나 창을 다시 열면 새로 받는다.
      blocks.set(index, 'error');
      if (failedSeq !== seq) { failedSeq = seq; showToast(error.message || String(error), 'error'); }
    } finally {
      aborts.delete(index);
    }
    if (mine === seq) { paintTools(); layoutGrid(); }
  }

  let groupSeq = 0;
  async function loadGroups() {
    const mine = ++groupSeq;              // 성별을 빠르게 바꾸면 늦게 온 응답이 새 것을 덮지 않게
    try {
      // 성별을 실어 보낸다 - 그룹 인원이 지금 고른 성별의 수로 온다(사용자 지시 2026-10-22).
      const gq = state.gender && state.gender !== 'all' ? `&gender=${encodeURIComponent(state.gender)}` : '';
      const res = await fetch(`/api/character-viewer/groups?offset=0&limit=5000${gq}`, {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      if (mine !== groupSeq) return;
      if (res.ok) {
        const items = Array.isArray(data.items) ? data.items : [];
        groupKo = {};
        items.forEach(g => { if (g && g.ko) groupKo[g.key] = String(g.ko); });
        // All · original · etc 를 위에 고정하고 그 아래 일반 작품(2명 이상). 1명짜리 작품은 etc 한 묶음으로.
        // 묶는 기준은 성별과 무관한 그룹 크기(total) - 성별을 바꿔도 etc 의 구성은 그대로, 인원(count)만 바뀐다.
        // 고른 성별이 0명인 작품은 감춘다(고정 그룹은 남긴다).
        const size = g => Number(g.total ?? g.count ?? 0);
        const all = items.filter(g => g.key === '__ALL__');
        const pinned = PINNED_GROUPS.map(key => items.find(g => g.key === key)).filter(Boolean);
        const singles = items.filter(g => g.key !== '__ALL__' && !PINNED_GROUPS.includes(g.key) && size(g) === 1);
        const etcCount = singles.reduce((sum, g) => sum + Number(g.count || 0), 0);
        const rest = items.filter(g => g.key !== '__ALL__' && !PINNED_GROUPS.includes(g.key) && size(g) > 1
          && Number(g.count || 0) > 0)
          .sort((a, b) => Number(b.count || 0) - Number(a.count || 0));   // 고른 성별의 인원 순
        groups = [...all, ...pinned,
          ...(singles.length ? [{key: GROUP_ETC, name: 'etc', count: etcCount, special: true}] : []), ...rest];
      }
    } catch (_) { /* 다음에 다시 */ }
    paintGroups();
  }

  // ── 격자(보이는 만큼만) ─────────────────────────────────────────────────────
  let geo = {cols: 1, cellW: CELL_MIN, rowH: CELL_MIN + NAME_H + CELL_GAP};

  function layoutGrid() {
    const grid = el('[data-chw-grid]');
    if (!grid) return;
    const width = grid.clientWidth - 16;
    const cols = Math.max(1, Math.floor((width + CELL_GAP) / (CELL_MIN + CELL_GAP)));
    const cellW = Math.floor((width - CELL_GAP * (cols - 1)) / cols);
    geo = {cols, cellW, rowH: cellW + NAME_H + CELL_GAP};
    el('[data-chw-spacer]').style.height = `${Math.ceil(total / cols) * geo.rowH + 8}px`;
    paintGrid();
  }

  function itemAt(i) {
    const b = Math.floor(i / BLOCK);
    const block = Array.isArray(blocks.get(b)) ? blocks.get(b) : stale.get(b);
    return Array.isArray(block) ? block[i % BLOCK] || null : null;
  }

  function cellHtml(item, i) {
    const x = (i % geo.cols) * (geo.cellW + CELL_GAP) + 8;
    const y = Math.floor(i / geo.cols) * geo.rowH + 8;
    const style = `transform:translate(${x}px,${y}px);width:${geo.cellW}px`;
    if (!item) return `<div class="chw-cell is-loading" style="${style}"><div class="chw-im" style="height:${geo.cellW}px"></div></div>`;
    const on = selected && selected.group === item.group && selected.character === item.character;
    const img = item.thumbnail_url
      ? `<img loading="lazy" decoding="async" alt="" src="${escAttr(item.thumbnail_url)}">`
      : `<span class="chw-ini">${escHtml(String(item.character || '?').charAt(0).toUpperCase())}</span>`;
    return `<button type="button" class="chw-cell${on ? ' is-on' : ''}" style="${style}" data-chw-i="${i}"`
      // 툴팁은 달지 않는다 - 칸 아래 이름 · 작품과 같은 말이다(사용자 지시 2026-10-22). 화면 읽기용 이름만.
      + ` aria-label="${escAttr(`${item.character} · ${groupLabel(item.group)}`)}">`
      + `<div class="chw-im" style="height:${geo.cellW}px">${img}${item.favorite ? '<span class="chw-star">★</span>' : ''}</div>`
      + `<div class="chw-nm">${escHtml(item.character)}</div>`
      + `<div class="chw-mt"><span class="chw-glink" data-chw-goto="${escAttr(item.group)}" title="이 작품 그룹으로 가기">`
      + `${escHtml(groupLabel(item.group))}</span> · ${Number(item.count || 0).toLocaleString()}</div></button>`;
  }

  function paintGrid() {
    const grid = el('[data-chw-grid]');
    if (!grid) return;
    const first = Math.max(0, Math.floor(grid.scrollTop / geo.rowH) - 1) * geo.cols;
    const last = Math.min(total, Math.ceil((grid.scrollTop + grid.clientHeight) / geo.rowH + 1) * geo.cols);
    for (let b = Math.floor(first / BLOCK); b <= Math.floor(Math.max(first, last - 1) / BLOCK); b += 1) {
      if (b * BLOCK < Math.max(total, 1)) void loadBlock(b);
    }
    let html = '';
    for (let i = first; i < last; i += 1) html += cellHtml(itemAt(i), i);
    const spacer = el('[data-chw-spacer]');
    if (spacer._html !== html) {
      const focused = doc.activeElement && spacer.contains(doc.activeElement) ? doc.activeElement.dataset.chwI : null;
      spacer._html = html;
      spacer.innerHTML = html;
      // preventScroll 필수 - 그냥 focus() 는 그 칸을 화면 안으로 끌어와 휠 스크롤과 싸운다
      // (사용자 제보 2026-10-22: 칸을 누른 뒤 휠을 올리면 화면이 올라가다 아래로 떨어지기를 되풀이).
      if (focused != null) spacer.querySelector(`[data-chw-i="${focused}"]`)?.focus({preventScroll: true});
    }
    const count = el('[data-chw-count]');
    const label = blocks.get(0) === 'error' && !total ? '불러오지 못했습니다 - 검색을 바꾸거나 창을 다시 여세요'
      : blocks.get(0) === 'loading' && !total ? '불러오는 중…' : total ? `${total.toLocaleString()}명` : '맞는 캐릭터가 없습니다';
    if (count.textContent !== label) count.textContent = label;
  }

  // ── 그룹(보이는 만큼만) ─────────────────────────────────────────────────────
  function shownGroups() {
    const q = groupQuery.trim().toLowerCase();
    return q ? groups.filter(g => g.key === '__ALL__' || String(g.name).toLowerCase().includes(q)
      || String(groupKo[g.key] || '').includes(groupQuery.trim())) : groups;
  }

  function paintGroups() {
    const list = el('[data-chw-glist]');
    if (!list) return;
    const rows = shownGroups();
    const spacer = el('[data-chw-gspacer]');
    spacer.style.height = `${rows.length * GROUP_ROW}px`;
    const first = Math.max(0, Math.floor(list.scrollTop / GROUP_ROW) - 4);
    const last = Math.min(rows.length, Math.ceil((list.scrollTop + list.clientHeight) / GROUP_ROW) + 4);
    let html = '';
    for (let i = first; i < last; i += 1) {
      const g = rows[i];
      html += `<button type="button" class="chw-gi${g.key === state.group ? ' is-on' : ''}" style="transform:translateY(${i * GROUP_ROW}px)"`
        + ` data-chw-g="${escAttr(g.key)}" title="${escAttr(g.key === GROUP_ETC ? '캐릭터가 1명인 작품들' : g.name)}">`
        + `<span>${escHtml(g.key === GROUP_ETC ? 'etc' : groupLabel(g.key, g.name))}</span>`
        + `<i>${Number(g.count || 0).toLocaleString()}</i></button>`;
    }
    if (spacer._html !== html) { spacer._html = html; spacer.innerHTML = html; }
  }

  // ── 도구 줄 · 칩 · 특징 판 ──────────────────────────────────────────────────
  function paintTools() {
    const seg = el('[data-chw-seg]');
    if (!seg) return;
    const html = GENDERS.map(([key, label, tip]) => {
      const n = genderCounts && key !== 'all' ? Number(genderCounts[key] || 0) : null;
      return `<button type="button" class="${key === state.gender ? 'is-on' : ''}" data-chw-gender="${key}"`
        + ` title="${tip}${n != null ? ` ${n.toLocaleString()}명` : ''}">${label}</button>`;
    }).join('');
    if (seg._html !== html) { seg._html = html; seg.innerHTML = html; }
    el('[data-chw-fav]').classList.toggle('is-on', state.fav);
    const chips = el('[data-chw-chips]');
    const chipHtml = [...state.inc.map(t => ['inc', t]), ...state.exc.map(t => ['exc', t])].map(([line, t]) =>
      `<button type="button" class="chw-chip is-${t.kind === 'work' ? 'work' : line}" data-chw-unchip="${line}"`
      + ` data-chw-tag="${escAttr(t.tag)}" data-chw-kind="${escAttr(t.kind)}" title="빼기">`
      + `${line === 'exc' ? '− ' : t.kind === 'work' ? 'work: ' : '+ '}${escHtml(t.tag)} ✕</button>`).join('');
    chips.hidden = !chipHtml;
    if (chips._html !== chipHtml) { chips._html = chipHtml; chips.innerHTML = chipHtml; }
  }

  function shownSuggestions() {
    const chosen = new Set([...state.inc, ...state.exc].map(t => `${t.kind}\u0000${t.tag}`));
    return feat.rows.filter(r => !chosen.has(`${r.kind}\u0000${r.tag}`)).slice(0, 12);
  }

  function paintFeat() {
    const box = el('[data-chw-feat]');
    if (!box) return;
    if (!box.querySelector('[data-chw-ft]')) {
      const wrap = (line, label, example) => `<div class="chw-fwrap is-${line}" data-chw-fwrap="${line}">`
        + `<input class="chw-ft" data-chw-ft data-chw-fl="${line}" type="search" role="combobox" aria-autocomplete="list"`
        + ` aria-controls="chwFdrop-${line}" placeholder="${label} - 색 · 특징 · 가슴 · 작품 (예: ${example})" spellcheck="false" autocomplete="off">`
        + `<div class="chw-fdrop" id="chwFdrop-${line}" role="listbox" data-chw-fdrop="${line}" hidden></div></div>`;
      box.innerHTML = `<div class="chw-feat-row"><span class="chw-fseg" title="그룹(작품) 이름">`
        + `<button type="button" data-chw-lang="ko">한글</button><button type="button" data-chw-lang="en">영문</button></span>`
        + wrap('inc', '포함', 'pink hair') + wrap('exc', '제외', 'glasses') + `</div>`;
    }
    box.querySelectorAll('[data-chw-lang]').forEach(b => b.classList.toggle('is-on', b.dataset.chwLang === lang));
    const rows = shownSuggestions();
    if (feat.active >= rows.length) feat.active = Math.max(0, rows.length - 1);
    const html = rows.map((r, i) =>
      `<div class="chw-fs${i === feat.active ? ' is-on' : ''}" role="option" aria-selected="${i === feat.active}" data-chw-fs="${i}">`
      + `<span>${escHtml(r.tag)}</span><i>${escHtml(r.label || r.kind)} · ${Number(r.count || 0).toLocaleString()}</i></div>`).join('')
      || (feat.text.trim()
        // 캐릭터 이름을 필터 칸에 치는 실수가 잦다(사용자 지시 2026-10-22) - 윗줄로 보낸다.
        ? '<div class="chw-empty">맞는 낱말이 없습니다 · 캐릭터 이름은 윗줄에서 검색하세요</div>'
          + `<button type="button" class="chw-fmove" data-chw-fmove>윗줄에서 '${escHtml(feat.text.trim())}' 찾기</button>`
        : '');
    // 자동완성은 지금 치는 칸(포함/제외) 아래에만.
    box.querySelectorAll('[data-chw-fdrop]').forEach(drop => {
      const mine = drop.dataset.chwFdrop === feat.line;
      drop.hidden = !(mine && feat.show && feat.text.trim());
      const body = mine ? html : '';
      if (drop._html !== body) { drop._html = body; drop.innerHTML = body; }
    });
    box.querySelector(`[data-chw-fdrop="${feat.line}"] .chw-fs.is-on`)?.scrollIntoView({block: 'nearest'});
  }

  function pickSuggestion(index) {
    const row = shownSuggestions()[index];
    if (!row) return;
    (feat.line === 'exc' ? state.exc : state.inc).push({tag: row.tag, kind: row.kind});
    feat.text = ''; feat.rows = []; feat.active = 0;
    const input = el(`[data-chw-fl="${feat.line}"]`); if (input) input.value = '';
    paintTools(); paintFeat(); resetResults();
  }

  function suggest() {
    clearTimeout(feat.timer);
    feat.timer = setTimeout(async () => {
      const mine = ++feat.seq;
      const text = feat.text.trim();
      if (!text) { feat.rows = []; paintFeat(); return; }
      try {
        const res = await fetch(`/api/character-viewer/feature-suggest?q=${encodeURIComponent(text)}`);
        const data = await res.json().catch(() => ({}));
        if (mine !== feat.seq) return;
        if (data.pending) { feat.timer = setTimeout(suggest, 1500); return; }      // 색인 준비 중(Find 와 같다)
        feat.rows = Array.isArray(data.rows) ? data.rows : [];
        feat.active = 0;
      } catch (_) { feat.rows = []; }
      paintFeat();
    }, 150);
  }

  // ── 고른 캐릭터 줄 ───────────────────────────────────────────────────────────
  function paintSel() {
    const box = el('[data-chw-sel]');
    if (!box) return;
    const tog = (mode, label, title) => `<button type="button" class="chw-gopt${drawerMode === mode ? ' is-on' : ''}"`
      + ` data-chw-drawer-mode="${mode}" aria-expanded="${drawerMode === mode}" title="${title}">`
      + `${label} ${drawerMode === mode ? '▾' : '▴'}</button>`;
    const gopt = tog('gen', '생성 옵션', 'Prefix · 캐릭터 슬롯 · Postfix · 옵션')
      + tog('detail', '캐릭터 상세보기', '썸네일 · Variations · 색 · 특징 · 의상 · 프롬프트');
    if (!selected) { box.innerHTML = `${gopt}<div class="chw-empty">캐릭터를 누르면 여기서 슬롯 · 풀 · 생성을 합니다.</div>`; return; }
    const s = selected;
    const off = busy ? ' disabled' : '';
    box.innerHTML = `${gopt}<div class="chw-st"><b>${escHtml(s.character)}</b>`
      + `<span><span class="chw-glink" data-chw-goto="${escHtml(s.group)}" title="이 작품 그룹으로 가기">${escHtml(groupLabel(s.group))}</span>`
      + ` · ${Number(s.count || 0).toLocaleString()}`
      + `${selVariant ? ` · ${escHtml(selVariant.replace(/_/g, ' '))}` : ''}</span></div>`
      + `<div class="chw-acts">`
      + `<button type="button" class="chw-act is-slot" data-chw-act="slot"${off}>+ 슬롯</button>`
      + `<button type="button" class="chw-act is-pool" data-chw-act="pool"${off}>+ 풀</button>`
      + `<button type="button" class="chw-act" data-chw-act="gen"${off} title="썸네일 생성(생성 설정 창의 Prefix · Postfix · 옵션)">생성</button>`
      + `<button type="button" class="chw-act${s.favorite ? ' is-on' : ''}" data-chw-act="fav"${off} title="즐겨찾기">★</button>`
      + `<button type="button" class="chw-act" data-chw-act="copy"${off} title="프롬프트 줄 복사">복사</button>`
      + `<button type="button" class="chw-act is-hide" data-chw-act="hide"${off} title="숨김(검색 · 랜덤에서 빠진다 · Find [제외] 에서 되돌린다)">숨김</button>`
      + `<button type="button" class="chw-act" data-chw-act="more"${off} title="썸네일 삭제 · Characters 탭에서 열기">⋯</button></div>`
      + `<div class="chw-more" data-chw-more hidden>`
      + `<button type="button" data-chw-act="delthumb">내 썸네일 삭제</button>`
      + `<button type="button" data-chw-act="tab">Characters 탭에서 열기(연속 생성 등)</button></div>`;
  }

  async function select(item) {
    selected = {group: item.group, character: item.character, count: item.count, favorite: !!item.favorite};
    selVariant = '';
    // 고르기만 해도 생성 설정 창의 가상 슬롯에 담긴다(사용자 결정 2026-10-22).
    try { win.dispatchEvent(new CustomEvent('naia:character-picked', {detail: {group: item.group, character: item.character}})); } catch (_) {}
    selectedLine = '';
    paintSel();
    paintGrid();
    if (drawerMode === 'detail') void loadDetail();
    await loadLine();
  }

  /** [복사] 할 줄 - 고른 캐릭터 · 변형의 줄(Find [+ 슬롯] 과 같은 옵션). 그사이 바뀌었으면 버린다. */
  async function loadLine() {
    const mine = selected;
    const variant = selVariant;
    selectedLine = '';                   // 못 받으면 옛 줄(다른 변형)이 아니라 이름을 복사한다(Codex 재리뷰)
    if (!mine) return;
    try {
      const res = await fetch('/api/character-viewer/detail', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group: mine.group, character: mine.character, variant,
                              options: {hide_charname: false, cosplay_enabled: false, auto_copyright: true}}),
      });
      const data = await res.json().catch(() => ({}));
      if (mine !== selected || variant !== selVariant) return;
      selectedLine = String(data.prompt?.character_prompt || '').trim();
    } catch (_) { /* 줄만 못 받는다 - 복사는 이름으로 */ }
  }

  async function act(kind) {
    if (!selected || busy) return;
    const s = selected;
    const actions = getActions() || {};
    if (kind === 'more') { const m = el('[data-chw-more]'); if (m) m.hidden = !m.hidden; return; }
    if (kind === 'copy') {
      try { await navigator.clipboard.writeText(selectedLine || s.character); showToast('프롬프트 줄을 복사했습니다.', 'info'); }
      catch (_) { showToast('복사하지 못했습니다.', 'error'); }
      return;
    }
    if (kind === 'tab') { openCharacterPage(s.group, s.character); return; }
    busy = kind;
    paintSel();
    try {
      if (kind === 'slot') await actions.addToSlot?.(s.group, s.character, selVariant);
      else if (kind === 'pool') await actions.poolAdd?.(s.group, s.character);
      // [생성] = 가상 슬롯으로(그 슬롯에서 고친 줄 · 추가 프롬프트 · 네거티브가 함께 나간다).
      else if (kind === 'gen') await (actions.generateVirtual ? actions.generateVirtual(s.group, s.character, selVariant)
        : actions.generateThumb?.(s.group, s.character, {variant: selVariant}));
      else if (kind === 'fav' || kind === 'hide') {
        const fav = kind === 'fav';
        const res = await fetch(fav ? '/api/character-viewer/favorite' : '/api/character-viewer/hidden', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(fav ? {group: s.group, character: s.character, favorite: !s.favorite}
            : {group: s.group, character: s.character, hidden: true}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '처리하지 못했습니다.');
        if (fav) {
          s.favorite = !!data.favorite;
          showToast(s.favorite ? `${s.character} - 즐겨찾기에 넣었습니다` : `${s.character} - 즐겨찾기에서 뺐습니다`, 'info');
        } else {
          showToast(`${s.character} - 숨겼습니다. Find [제외] 에서 되돌립니다`, 'info');
          selected = null;
          selVariant = '';
          selectedLine = '';
          if (drawerMode === 'detail') void loadDetail();    // 선택이 없다 - 빈 상세(앞선 요청은 번호로 무른다)
          try { win.dispatchEvent(new CustomEvent('naia:character-hidden-changed')); } catch (_) {}
        }
        resetResults();
      } else if (kind === 'delthumb') {
        const res = await fetch('/api/character-viewer/thumbnail/delete', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({group: s.group, character: s.character, variant: selVariant}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '지우지 못했습니다.');
        showToast(data.removed ? `${s.character} - 생성된 썸네일을 지웠습니다(기본 썸네일로 돌아갑니다)`
          : `${s.character} - 지울 생성 썸네일이 없습니다`, 'info');
        resetResults();
        if (drawerMode === 'detail') void loadDetail();
      }
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      busy = '';
      paintSel();
    }
  }

  // 바깥에서 목록이 바뀌었다 - 썸네일 저장(생성 완료) · 숨김/되돌림 · 즐겨찾기(Find 쪽에서도). 자리는 지키고 덩어리만 새로.
  function softRefresh() {
    if (!panel || !panel.isOpen()) { blocks = new Map(); return; }    // 닫혀 있으면 열 때 새로 받는다
    seq += 1;
    aborts.forEach(ctrl => { try { ctrl.abort(); } catch (_) {} });
    aborts = new Map();
    blocks.forEach((value, key) => { if (Array.isArray(value)) stale.set(key, value); });
    blocks = new Map();
    paintGrid();
    if (drawerMode === 'detail') scheduleDetail();      // 생성이 끝나 썸네일이 바뀌었을 수 있다 - 몰려도 한 번
  }
  for (const name of ['naia:character-thumb-changed', 'naia:character-hidden-changed', 'naia:character-favorite-changed']) {
    try { win.addEventListener(name, softRefresh); } catch (_) { /* 이벤트가 없으면 다시 열 때 받는다 */ }
  }

  // ── 손 ──────────────────────────────────────────────────────────────────────
  function onSlotClick(event) {
    const actions = getActions() || {};
    if (event.target.closest('[data-chw-pool]')) actions.openPoolWindow?.();
    if (event.target.closest('[data-chw-ext]')) openExternalViewer();
  }

  /** [외부 브라우저] - 지금 보던 그룹 · 검색어 · 성별 · 한글/영문 · 필터를 주소에 싣는다(character-viewer.html 이 읽는다). */
  function externalViewerUrl() {
    const p = new URLSearchParams();
    if (state.group && state.group !== '__ALL__') p.set('group', state.group);
    if (state.query.trim()) p.set('q', state.query.trim());
    p.set('gender', state.gender);
    p.set('lang', lang);
    const enc = term => (term.kind === 'work' ? `work:${term.tag}` : term.tag);
    state.inc.forEach(term => p.append('inc', enc(term)));
    state.exc.forEach(term => p.append('exc', enc(term)));
    return `/character-viewer.html?${p}`;
  }
  function openExternalViewer() {
    const opened = typeof openExternalUrl === 'function' && openExternalUrl(externalViewerUrl());
    if (!opened) showToast('브라우저를 열지 못했습니다 — 팝업 차단을 확인해 주세요.', 'error');
  }

  // ── 우클릭 메뉴 ─────────────────────────────────────────────────────────────
  // 아래 선택 줄의 단추와 같은 일(사용자 지시 2026-10-22). 누른 칸을 먼저 고르고(고르기만 해도 슬롯에 담기 - 같은 규칙)
  // 그 캐릭터에 대해 연다. 옷은 결과 뷰어 · Artist 격자와 같은 `.result-context-menu`.
  let ctxMenu = null;
  let ctxTarget = null;
  function closeCtxMenu() {
    if (ctxMenu) { ctxMenu.remove(); ctxMenu = null; }
    ctxTarget = null;
    doc.removeEventListener('pointerdown', onCtxOutside, true);
    doc.removeEventListener('keydown', onCtxKey, true);
    win.removeEventListener('blur', closeCtxMenu);
    win.removeEventListener('resize', closeCtxMenu);
    el('[data-chw-grid]')?.removeEventListener('scroll', closeCtxMenu);
  }
  function onCtxOutside(event) { if (ctxMenu && !ctxMenu.contains(event.target)) closeCtxMenu(); }
  function onCtxKey(event) {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    closeCtxMenu();
  }
  function onGridContextMenu(event) {
    const cell = event.target.closest('[data-chw-i]');
    if (!cell) return;
    const item = itemAt(Number(cell.dataset.chwI));
    if (!item) return;
    event.preventDefault();
    event.stopPropagation();
    closeCtxMenu();
    const same = selected && selected.group === item.group && selected.character === item.character;
    if (!same) void select(item);
    const s = selected;
    ctxTarget = s;
    const off = busy ? ' disabled' : '';
    const btn = (act, label, cls = '') =>
      `<button type="button" class="result-context-item${cls}" data-chw-ctx="${act}" role="menuitem"${off}><span>${label}</span></button>`;
    const menu = doc.createElement('div');
    menu.className = 'result-context-menu chw-ctx-menu open';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `<div class="chw-ctx-head">${escHtml(s.character)}<span>${escHtml(groupLabel(s.group))}</span></div>`
      + `<div class="result-context-group">${btn('slot', '+ 슬롯')}${btn('pool', '+ 풀')}${btn('gen', '생성')}</div>`
      + `<div class="result-context-group">${btn('fav', s.favorite ? '★ 즐겨찾기 해제' : '★ 즐겨찾기')}${btn('copy', '복사')}</div>`
      + `<div class="result-context-group">${btn('hide', '숨김', ' danger')}${btn('delthumb', '내 썸네일 삭제')}`
      + `${btn('tab', 'Characters 탭에서 열기')}</div>`
      + `<div class="result-context-group">${btn('goto', `'${escHtml(groupLabel(s.group))}' 그룹으로 가기`)}</div>`;
    menu.addEventListener('contextmenu', e => e.preventDefault());
    menu.addEventListener('click', e => {
      const b = e.target.closest('[data-chw-ctx]');
      if (!b) return;
      e.preventDefault();
      e.stopPropagation();
      const target = ctxTarget;
      closeCtxMenu();
      // 그사이 다른 캐릭터가 골라졌으면(다른 칸을 눌렀다) 이 메뉴의 대상이 아니다 - 안 한다.
      if (!target || target !== selected) return;
      if (b.dataset.chwCtx === 'goto') { jumpToGroup(target.group); return; }
      void act(b.dataset.chwCtx);
    });
    doc.body.appendChild(menu);
    ctxMenu = menu;
    const margin = 8;
    const rect = menu.getBoundingClientRect();
    menu.style.left = `${Math.min(Math.max(margin, event.clientX), win.innerWidth - rect.width - margin)}px`;
    menu.style.top = `${Math.min(Math.max(margin, event.clientY), win.innerHeight - rect.height - margin)}px`;
    doc.addEventListener('pointerdown', onCtxOutside, true);
    doc.addEventListener('keydown', onCtxKey, true);
    win.addEventListener('blur', closeCtxMenu);
    win.addEventListener('resize', closeCtxMenu);
    el('[data-chw-grid]')?.addEventListener('scroll', closeCtxMenu, {passive: true});
  }

  // ── 생성 옵션 서랍 ───────────────────────────────────────────────────────────
  let drawerMode = null;                // null | 'gen' | 'detail' - 한 번에 하나만(사용자 지시 2026-10-22)
  let drawerH = (() => {
    try { return Number(storage?.getItem(DRAWER_H_KEY)) || DRAWER_H_DEFAULT; } catch (_) { return DRAWER_H_DEFAULT; }
  })();
  /** 서랍 높이를 놓는다 - 창 안(.chw-main)을 넘지 않게. 칸 높이는 CSS 가 나눈다(캐릭터 · 추가 프롬프트가 늘어난다). */
  function applyDrawerH(h) {
    const box = el('[data-chw-drawer]');
    const room = (el('.chw-main')?.clientHeight || 0) - 12;
    const max = room > DRAWER_H_MIN ? room : DRAWER_H_MIN;
    drawerH = Math.round(Math.min(Math.max(h, DRAWER_H_MIN), max));
    if (box) box.style.height = `${drawerH}px`;
  }
  function onGripDown(event) {
    if (event.button !== 0) return;
    const grip = event.currentTarget;
    const box = el('[data-chw-drawer]');
    const startY = event.clientY;
    const startH = box.getBoundingClientRect().height;
    event.preventDefault();
    try { grip.setPointerCapture(event.pointerId); } catch (_) {}
    grip.classList.add('is-drag');
    // 아래에 붙어 위로 자란다 - 위로 끌면 커진다.
    const move = e => applyDrawerH(startH + (startY - e.clientY));
    const up = () => {
      grip.removeEventListener('pointermove', move);
      grip.removeEventListener('pointerup', up);
      grip.removeEventListener('pointercancel', up);
      grip.classList.remove('is-drag');
      try { storage?.setItem(DRAWER_H_KEY, String(drawerH)); } catch (_) {}
    };
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  }
  async function setDrawer(mode) {
    const box = el('[data-chw-drawer]');
    if (!box) return;
    drawerMode = mode === 'gen' || mode === 'detail' ? mode : null;
    box.hidden = !drawerMode;
    el('[data-chw-drawer-body]').hidden = drawerMode !== 'gen';
    el('[data-chw-detail]').hidden = drawerMode !== 'detail';
    if (drawerMode) applyDrawerH(drawerH);
    paintSel();
    const actions = getActions() || {};
    if (drawerMode !== 'gen') actions.cancelGenOptions?.();
    if (drawerMode === 'detail') { void loadDetail(); return; }
    if (drawerMode !== 'gen') return;
    try { await actions.mountGenOptions?.(el('[data-chw-drawer-body]')); }
    catch (error) { showToast(error.message || String(error), 'error'); }
  }

  // ── 캐릭터 상세보기 ─────────────────────────────────────────────────────────
  // 썸네일 · 이름 · 작품 · 데이터 수 · Variations(칩) · 색 · 특징 · 의상 · 맨 아래 프롬프트 줄(그 슬롯에 담길 줄).
  let detailSeq = 0;
  let detailTimer = 0;
  function scheduleDetail() {
    clearTimeout(detailTimer);
    detailTimer = setTimeout(() => { void loadDetail(); }, 200);
  }
  const GENDER_LABEL = {girl: '여성', boy: '남성', other: '비인간'};
  async function loadDetail() {
    const host = el('[data-chw-detail]');
    if (!host) return;
    const mine = ++detailSeq;
    if (!selected) { host.innerHTML = '<div class="chw-empty">캐릭터를 고르면 여기에 상세가 보입니다.</div>'; return; }
    const s = selected;
    const variant = selVariant;
    host.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      const res = await fetch('/api/character-viewer/detail', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group: s.group, character: s.character, variant}),
      });
      const data = await res.json().catch(() => ({}));
      if (mine !== detailSeq || s !== selected || variant !== selVariant || drawerMode !== 'detail') return;
      if (!res.ok) throw new Error(data.error || '상세를 받지 못했습니다.');
      paintDetail(host, data);
    } catch (error) {
      if (mine === detailSeq) host.innerHTML = `<div class="chw-empty">${escHtml(error.message || String(error))}</div>`;
    }
  }
  function paintDetail(host, d) {
    const n = v => Number(v || 0).toLocaleString();
    const variants = Array.isArray(d.variants) ? d.variants : [];
    const name = d.variant ? `${d.character} (${String(d.variant).replace(/_/g, ' ')})` : d.character;
    const aliases = (d.aliases || []).filter(a => a && a !== d.character);
    // 생성(사용자) 썸네일만 지운다 - URL 의 v= 가 u 로 시작하면 사용자 것(서비스 thumbnail_source 의 접두사).
    const userThumb = /[?&]v=u/.test(String(d.thumbnail_url || ''));
    // 변형에 제 썸네일이 없으면 기본 썸네일로 대신 보인다(빈 칸보다 낫다 · 2026-10-22).
    const thumbUrl = d.thumbnail_url || d.default_thumbnail_url || '';
    const thumb = thumbUrl
      ? `<img class="chw-dt-img" src="${escHtml(thumbUrl)}" alt="" draggable="false">`
      : '<div class="chw-dt-img is-empty">썸네일 없음</div>';
    const sec = (title, items, tone) => (items && items.length
      ? `<div class="chw-dt-sec"><div class="chw-dt-lab">${title}</div>`
        + items.map(it => `<div class="chw-dt-tag${tone}"><span>${escHtml(it.tag)}</span>`
          + `<i><b style="width:${Math.max(0, Math.min(100, Number(it.pct || 0)))}%"></b></i>`
          + `<em>${Number(it.pct || 0).toFixed(1)}%</em></div>`).join('') + '</div>'
      : '');
    const sections = d.sections || {};
    host.innerHTML = `<div class="chw-dt-scroll">`
      + `<div class="chw-dt-head">${thumb}<div class="chw-dt-info"><b>${escHtml(name)}</b>`
      + `<span><span class="chw-glink" data-chw-goto="${escAttr(d.group || '')}" title="이 작품 그룹으로 가기">`
      + `${escHtml(groupLabel(d.group || ''))}</span>${GENDER_LABEL[d.gender] ? ` · ${GENDER_LABEL[d.gender]}` : ''}</span>`
      + `<span>데이터 ${n(d.count)}장${d.danbooru_posts ? ` · Danbooru ${n(d.danbooru_posts)}` : ''}</span>`
      + (aliases.length ? `<span class="chw-dt-alias">별칭: ${escHtml(aliases.join(', '))}</span>` : '')
      + (userThumb ? `<button type="button" class="chw-dt-del" data-chw-act="delthumb"`
        + ` data-chw-dt-g="${escHtml(d.group || '')}" data-chw-dt-c="${escHtml(d.character || '')}" data-chw-dt-v="${escHtml(d.variant || '')}" title="생성된 썸네일을 지우고 기본 썸네일로 돌아갑니다">생성된 썸네일 삭제</button>` : '')
      + `</div></div>`
      + (variants.length > 1
        ? `<div class="chw-dt-sec"><div class="chw-dt-lab">Variations · ${variants.length}</div><div class="chw-vchips">`
          + variants.map(v => `<button type="button" class="chw-vchip${String(v.label || '') === String(d.variant || '') ? ' is-on' : ''}"`
            + ` data-chw-var="${escHtml(v.label || '')}">${escHtml(v.name || 'Default')}<b>${n(v.rows)}</b></button>`).join('')
          + `</div></div>`
        : '')
      + sec('Personal Color', sections.personal_color, ' is-pc')
      + sec('Characteristics', sections.characteristics, '')
      + sec('Attire', sections.attire, ' is-at')
      + `</div>`
      + `<div class="chw-dt-prompt" title="생성 옵션의 저장값으로 만든 캐릭터 줄">${escHtml(String(d.prompt?.character_prompt || ''))}</div>`;
  }
  function pickVariant(label) {
    if (!selected) return;
    selVariant = String(label || '');
    // 슬롯도 그 변형으로(고르기만 해도 담기 - 같은 규칙).
    try {
      win.dispatchEvent(new CustomEvent('naia:character-picked',
        {detail: {group: selected.group, character: selected.character, variant: selVariant}}));
    } catch (_) {}
    paintSel();
    void loadDetail();
    void loadLine();
  }

  /** 작품 그룹으로 바로 간다(사용자 지시 2026-10-22 - 칸 · 아래 줄의 작품명 링크 · 우클릭). 그룹 목록도 그 자리로 굴린다. */
  function jumpToGroup(key) {
    if (!key) return;
    state.group = key;
    groupQuery = '';
    const gq = el('[data-chw-gq]'); if (gq) gq.value = '';
    const list = el('[data-chw-glist]');
    const index = shownGroups().findIndex(g => g.key === key);
    if (list && index >= 0) list.scrollTop = Math.max(0, index * GROUP_ROW - list.clientHeight / 2 + GROUP_ROW);
    paintGroups(); resetResults();
  }

  function onClick(event) {
    const t = event.target;
    // 작품명 링크는 칸(고르기)보다 먼저 - 칸 안에 있다.
    const go = t.closest('[data-chw-goto]');
    if (go) { event.preventDefault(); jumpToGroup(go.dataset.chwGoto); return; }
    const cell = t.closest('[data-chw-i]');
    if (cell) { const item = itemAt(Number(cell.dataset.chwI)); if (item) void select(item); return; }
    const g = t.closest('[data-chw-g]');
    if (g) { state.group = g.dataset.chwG || '__ALL__'; paintGroups(); resetResults(); return; }
    const gender = t.closest('[data-chw-gender]');
    if (gender) {
      state.gender = gender.dataset.chwGender;
      try { storage?.setItem(GENDER_KEY, state.gender); } catch (_) {}
      paintTools(); resetResults(); void loadGroups(); return;
    }
    if (t.closest('[data-chw-fav]')) { state.fav = !state.fav; paintTools(); resetResults(); return; }
    const lb = t.closest('[data-chw-lang]');
    if (lb) {
      lang = lb.dataset.chwLang === 'en' ? 'en' : 'ko';
      try { storage?.setItem(LANG_KEY, lang); } catch (_) {}
      paintFeat(); paintGroups(); paintGrid(); paintSel(); return;
    }
    const fs = t.closest('[data-chw-fs]');
    if (fs) { pickSuggestion(Number(fs.dataset.chwFs)); el(`[data-chw-fl="${feat.line}"]`)?.focus(); return; }
    if (t.closest('[data-chw-fmove]')) {
      // 필터 칸의 글을 이름 검색 칸으로 옮긴다.
      const text = feat.text.trim();
      const ft = el(`[data-chw-fl="${feat.line}"]`); if (ft) ft.value = '';
      feat.text = ''; feat.rows = []; feat.show = false; paintFeat();
      const q = el('[data-chw-q]');
      if (q) { q.value = text; q.focus(); }
      state.query = text; seq += 1; resetResults();
      return;
    }
    const chip = t.closest('[data-chw-unchip]');
    if (chip) {
      const same = term => term.tag === chip.dataset.chwTag && term.kind === chip.dataset.chwKind;
      if (chip.dataset.chwUnchip === 'exc') state.exc = state.exc.filter(x => !same(x));
      else state.inc = state.inc.filter(x => !same(x));
      paintTools(); paintFeat(); resetResults(); return;
    }
    const dm = t.closest('[data-chw-drawer-mode]');
    if (dm) { const m = dm.dataset.chwDrawerMode; void setDrawer(drawerMode === m ? null : m); return; }
    const vb = t.closest('[data-chw-var]');
    if (vb) { pickVariant(vb.dataset.chwVar); return; }
    const a = t.closest('[data-chw-act]');
    if (a && a.dataset.chwDtC !== undefined && (!selected || a.dataset.chwDtG !== selected.group
      || a.dataset.chwDtC !== selected.character || a.dataset.chwDtV !== selVariant)) return;   // 옛 상세의 단추
    if (a) void act(a.dataset.chwAct);
  }

  function onInput(event) {
    if (event.target.closest('[data-chw-q]')) {
      state.query = event.target.value || '';
      seq += 1;                                     // 입력하는 즉시 옛 응답을 무효로(디바운스 중 반영 금지 - 성능 리뷰)
      clearTimeout(queryTimer);
      queryTimer = setTimeout(resetResults, 150);
      return;
    }
    if (event.target.closest('[data-chw-gq]')) {
      groupQuery = event.target.value || '';
      const list = el('[data-chw-glist]'); if (list) list.scrollTop = 0;
      paintGroups();
      return;
    }
    const ft = event.target.closest('[data-chw-ft]');
    if (ft) { feat.line = ft.dataset.chwFl; feat.text = ft.value || ''; feat.show = true; suggest(); }
  }

  // 자동완성 손버릇: ↑ ↓ 고르기 · Enter 넣기 · Esc 닫기(조합 중 키는 입력기의 것).
  function onKey(event) {
    if (!event.target.closest('[data-chw-ft]') || event.isComposing || event.keyCode === 229) return;
    const rows = shownSuggestions();
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!rows.length) return;
      event.preventDefault();
      feat.show = true;
      feat.active = (feat.active + (event.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
      paintFeat();
    } else if (event.key === 'Enter') {
      if (!rows.length) return;
      event.preventDefault();
      pickSuggestion(feat.active);
    } else if (event.key === 'Escape') {
      if (!feat.show) return;
      event.preventDefault();
      event.stopPropagation();
      feat.show = false;
      paintFeat();
    }
  }

  // ── 바깥 ─────────────────────────────────────────────────────────────────────
  function open() {
    ensurePanel();
    if (panel.isOpen()) panel.raise(); else panel.open();
    if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
    paintTools(); paintSel(); paintFeat();
    if (!groups.length) void loadGroups();
    resetResults();
  }

  return {
    open,
    /** 탭 단추 규칙(Artist 와 같다) - 창을 세웠으면 false(탭으로 가지 않는다), 이미 펴져 있으면 true(탭으로). */
    requestTab() {
      if (!panel || !panel.isOpen() || (panel.isCollapsed && panel.isCollapsed())) { open(); return false; }
      return true;
    },
    isOpen: () => !!(panel && panel.isOpen()),
    refresh: () => { if (panel && panel.isOpen()) resetResults(); },
    /** 생성 설정 조각이 떠 있는 창(Find ⚙)으로 옮겨 갔다 - 빈 서랍을 닫는다. */
    // 조각을 가져간 쪽이 부른다 - 그 이동을 무르면 안 되니 서랍만 접는다(setDrawer(false) 는 기다리는 열기를 무른다).
    closeDrawer: () => {
      if (drawerMode !== 'gen') return;            // 상세보기가 열려 있으면 그대로 둔다
      drawerMode = null;
      const box = el('[data-chw-drawer]');
      if (box) box.hidden = true;
      paintSel();
    },
  };
}
