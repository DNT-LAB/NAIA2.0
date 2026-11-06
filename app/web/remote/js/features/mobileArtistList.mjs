// 휴대폰용 Artists 판(사용자 지정 2026-11-06) - PC 의 Artist Thumbnail 탭을 줄이지 않고 따로 만든 간소판.
// 하는 일은 둘뿐이다(사용자 지정):
//   1) 보고 태그 복사 - 누르면 고르기만(잘못 눌러도 복사되지 않게) · 아래 줄 [태그 복사] 로 복사.
//   2) 랜덤 생성에 이 목록 연결 - PC 의 [메인 랜덤 버튼 연결](main_link)과 **같은 서버 설정**이다. 켜면 뽑는 목록을
//      이 판의 모드 · 목록 · 이름 검색으로 바꾼다(PC 에 저장된 매칭 검색 · 구간은 풀린다 - 사용자 결정 2026-11-06).
//      메인 Random 을 누를 때마다 서버가 그 목록에서 한 명을 뽑는다 - 판을 접어도 · 닫아도 돈다.
// 창은 앱 표준 떠 있는 창(draggablePanel)이다 - 머리줄 끌기 · 오른쪽 아래 손잡이로 크기 · [–] 접기(머리줄만 남는다) ·
// 화면 밖 방지 · 가장자리 붙기를 그대로 쓴다. 이 판은 손가락 크기만 키운다(style.css `.dragpanel.mal`).
// 데이터는 PC 탭과 같은 라우트(/api/artist-thumb/state · /list · /random-tools · /options)를 쓴다.

// ⚠️ 다른 창들과 **같은 주소**로 읽는다 - 주소가 다르면 모듈이 둘이 되어 창 앞뒤 순서(REGISTRY)가 갈린다.
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const PAGE_SIZE = 48;
const MODE_KEY = 'naia.mobileArtists.mode';
const FILTER_KEY = 'naia.mobileArtists.filter';
const COLS_KEY = 'naia.mobileArtists.cols';
const COL_CHOICES = [1, 2, 3, 4];     // 한 줄 최대 4칸(사용자 지정)
const DEFAULT_COLS = 3;

export function createMobileArtistList({
  document, window, escHtml, showToast, storage,
  getGenerationMode = () => 'NAI', isAnimaArtistMode = () => false,
}) {
  let panel = null;
  let els = {};
  let state = null;
  let items = [];
  let selected = null;
  let page = 0;          // 마지막으로 읽은 쪽(0 = 아직)
  let totalPages = 0;
  let total = 0;
  let loading = false;
  let serial = 0;        // 조건이 바뀌면 올린다 - 늦게 온 옛 응답은 버린다
  let searchTimer = 0;
  let linkOn = false;    // 서버의 main_link(이 판이 마지막으로 안 값)
  let linkBusy = false;

  const read = key => { try { return storage?.getItem(key) || ''; } catch { return ''; } };
  const write = (key, value) => { try { storage?.setItem(key, value); } catch { /* 저장 못 해도 화면은 돈다 */ } };
  const count = value => Number(value || 0).toLocaleString();
  const savedCols = () => {
    const n = Number.parseInt(read(COLS_KEY), 10);
    return COL_CHOICES.includes(n) ? n : DEFAULT_COLS;
  };

  // ── 만들기 ───────────────────────────────────────────────────────────────
  function build() {
    const vw = window.innerWidth || 412;
    const vh = window.innerHeight || 800;
    panel = createDraggablePanel({
      document, window, escHtml,
      title: 'Artists',
      variant: 'mal',
      storageKey: 'mobile-artists',
      storage,
      width: Math.max(260, Math.min(vw - 12, 560)),
      height: Math.round(vh * 0.7),
      minWidth: 240,
      minHeight: 220,
      maxWidth: 1600,
      resizable: true,
      edgeSnap: 10,
      initial: {x: 6, y: 52},
      onCollapse: () => paintLink(linkOn),
    });

    // 머리줄 = [Artists] [1 2 3 4] [●연결] ... [–] [×]
    panel.slot.innerHTML = `
      <span class="mal-cols" role="group" aria-label="한 줄에 몇 칸">
        ${COL_CHOICES.map(n => `<button type="button" class="mal-col" data-mal-cols="${n}" aria-label="한 줄 ${n}칸">${n}</button>`).join('')}
      </span>
      <span class="mal-linkdot" data-mal-linkdot hidden title="랜덤 생성에 연결됨"></span>`;

    panel.body.innerHTML = `
      <div class="mal-controls">
        <select class="mod-select" data-mal-mode aria-label="모드"></select>
        <select class="mod-select" data-mal-filter aria-label="목록"></select>
      </div>
      <div class="mal-search-row">
        <input type="search" class="mal-search" data-mal-query placeholder="작가 이름 검색" autocomplete="off"
               autocapitalize="off" spellcheck="false" enterkeyhint="search">
      </div>
      <div class="mal-status" data-mal-status></div>
      <div class="mal-scroll" data-mal-scroll>
        <div class="mal-grid" data-mal-grid></div>
        <div class="mal-more" data-mal-more></div>
      </div>
      <div class="mal-pick" data-mal-pick hidden>
        <button type="button" class="mal-pick-thumb" data-mal-zoom aria-label="크게 보기"></button>
        <span class="mal-pick-text"><b data-mal-pick-name></b><span data-mal-pick-meta></span></span>
        <button type="button" class="mal-copy" data-mal-copy>태그 복사</button>
      </div>
      <label class="mal-link">
        <input type="checkbox" data-mal-link>
        <span class="mal-switch" aria-hidden="true"></span>
        <span class="mal-link-text">랜덤 생성에 이 목록 연결</span>
      </label>`;

    // 크게 보기는 창 전체(머리줄 아래)를 덮는다 - 본문은 스크롤 상자라 창에 붙인다.
    const viewer = document.createElement('div');
    viewer.className = 'mal-viewer';
    viewer.hidden = true;
    viewer.innerHTML = `
      <button type="button" class="mal-viewer-close" data-mal-viewer-close aria-label="닫기">&#10005;</button>
      <img class="mal-viewer-img" data-mal-viewer-img alt="">
      <div class="mal-viewer-info" data-mal-viewer-info></div>`;
    panel.el.appendChild(viewer);

    const q = sel => panel.el.querySelector(sel);
    els = {
      mode: q('[data-mal-mode]'),
      filter: q('[data-mal-filter]'),
      query: q('[data-mal-query]'),
      status: q('[data-mal-status]'),
      scroll: q('[data-mal-scroll]'),
      grid: q('[data-mal-grid]'),
      more: q('[data-mal-more]'),
      pick: q('[data-mal-pick]'),
      pickThumb: q('[data-mal-zoom]'),
      pickName: q('[data-mal-pick-name]'),
      pickMeta: q('[data-mal-pick-meta]'),
      link: q('[data-mal-link]'),
      linkDot: q('[data-mal-linkdot]'),
      viewer,
      viewerImg: q('[data-mal-viewer-img]'),
      viewerInfo: q('[data-mal-viewer-info]'),
    };

    panel.slot.addEventListener('click', event => {
      const button = event.target.closest('[data-mal-cols]');
      if (!button) return;
      write(COLS_KEY, button.dataset.malCols);
      paintCols();
    });
    // 크게 보기는 **아무 데나** 누르면 닫힌다(사용자 지정 2026-11-06 - 그림 위를 눌러도).
    viewer.addEventListener('click', closeViewer);
    els.mode.addEventListener('change', () => { write(MODE_KEY, els.mode.value); reload(); });
    els.filter.addEventListener('change', () => { write(FILTER_KEY, els.filter.value); reload(); });
    els.query.addEventListener('input', () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(reload, 400);
    });
    els.query.addEventListener('keydown', event => {
      if (event.key !== 'Enter') return;
      window.clearTimeout(searchTimer);
      els.query.blur();   // 휴대폰 자판을 내린다
      reload();
    });
    // 누르면 고르기만 한다 - 복사는 아래 줄 단추로(사용자 지정: 넘겨 보다 잘못 눌러도 복사되지 않게).
    els.grid.addEventListener('click', event => {
      const card = event.target.closest('[data-mal-index]');
      if (card) select(Number(card.dataset.malIndex));
    });
    els.pickThumb.addEventListener('click', () => openViewer(selected));
    q('[data-mal-copy]').addEventListener('click', () => void copySelected());
    els.link.addEventListener('change', () => void setLink(els.link.checked));
    // 아래 끝에 다가가면 다음 쪽을 읽는다. 스크롤 이벤트로 잰다 - IntersectionObserver 는 그리기 프레임에
    // 묶여 있어 창이 가려진 동안 안 불린다.
    els.scroll.addEventListener('scroll', () => { if (nearBottom()) void loadNext(); }, {passive: true});
    // 크기를 늘려도 오른쪽 아래 손잡이는 화면 안에 남긴다 - 휴대폰은 화면 밖으로 넘친 손잡이를 다시 잡을 길이 없다
    // (표준 창은 PC 용이라 넘침을 허용한다). 끄는 동안마다 오는 `dragpanel-resize` 에서 깎는다.
    panel.el.addEventListener('dragpanel-resize', keepGripOnScreen);
    paintCols();
  }

  function keepGripOnScreen() {
    const rect = panel.el.getBoundingClientRect();
    const maxW = Math.floor((window.innerWidth || 0) - Math.max(0, rect.left) - 4);
    const maxH = Math.floor((window.innerHeight || 0) - Math.max(0, rect.top) - 4);
    if (maxW > 200 && rect.width > maxW) panel.el.style.width = `${maxW}px`;
    if (maxH > 160 && rect.height > maxH && !panel.isCollapsed()) panel.el.style.height = `${maxH}px`;
  }

  function paintCols() {
    const cols = savedCols();
    els.grid.style.setProperty('--mal-cols', String(cols));
    panel.slot.querySelectorAll('[data-mal-cols]').forEach(button => {
      button.setAttribute('aria-pressed', String(Number(button.dataset.malCols) === cols));
    });
    // 칸을 줄이면 읽은 것이 화면을 못 채울 수 있다 - 이어 읽는다.
    if (state && nearBottom()) void loadNext();
  }

  // ── 목록 ─────────────────────────────────────────────────────────────────
  async function loadState() {
    const response = await fetch('/api/artist-thumb/state', {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    state = data;
    const modes = (state.modes || []).filter(mode => mode.available || mode.virtual);
    const savedMode = read(MODE_KEY);
    els.mode.innerHTML = modes.map(mode =>
      `<option value="${escHtml(mode.key)}">${escHtml(mode.label || mode.key)}</option>`).join('');
    els.mode.value = modes.some(mode => mode.key === savedMode) ? savedMode : (modes[0]?.key || '');
    const filters = state.filters || [];
    const savedFilter = read(FILTER_KEY) || 'all';
    els.filter.innerHTML = filters.map(item => item.separator
      ? `<option disabled>── ${escHtml(item.name || '')} ──</option>`
      : `<option value="${escHtml(item.key)}">${escHtml(item.name || item.key)} (${count(item.count)})</option>`).join('');
    els.filter.value = filters.some(item => !item.separator && item.key === savedFilter) ? savedFilter : 'all';
  }

  function currentPool() {
    return {mode: els.mode.value || '', filter: els.filter.value || 'all', query: els.query.value.trim(), search: null};
  }

  function listUrl(pageNo) {
    const pool = currentPool();
    const params = new URLSearchParams({
      mode: pool.mode, filter: pool.filter, query: pool.query, page: String(pageNo), per_page: String(PAGE_SIZE),
    });
    return `/api/artist-thumb/list?${params}`;
  }

  function reload() {
    serial += 1;
    items = [];
    page = 0;
    totalPages = 0;
    total = 0;
    loading = false;
    select(-1);
    els.grid.innerHTML = '';
    els.scroll.scrollTop = 0;
    void loadNext();
    // 연결이 켜져 있으면 뽑는 목록도 지금 보는 목록을 따라간다.
    if (linkOn) void setLink(true, {quiet: true});
  }

  function nearBottom() {
    const {scrollTop, scrollHeight, clientHeight} = els.scroll;
    return scrollHeight - scrollTop - clientHeight < 600;
  }

  async function loadNext() {
    if (loading || !panel?.isOpen() || panel.isCollapsed()) return;
    if (page > 0 && page >= totalPages) return;
    if (!els.mode.value) { renderStatus('받아 둔 썸네일 팩이 없습니다 - PC 화면의 Artist Thumbnail 에서 받으세요'); return; }
    const mine = serial;
    loading = true;
    renderStatus(page ? `${count(total)}명 · 더 읽는 중…` : '불러오는 중…');
    try {
      const response = await fetch(listUrl(page + 1), {cache: 'no-store'});
      const data = await response.json().catch(() => ({}));
      if (mine !== serial) return;
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      const start = items.length;
      const added = Array.isArray(data.items) ? data.items : [];
      items.push(...added);
      page = Number(data.page || page + 1);
      totalPages = Number(data.total_pages || 0);
      total = Number(data.total || 0);
      els.grid.insertAdjacentHTML('beforeend', added.map((item, i) => cardHtml(item, start + i)).join(''));
      renderStatus();
    } catch (error) {
      if (mine !== serial) return;
      renderStatus(`목록을 못 읽었습니다: ${error.message || error}`);
    } finally {
      if (mine === serial) loading = false;
    }
    // 읽는 동안 이미 끝까지 내렸거나 첫 쪽이 화면을 다 못 채우면(창을 키움) 스크롤이 다시 안 온다 - 직접 이어 읽는다.
    if (mine === serial && page < totalPages && nearBottom()) void loadNext();
  }

  function cardHtml(item, index) {
    const name = escHtml(item.artist || '');
    const image = item.image_url
      ? `<img loading="lazy" decoding="async" src="${escHtml(item.image_url)}" alt="">`
      : '<span class="mal-noimg">No Image</span>';
    const marks = (item.favorite ? '<span class="mal-mark mal-fav" title="관심 작가">&#9733;</span>' : '')
      + (item.banned ? '<span class="mal-mark mal-ban" title="제외 작가">&#8856;</span>' : '');
    return `<button type="button" class="mal-card${item.banned ? ' is-banned' : ''}" data-mal-index="${index}">`
      + `<span class="mal-thumb">${image}${marks}</span>`
      + `<span class="mal-name">${name}</span></button>`;
  }

  function renderStatus(text) {
    if (text !== undefined) { els.status.textContent = text; return; }
    if (!total) {
      els.status.textContent = els.query.value.trim() ? '찾은 작가가 없습니다' : '목록이 비었습니다';
      els.more.textContent = '';
      return;
    }
    els.status.textContent = `${count(total)}명 · ${count(items.length)}명 보는 중`;
    els.more.textContent = page < totalPages ? '' : '끝';
  }

  // ── 고르기 · 복사 ────────────────────────────────────────────────────────
  function select(index) {
    els.grid.querySelector('.mal-card.is-selected')?.classList.remove('is-selected');
    selected = items[index] || null;
    els.pick.hidden = !selected;
    if (!selected) return;
    els.grid.querySelector(`[data-mal-index="${index}"]`)?.classList.add('is-selected');
    els.pickThumb.innerHTML = selected.image_url ? `<img src="${escHtml(selected.image_url)}" alt="">` : '';
    els.pickName.textContent = selected.artist || '';
    const weight = Number(selected.weight || 0);
    els.pickMeta.textContent = weight ? `게시물 ${count(weight)}` : '';
  }

  /** PC 탭의 기본 서식과 같다(artistThumbTab.baseArtistPrompt): NAI = artist:이름 · ANIMA = @이름 · 그 밖 = 이름.
   *  SD 계열은 괄호를 이스케이프한다. */
  function artistTag(name) {
    const artist = String(name || '').trim();
    if (!artist) return '';
    if (String(getGenerationMode?.() || 'NAI').trim().toUpperCase() === 'NAI') return `artist:${artist}`;
    const escaped = artist.replace(/[()]/g, '\\$&');
    return isAnimaArtistMode?.() ? `@${escaped}` : escaped;
  }

  /** 휴대폰은 LAN 주소(http)로 들어온다 - 안전한 출처가 아니라 navigator.clipboard 가 없다. 그때는 옛 길(execCommand). */
  async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return true; } catch { /* 옛 길로 */ }
    }
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px';
    document.body.appendChild(area);
    let ok = false;
    try {
      area.focus();
      area.select();
      area.setSelectionRange(0, text.length);
      ok = document.execCommand('copy');
    } catch { ok = false; } finally { area.remove(); }
    return ok;
  }

  async function copySelected() {
    const tag = artistTag(selected?.artist);
    if (!tag) return;
    const ok = await copyText(tag);
    showToast?.(ok ? `${tag} 복사됨` : '복사하지 못했습니다', ok ? 'success' : 'error');
  }

  // ── 랜덤 생성 연결 ───────────────────────────────────────────────────────
  async function refreshLink() {
    try {
      const response = await fetch('/api/artist-thumb/random-tools', {cache: 'no-store'});
      const tools = await response.json().catch(() => ({}));
      if (response.ok && !tools.error) paintLink(Boolean(tools.main_link));
    } catch { /* 표시는 다음 기회에 */ }
  }

  function paintLink(on) {
    linkOn = on;
    if (!els.link) return;
    els.link.checked = on;
    els.linkDot.hidden = !on;
  }

  /** 켜기 = main_link + 뽑는 목록을 이 판의 목록으로(출처 = 아티스트 탭 · 구간 전체 · 매칭 검색 없음). 끄기 = main_link 만. */
  async function setLink(on, {quiet = false} = {}) {
    if (on && !els.mode.value) { paintLink(false); showToast?.('받아 둔 썸네일 팩이 없습니다', 'error'); return; }
    if (linkBusy && quiet) return;
    linkBusy = true;
    const randomTools = on
      ? {main_link: true, pool: currentPool(), source: {kind: 'tab', id: ''}, range: [0, 100]}
      : {main_link: false};
    try {
      const response = await fetch('/api/artist-thumb/options', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({random_tools: randomTools}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      paintLink(Boolean(data.random_tools?.main_link ?? on));
      if (!quiet) {
        showToast?.(on ? '메인 Random 마다 이 목록에서 작가 한 명을 붙입니다' : '랜덤 작가 연결을 껐습니다', 'info');
      }
    } catch (error) {
      paintLink(linkOn);   // 서버는 그대로다 - 스위치를 되돌린다
      showToast?.(`연결을 바꾸지 못했습니다: ${error.message || error}`, 'error');
    } finally {
      linkBusy = false;
    }
  }

  // ── 크게 보기 ────────────────────────────────────────────────────────────
  function openViewer(item) {
    if (!item) return;
    els.viewerImg.src = item.image_url || '';
    els.viewerImg.hidden = !item.image_url;
    const weight = Number(item.weight || 0);
    els.viewerInfo.innerHTML = `<b>${escHtml(item.artist || '')}</b>`
      + (weight ? `<span>게시물 ${count(weight)}</span>` : '')
      + (item.favorite ? '<span>&#9733; 관심 작가</span>' : '')
      + (item.banned ? '<span>제외 작가</span>' : '');
    els.viewer.hidden = false;
  }

  function closeViewer() {
    if (!els.viewer) return;
    els.viewer.hidden = true;
    els.viewerImg.removeAttribute('src');
  }

  // ── 열기 · 닫기 ──────────────────────────────────────────────────────────
  async function open() {
    if (!panel) build();
    panel.open();
    if (panel.isCollapsed()) panel.expand();   // 리모트에서 다시 부르면 펼쳐서 보여 준다
    void refreshLink();
    if (state) {
      if (!items.length && !loading) reload();
      return;
    }
    renderStatus('불러오는 중…');
    try {
      await loadState();
      reload();
    } catch (error) {
      renderStatus(`작가 목록을 못 열었습니다: ${error.message || error}`);
      showToast?.('Artists 목록을 못 열었습니다', 'error');
    }
  }

  function close() {
    closeViewer();
    panel?.close();
  }

  return {open, close, isOpen: () => Boolean(panel?.isOpen())};
}
