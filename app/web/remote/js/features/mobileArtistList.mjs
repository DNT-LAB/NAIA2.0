// 휴대폰용 Artists 목록(사용자 지정 2026-11-06) - PC 의 Artist Thumbnail 탭을 줄이지 않고 따로 만든 간소판.
// 지금은 **보기만** 한다: 모드 · 목록(전체/관심/제외/모델) · 이름 검색 · 썸네일 격자(아래로 내리면 더 읽음) ·
// 누르면 크게 보기. 데이터는 PC 탭과 같은 라우트(/api/artist-thumb/state · /list)를 그대로 쓴다.
// 서버 상태를 바꾸는 요청은 하나도 보내지 않는다.

const PAGE_SIZE = 48;
const MODE_KEY = 'naia.mobileArtists.mode';
const FILTER_KEY = 'naia.mobileArtists.filter';

export function createMobileArtistList({document, window, escHtml, showToast, storage}) {
  let root = null;
  let els = {};
  let state = null;
  let items = [];
  let page = 0;          // 마지막으로 읽은 쪽(0 = 아직)
  let totalPages = 0;
  let total = 0;
  let loading = false;
  let serial = 0;        // 조건이 바뀌면 올린다 - 늦게 온 옛 응답은 버린다
  let searchTimer = 0;

  const read = key => { try { return storage?.getItem(key) || ''; } catch { return ''; } };
  const write = (key, value) => { try { storage?.setItem(key, value); } catch { /* 저장 못 해도 화면은 돈다 */ } };
  const count = value => Number(value || 0).toLocaleString();

  function build() {
    root = document.createElement('div');
    root.className = 'mal-panel';
    root.hidden = true;
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-label', 'Artists');
    root.innerHTML = `
      <div class="mal-head">
        <span class="mal-title">Artists</span>
        <button type="button" class="mal-close" data-mal-close aria-label="닫기">&#10005;</button>
      </div>
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
      <div class="mal-viewer" data-mal-viewer hidden>
        <button type="button" class="mal-close mal-viewer-close" data-mal-viewer-close aria-label="닫기">&#10005;</button>
        <img class="mal-viewer-img" data-mal-viewer-img alt="">
        <div class="mal-viewer-info" data-mal-viewer-info></div>
      </div>`;
    document.body.appendChild(root);
    els = {
      mode: root.querySelector('[data-mal-mode]'),
      filter: root.querySelector('[data-mal-filter]'),
      query: root.querySelector('[data-mal-query]'),
      status: root.querySelector('[data-mal-status]'),
      scroll: root.querySelector('[data-mal-scroll]'),
      grid: root.querySelector('[data-mal-grid]'),
      more: root.querySelector('[data-mal-more]'),
      viewer: root.querySelector('[data-mal-viewer]'),
      viewerImg: root.querySelector('[data-mal-viewer-img]'),
      viewerInfo: root.querySelector('[data-mal-viewer-info]'),
    };
    root.querySelector('[data-mal-close]').addEventListener('click', close);
    root.querySelector('[data-mal-viewer-close]').addEventListener('click', closeViewer);
    els.viewer.addEventListener('click', event => { if (event.target === els.viewer) closeViewer(); });
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
    els.grid.addEventListener('click', event => {
      const card = event.target.closest('[data-mal-index]');
      if (card) openViewer(items[Number(card.dataset.malIndex)]);
    });
    // 아래 끝에 다가가면 다음 쪽을 읽는다(쪽 단추 대신 - 휴대폰에서는 내리는 쪽이 손에 익다).
    // 스크롤 이벤트로 잰다 - IntersectionObserver 는 그리기 프레임에 묶여 있어 창이 가려진 동안 안 불린다.
    els.scroll.addEventListener('scroll', () => { if (nearBottom()) void loadNext(); }, {passive: true});
  }

  function nearBottom() {
    const {scrollTop, scrollHeight, clientHeight} = els.scroll;
    return scrollHeight - scrollTop - clientHeight < 600;
  }

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

  function listUrl(pageNo) {
    const params = new URLSearchParams({
      mode: els.mode.value || '',
      filter: els.filter.value || 'all',
      query: els.query.value.trim(),
      page: String(pageNo),
      per_page: String(PAGE_SIZE),
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
    els.grid.innerHTML = '';
    els.scroll.scrollTop = 0;
    void loadNext();
  }

  async function loadNext() {
    if (loading || !root || root.hidden) return;
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
    // 읽는 동안 이미 끝까지 내렸거나 첫 쪽이 화면을 다 못 채우면(펼친 폴드) 스크롤이 다시 안 온다 - 직접 이어 읽는다.
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
    els.viewer.hidden = true;
    els.viewerImg.removeAttribute('src');
  }

  async function open() {
    if (!root) build();
    root.hidden = false;
    document.documentElement.classList.add('mal-open');
    if (state) {
      if (!items.length) reload();
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
    if (!root) return;
    closeViewer();
    root.hidden = true;
    document.documentElement.classList.remove('mal-open');
  }

  return {open, close, isOpen: () => Boolean(root && !root.hidden)};
}
