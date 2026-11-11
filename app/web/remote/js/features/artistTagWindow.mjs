// [자동화 / 고급 기능] > [아티스트 태그 관리](사용자 지시 2026-11-11) - 메인 프롬프트에 쓴 작가를 썸네일 타일로 보여 준다.
//
//   - **부른 그때 한 번** 읽는다. 프롬프트를 고쳐도 따라가지 않는다 - 다시 열면 그때의 프롬프트로 다시 읽는다.
//   - 메인 프롬프트만 본다(네거티브 · 캐릭터 프롬프트는 보지 않는다).
//   - 그림은 서버가 팩을 통째로 올리지 않고 그 작가의 자리만 읽어 낸다(core/artist_pack_index). 처음 여는 팩은
//     자리 색인을 만드느라 몇 초가 든다 - 그동안 '찾는 중' 을 보여 준다.
//   - 작가의 그림은 여러 팩에 나뉘어 있다. 받은 팩 어디에도 없으면 그 타일은 '데이터 없음'.
//   - 타일에 마우스를 올리면 창 옆에 크게 뜬다 - Artist Thumbnail 리모컨의 확대 상자를 그대로 쓴다
//     (remoteController.showZoomBeside · 사용자 지시 2026-11-11 "기존 Artist Thumbnail 의 기능을 점검"). 폭만 넓힌다(is-wide).
//   - 타일 우클릭 = [이 아티스트로만 생성](사용자 지시 2026-11-11 - 이 창을 만든 까닭): [현재 프롬프트로] · [랜덤+생성] + 가중치.
//     다른 작가를 전부 걷고 이 작가만 넣은 글로 한 장 생성한다. 글을 만들고 보내는 것은 app.js(soloGenerate) - 프롬프트 칸은
//     바꾸지 않는다(랜덤+생성은 Random 을 누른 것과 같아 칸이 새 글로 바뀐다).
// 껍데기는 다른 떠 있는 창과 같다(em-overlay em-window). 옷은 이 파일이 직접 넣는다(style.css 를 건드리지 않는다).

import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'atw-style';
const ATW_CSS = `
.atw-window .dragpanel-body { display: flex; flex-direction: column; min-height: 0; padding: 0; }
.atw-count { font-family: var(--font-mono); font-size: 11px; color: var(--text-dim); }
.atw-note { margin: auto; padding: 24px 16px; text-align: center; font-size: 12px; line-height: 1.6; color: var(--text-dim); }
.atw-note.is-error { color: #ffb4b4; }
.atw-grid { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 10px;
  /* 한 줄에 많아야 넷(사용자 지시 2026-11-11 - 작으면 안 보인다). 넷이 들어갈 폭(25% - 틈)을 하한으로 두면 넓은 창에서도
     다섯째가 못 들어온다. 좁은 창에서는 120px 하한으로 셋 · 둘로 준다. */
  display: grid; grid-template-columns: repeat(auto-fill, minmax(max(120px, calc(25% - 6px)), 1fr)); gap: 8px; align-content: start;
  /* 줄 높이를 내용에 맞춘다 - 안 하면 타일(overflow hidden)이 창 높이에 맞춰 눌려 이름 줄이 잘린다(실측 150 -> 77px). */
  grid-auto-rows: max-content; }
.atw-tile { min-width: 0; border: 1px solid var(--border-dim); border-radius: 6px; overflow: hidden; background: var(--bg-surface); }
.atw-img { display: block; width: 100%; aspect-ratio: 3 / 4; object-fit: cover; background: #0c0c12; }
.atw-none { display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 3 / 4;
  background: #0c0c12; color: var(--text-dim); font-size: 11px; }
.atw-name { padding: 6px 6px 0; font-size: 13px; color: var(--text-primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.atw-meta { display: flex; justify-content: space-between; gap: 8px; padding: 2px 6px 6px;
  font-family: var(--font-mono); font-size: 12px; color: var(--text-dim); }
.atw-weight { color: var(--text-primary); }
.atw-weight.is-neg { color: #ff8f8f; }
.atw-tile.is-menu { border-color: var(--accent); }
.atw-menu { position: fixed; z-index: calc(var(--z-drag-panel-zoom, 10195) + 5); width: 250px;
  background: var(--bg-elevated); border: 1px solid var(--border-glow); border-radius: 10px;
  box-shadow: 0 14px 40px rgba(0,0,0,0.6); overflow: hidden; user-select: none; }
.atw-menu[hidden] { display: none !important; }
.atw-menu-head { padding: 8px 12px; font-size: 13px; font-weight: 600; color: var(--text-primary);
  border-bottom: 1px solid var(--border-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.atw-menu-sec { padding: 8px 12px 2px; font-size: 11px; color: var(--text-dim); }
.atw-menu-item { display: block; width: 100%; padding: 7px 12px; border: 0; background: transparent; cursor: pointer;
  text-align: left; font-size: 13px; color: var(--text-primary); font-family: inherit; }
.atw-menu-item:hover, .atw-menu-item:focus-visible { background: var(--bg-hover); outline: none; }
.atw-menu-weight { display: flex; align-items: center; gap: 8px; margin-top: 4px; padding: 8px 12px 10px;
  border-top: 1px solid var(--border-dim); font-size: 12px; color: var(--text-muted); }
.atw-menu-weight input { flex: 1 1 auto; min-width: 0; }
.atw-menu-weight b { min-width: 34px; text-align: right; font-family: var(--font-mono); font-weight: 600; color: var(--text-primary); }
.rctl-zoom.is-wide { width: 460px; max-width: 46vw; }
.rctl-zoom.is-wide img { max-height: 82vh; }
.rctl-zoom.is-wide .rctl-zoom-cap b { font-size: 14px; }
.rctl-zoom.is-wide .rctl-zoom-cap span { font-size: 12px; }
`;

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = ATW_CSS;
  doc.head.appendChild(style);
}

function shortCount(value) {
  const n = Number(value) || 0;
  if (n <= 0) return '';
  if (n < 1000) return String(n);
  const k = n / 1000;
  return `${k >= 10 ? Math.round(k) : Math.round(k * 10) / 10}k`;
}

export function createArtistTagWindow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  fetch: fetchFn = win.fetch.bind(win),
  // 지금의 메인 프롬프트 글.
  getPrompt = () => '',
  // Artist Thumbnail 에서 고른 모드(팩 계열을 정한다). 모르면 빈 글 - 서버가 API 모드로 고른다.
  getThumbMode = () => '',
  escHtml = v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  onVisibilityChange = () => {},
  // 창 옆에 크게 보기 · 걷기(리모컨의 확대 상자). 없으면 올려도 아무 일도 없다.
  showZoom = null,
  hideZoom = () => {},
  // [이 아티스트로만 생성] - {artist, weight, random} 으로 한 장 생성한다(app.js). 보냈으면 true, 못 보냈으면 까닭(글) 또는 false.
  // 없으면 우클릭 메뉴를 띄우지 않는다.
  soloGenerate = null,
  notify = () => {},
}) {
  ensureStyle(doc);
  let serial = 0;      // 늦게 온 응답이 새 목록을 덮지 않게
  const panel = createDraggablePanel({
    document: doc, window: win, id: 'artistTagWindow', title: '아티스트 태그 관리',
    variant: 'em-overlay em-window atw-window', storageKey: 'artist-tag-manager',
    width: 560, height: 520, minWidth: 260, maxWidth: 960, minHeight: 200, resizable: true,
    escHtml,
    onOpen: () => { load(); onVisibilityChange(); },
    onClose: () => { serial += 1; leaveTile(); closeMenu(); onVisibilityChange(); },
  });
  const count = doc.createElement('span');
  count.className = 'atw-count';
  panel.slot.append(count);

  function note(text, isError = false) {
    panel.body.innerHTML = `<div class="atw-note${isError ? ' is-error' : ''}">${escHtml(text)}</div>`;
  }

  function tileHtml(row) {
    const name = String(row.name || '');
    const posts = shortCount(row.count);
    const weight = Number.isFinite(Number(row.weight)) ? Number(row.weight) : 1;
    const tip = row.image_url ? `${name} · ${row.pack_label || row.pack || ''}` : `${name} · 받은 팩에 이 작가의 그림이 없습니다`;
    const picture = row.image_url
      ? `<img class="atw-img" loading="lazy" alt="" src="${escHtml(row.image_url)}">`
      : '<div class="atw-none">데이터 없음</div>';
    return `<div class="atw-tile" title="${escHtml(tip)}" data-atw-artist="${escHtml(name)}" data-atw-weight="${escHtml(String(weight))}">${picture}`
      + `<div class="atw-name">${escHtml(name)}</div><div class="atw-meta">`
      + `<span class="atw-weight${weight < 0 ? ' is-neg' : ''}" title="가중치">${escHtml(String(weight))}</span>`
      + `<span title="게시물 수">${escHtml(posts)}</span></div></div>`;
  }

  async function load() {
    const mine = ++serial;
    count.textContent = '';
    note('작가를 찾는 중… 처음 여는 팩은 몇 초 걸립니다.');
    let data = null;
    try {
      const response = await fetchFn('/api/artist-thumb/used', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: String(getPrompt() || ''), mode: String(getThumbMode() || '')}),
      });
      data = await response.json();
      if (!response.ok || !data?.ok) throw new Error(data?.error || `HTTP ${response.status}`);
    } catch (error) {
      if (mine !== serial) return;
      note(`작가 목록을 읽지 못했습니다 - ${error?.message || error}`, true);
      return;
    }
    if (mine !== serial) return;
    const rows = Array.isArray(data.artists) ? data.artists : [];
    count.textContent = rows.length ? `${rows.length}명` : '';
    if (!rows.length) { note('메인 프롬프트에 작가 태그가 없습니다.'); return; }
    panel.body.innerHTML = `<div class="atw-grid">${rows.map(tileHtml).join('')}</div>`;
  }

  // ── 올리면 창 옆에 크게 ──────────────────────────────────────────────
  const HOVER_DELAY_MS = 140;      // 리모컨과 같은 뜸 - 지나가는 마우스에는 안 뜬다
  let hoverTile = null;
  let hoverTimer = null;

  function leaveTile() {
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
    if (hoverTile) { hoverTile = null; hideZoom(); }
  }

  panel.body.addEventListener('mouseover', event => {
    const tile = event.target?.closest?.('.atw-tile');
    if (menuTile) return;                 // 메뉴가 떠 있는 동안은 크게 보기를 띄우지 않는다(메뉴를 가린다)
    if (tile === hoverTile) return;
    leaveTile();
    const src = tile?.querySelector('.atw-img')?.getAttribute('src');
    if (!src || typeof showZoom !== 'function') return;      // '데이터 없음' 은 띄울 것이 없다
    hoverTile = tile;
    hoverTimer = (win || globalThis).setTimeout(() => {
      hoverTimer = null;
      if (hoverTile !== tile || !panel.isOpen()) return;
      showZoom(tile, {
        src,
        title: tile.querySelector('.atw-name')?.textContent || '',
        note: [...tile.querySelectorAll('.atw-meta span')].map(s => s.textContent).filter(Boolean).join(' · '),
        wide: true,
      }, panel.el.getBoundingClientRect());
    }, HOVER_DELAY_MS);
  });
  panel.body.addEventListener('mouseleave', leaveTile);
  panel.body.addEventListener('scroll', leaveTile, true);
  panel.el.addEventListener('dragpanel-move', leaveTile);

  // ── 우클릭 = 이 아티스트로만 생성 ────────────────────────────────────
  const WEIGHT_MIN = 0, WEIGHT_MAX = 2, WEIGHT_STEP = 0.01;    // 범위는 Artist Thumbnail 의 슬라이더와 같다. 눈금은 0.01 - 0.05 면 타일의 0.83 이 0.85 로 바뀐 채 시작한다
  let menuEl = null;
  let menuTile = null;
  let menuBusy = false;

  const weightText = value => String(Math.round(Number(value) * 100) / 100);

  function menuBox() {
    if (menuEl) return menuEl;
    menuEl = doc.createElement('div');
    menuEl.className = 'atw-menu';
    menuEl.hidden = true;
    menuEl.setAttribute('role', 'menu');
    menuEl.innerHTML = `
      <div class="atw-menu-head" data-atw-menu-name></div>
      <div class="atw-menu-sec">이 아티스트로만 생성</div>
      <button type="button" class="atw-menu-item" role="menuitem" data-atw-solo="current">현재 프롬프트로</button>
      <button type="button" class="atw-menu-item" role="menuitem" data-atw-solo="random">랜덤+생성</button>
      <label class="atw-menu-weight"><span>가중치</span>
        <input type="range" min="${WEIGHT_MIN}" max="${WEIGHT_MAX}" step="${WEIGHT_STEP}" data-atw-weight aria-label="가중치">
        <b data-atw-weight-out></b></label>`;
    doc.body.appendChild(menuEl);
    menuEl.addEventListener('input', event => {
      if (event.target?.matches?.('[data-atw-weight]')) {
        menuEl.querySelector('[data-atw-weight-out]').textContent = weightText(event.target.value);
      }
    });
    menuEl.addEventListener('click', event => {
      const item = event.target?.closest?.('[data-atw-solo]');
      if (item) void runSolo(item.dataset.atwSolo === 'random');
    });
    menuEl.addEventListener('contextmenu', event => event.preventDefault());
    return menuEl;
  }

  function closeMenu() {
    if (menuTile) menuTile.classList.remove('is-menu');
    menuTile = null;
    if (menuEl) menuEl.hidden = true;
  }

  function openMenu(tile, x, y) {
    leaveTile();
    closeMenu();
    const box = menuBox();
    menuTile = tile;
    tile.classList.add('is-menu');
    box.querySelector('[data-atw-menu-name]').textContent = tile.dataset.atwArtist || '';
    // 처음 값은 그 타일의 가중치. 슬라이더 범위 밖(0 이하 · 2 초과)이면 1 에서 시작한다.
    const own = Number(tile.dataset.atwWeight);
    const start = Number.isFinite(own) && own > WEIGHT_MIN && own <= WEIGHT_MAX ? own : 1;
    box.querySelector('[data-atw-weight]').value = String(start);
    box.querySelector('[data-atw-weight-out]').textContent = weightText(start);
    box.hidden = false;
    const view = win || doc.defaultView;
    const rect = box.getBoundingClientRect();
    box.style.left = `${Math.round(Math.max(6, Math.min(x, view.innerWidth - rect.width - 6)))}px`;
    box.style.top = `${Math.round(Math.max(6, Math.min(y, view.innerHeight - rect.height - 6)))}px`;
  }

  async function runSolo(random) {
    if (!menuTile || menuBusy) return;
    const artist = menuTile.dataset.atwArtist || '';
    const weight = Number(menuEl.querySelector('[data-atw-weight]').value);
    closeMenu();
    if (!artist) return;
    menuBusy = true;                      // 연타가 두 장이 되지 않게(랜덤+생성은 Random 응답을 기다린다)
    try {
      const sent = await soloGenerate({artist, weight, random});
      if (typeof sent === 'string' && sent) notify(sent, 'info');
    } catch (error) {
      notify(`생성을 보내지 못했습니다 - ${error?.message || error}`, 'error');
    } finally {
      menuBusy = false;
    }
  }

  panel.body.addEventListener('contextmenu', event => {
    const tile = event.target?.closest?.('.atw-tile');
    if (!tile || typeof soloGenerate !== 'function') return;
    event.preventDefault();
    openMenu(tile, event.clientX, event.clientY);
  });
  // 메뉴 밖을 누르거나 · Esc · 스크롤 · 창 이동이면 닫는다.
  doc.addEventListener('pointerdown', event => {
    if (menuTile && !menuEl.contains(event.target)) closeMenu();
  }, true);
  doc.addEventListener('keydown', event => {
    if (menuTile && event.key === 'Escape') { event.stopPropagation(); closeMenu(); }
  }, true);
  panel.body.addEventListener('scroll', closeMenu, true);
  panel.el.addEventListener('dragpanel-move', closeMenu);

  // 그림을 못 읽은 타일은 '데이터 없음' 으로 바꾼다(팩이 그사이 갈린 경우).
  panel.body.addEventListener('error', event => {
    const img = event.target;
    if (!img?.classList?.contains('atw-img')) return;
    const empty = doc.createElement('div');
    empty.className = 'atw-none';
    empty.textContent = '데이터 없음';
    img.replaceWith(empty);
  }, true);

  return {
    open: () => panel.open(),
    close: () => panel.close(),
    toggle: () => panel.toggle(),
    isOpen: () => panel.isOpen(),
    el: panel.el,
  };
}
