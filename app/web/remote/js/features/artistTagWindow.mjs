// [자동화 / 고급 기능] > [아티스트 태그 관리](사용자 지시 2026-11-11) - 메인 프롬프트에 쓴 작가를 썸네일 타일로 보여 준다.
//
//   - **부른 그때 한 번** 읽는다. 프롬프트를 고쳐도 따라가지 않는다 - 다시 열면 그때의 프롬프트로 다시 읽는다.
//   - 메인 프롬프트만 본다(네거티브 · 캐릭터 프롬프트는 보지 않는다).
//   - 그림은 서버가 팩을 통째로 올리지 않고 그 작가의 자리만 읽어 낸다(core/artist_pack_index). 처음 여는 팩은
//     자리 색인을 만드느라 몇 초가 든다 - 그동안 '찾는 중' 을 보여 준다.
//   - 작가의 그림은 여러 팩에 나뉘어 있다. 받은 팩 어디에도 없으면 그 타일은 '데이터 없음'.
//   - 타일에 마우스를 올리면 창 옆에 크게 뜬다 - Artist Thumbnail 리모컨의 확대 상자를 그대로 쓴다
//     (remoteController.showZoomBeside · 사용자 지시 2026-11-11 "기존 Artist Thumbnail 의 기능을 점검"). 폭만 넓힌다(is-wide).
//   - '데이터 없음' 타일이 있으면 위에 [받기] 띠: 이 계열(NAID5 · ANIMA …)에서 아직 안 받은 팩마다 [받기](사용자 지시 2026-11-13
//     · 목업 승인). 받기는 Artist Thumbnail 탭과 같은 서버 다운로드(한 번에 한 팩 - 서버가 정한다)를 쓴다. 받는 동안 그 줄에
//     진행 · [취소], 다른 줄은 '대기'. 다 받으면 타일을 다시 읽는다. 어느 작가가 어느 팩에 드는지는 짐작하지 않는다.
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
.atw-packs { flex: 0 0 auto; margin: 10px 10px 0; padding: 8px 10px; border: 1px solid rgba(240,198,116,0.45);
  border-radius: 6px; background: var(--bg-surface); font-size: 12px; }
.atw-packs-head { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 4px; color: #f0c674; }
.atw-packs-busy { color: var(--text-dim); white-space: nowrap; }
.atw-pack { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 10px;
  padding: 5px 0; border-top: 1px solid var(--border-dim); }
.atw-pack-name { min-width: 0; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.atw-pack-size { font-family: var(--font-mono); color: var(--text-dim); }
.atw-pack button { min-width: 56px; padding: 3px 10px; border: 1px solid var(--border-dim); border-radius: 5px; cursor: pointer;
  background: transparent; color: var(--text-primary); font-family: inherit; font-size: 12px; }
.atw-pack button:hover:not(:disabled) { border-color: var(--accent); }
.atw-pack button:disabled { cursor: default; color: var(--text-dim); }
.atw-pack-bar { grid-column: 1 / -1; height: 4px; border-radius: 2px; background: var(--border-dim); overflow: hidden; }
.atw-pack-bar i { display: block; height: 100%; background: var(--accent); }
.atw-pack-msg { grid-column: 1 / -1; font-family: var(--font-mono); font-size: 11px; color: var(--text-dim); }
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
.atw-tile:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
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
  // [받기] 띠. 받기 상태는 서버 하나(Artist Thumbnail 탭과 같은 것)라 이 창이 시작하지 않은 받기도 여기 보인다.
  let packs = [];          // 이 계열의 팩 {key, label, exists, needs_update, expected_size_mb}
  let family = '';
  let missingTiles = 0;    // '데이터 없음' 타일 수 - 0 이면 띠를 띄우지 않는다
  let dl = null;           // 서버의 받기 상태(GET /api/artist-thumb/download)
  let dlTimer = null;
  let dlWatching = '';     // 진행 중으로 본 받기의 팩 - 끝남(active -> 아님)은 이것으로만 안다(done · error 는 지난 값이 남는다)
  let dlStarting = false;  // [받기] 를 누르고 응답을 기다리는 동안 - 연타 막기
  let dlCancelled = '';    // 이 창에서 [취소] 를 누른 받기 - 끝날 때 오류가 아니라 안내로 알린다
  const panel = createDraggablePanel({
    document: doc, window: win, id: 'artistTagWindow', title: '아티스트 태그 관리',
    variant: 'em-overlay em-window atw-window', storageKey: 'artist-tag-manager',
    width: 560, height: 520, minWidth: 260, maxWidth: 960, minHeight: 200, resizable: true,
    escHtml,
    onOpen: () => { load(); void refreshDownload(); onVisibilityChange(); },
    onClose: () => { serial += 1; stopDlPoll(); leaveTile(); closeMenu(); onVisibilityChange(); },
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
    return `<div class="atw-tile" tabindex="0" title="${escHtml(tip)}" data-atw-artist="${escHtml(name)}" data-atw-weight="${escHtml(String(weight))}">${picture}`
      + `<div class="atw-name">${escHtml(name)}</div><div class="atw-meta">`
      + `<span class="atw-weight${weight < 0 ? ' is-neg' : ''}" title="가중치">${escHtml(String(weight))}</span>`
      + `<span title="게시물 수">${escHtml(posts)}</span></div></div>`;
  }

  // ── 받지 않은 팩 [받기] ─────────────────────────────────────────────
  const fmtGb = mb => `${(Math.round((Number(mb) || 0) / 1024 * 100) / 100).toFixed(2)} GB`;

  function packsHtml() {
    const missing = packs.filter(p => !p.exists);
    if (!missingTiles || !missing.length) return '';
    const active = Boolean(dl?.active);
    const busyMode = active ? String(dl.mode || '') : '';
    const foreign = busyMode && !missing.some(p => p.key === busyMode);
    const head = `<div class="atw-packs-head"><span>그림 없는 작가 ${missingTiles}명 · 받지 않은 ${escHtml(family || '')} 팩 ${missing.length}개</span>`
      + (foreign ? `<span class="atw-packs-busy">${escHtml(busyMode)} 받는 중 ${Math.round(Number(dl.percent) || 0)}%</span>` : '')
      + '</div>';
    const rows = missing.map(p => {
      const size = Number(p.expected_size_mb) > 0 ? fmtGb(p.expected_size_mb) : '';
      if (active && busyMode === p.key) {
        const pct = Math.max(0, Math.min(100, Number(dl.percent) || 0));
        const total = Number(dl.total_mb) > 0 ? ` · ${fmtGb(dl.downloaded_mb)} / ${fmtGb(dl.total_mb)}` : '';
        return `<div class="atw-pack"><span class="atw-pack-name" title="${escHtml(p.label)}">${escHtml(p.label)}</span>`
          + `<span class="atw-pack-size">${escHtml(size)}</span><button type="button" data-atw-pack-cancel>취소</button>`
          + `<div class="atw-pack-bar"><i style="width:${pct}%"></i></div>`
          + `<div class="atw-pack-msg">${Math.round(pct)}%${escHtml(total)} · ${escHtml(dl.message || '')}</div></div>`;
      }
      const wait = active || dlStarting;
      return `<div class="atw-pack"><span class="atw-pack-name" title="${escHtml(p.label)}">${escHtml(p.label)}</span>`
        + `<span class="atw-pack-size">${escHtml(size)}</span>`
        + `<button type="button" data-atw-pack="${escHtml(p.key)}"${wait ? ' disabled' : ''}>${wait ? '대기' : '받기'}</button></div>`;
    }).join('');
    return head + rows;
  }

  function paintPacks() {
    const band = panel.body.querySelector('.atw-packs');
    if (!band) return;
    const html = packsHtml();
    band.hidden = !html;
    band.innerHTML = html;
  }

  function stopDlPoll() { if (dlTimer) { clearInterval(dlTimer); dlTimer = null; } }

  function startDlPoll() {
    if (dlTimer || !panel.isOpen()) return;
    dlTimer = (win || globalThis).setInterval(() => { void refreshDownload(); }, 900);
  }

  /** 서버의 받기 상태를 읽는다. 지켜보던 받기가 끝났으면 알리고 타일을 다시 읽는다. */
  async function refreshDownload() {
    let state = null;
    try {
      const response = await fetchFn('/api/artist-thumb/download');
      state = await response.json();
      if (!response.ok || state?.error && state.active === undefined) throw new Error(state?.error || `HTTP ${response.status}`);
    } catch (_) {
      return;           // 다음 차례에 다시 - 상태를 못 읽었다고 받기가 멈춘 것은 아니다
    }
    if (!panel.isOpen()) { stopDlPoll(); return; }
    applyDownload(state);
  }

  function applyDownload(state) {
    dl = state && typeof state === 'object' ? state : null;
    if (dl?.active) {
      dlWatching = String(dl.mode || '');
      startDlPoll();
    } else {
      stopDlPoll();
      if (dlWatching) {
        const mode = dlWatching;
        dlWatching = '';
        if (dl?.error && dlCancelled === mode) notify(`${mode} 받기를 취소했습니다`, 'info');
        else if (dl?.error) notify(`${mode} 받기 - ${dl.error}`, 'error');
        else notify(`${mode} 팩을 받았습니다`, 'info');
        dlCancelled = '';
        void load({quiet: true});      // 새 팩으로 타일 · 띠를 다시
      }
    }
    paintPacks();
  }

  async function startPack(key) {
    if (!key || dlStarting || dl?.active) return;
    dlStarting = true;
    paintPacks();
    try {
      const response = await fetchFn('/api/artist-thumb/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: key}),
      });
      const state = await response.json();
      if (!response.ok || state?.error && state.active === undefined) throw new Error(state?.error || `HTTP ${response.status}`);
      // 다른 받기가 돌고 있었으면 서버는 그 상태를 돌려준다(오류 아님) - 그 진행에 붙는다.
      if (state?.active && String(state.mode || '') !== key) notify(`${state.mode} 를 받는 중입니다 - 끝난 뒤에 받으세요`, 'info');
      if (!state?.active && state?.done) { dlStarting = false; void load({quiet: true}); }
      dlStarting = false;
      applyDownload(state);
    } catch (error) {
      dlStarting = false;
      notify(`받기를 시작하지 못했습니다 - ${error?.message || error}`, 'error');
      paintPacks();
    }
  }

  async function cancelPack() {
    dlCancelled = dlWatching;
    try {
      const response = await fetchFn('/api/artist-thumb/download/cancel', {method: 'POST'});
      const state = await response.json();
      if (response.ok && state && state.active !== undefined) applyDownload(state);
    } catch (error) {
      notify(`취소하지 못했습니다 - ${error?.message || error}`, 'error');
    }
  }

  panel.body.addEventListener('click', event => {
    const start = event.target?.closest?.('[data-atw-pack]');
    if (start) { void startPack(start.dataset.atwPack || ''); return; }
    if (event.target?.closest?.('[data-atw-pack-cancel]')) void cancelPack();
  });

  async function load({quiet = false} = {}) {
    const mine = ++serial;
    if (!quiet) {
      count.textContent = '';
      note('작가를 찾는 중… 처음 여는 팩은 몇 초 걸립니다.');
    }
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
      if (quiet) { notify(`작가 목록을 다시 읽지 못했습니다 - ${error?.message || error}`, 'error'); return; }
      note(`작가 목록을 읽지 못했습니다 - ${error?.message || error}`, true);
      return;
    }
    if (mine !== serial) return;
    const rows = Array.isArray(data.artists) ? data.artists : [];
    packs = Array.isArray(data.packs) ? data.packs : [];
    family = String(data.family || '');
    missingTiles = rows.filter(row => !row.image_url).length;
    count.textContent = rows.length ? `${rows.length}명` : '';
    if (!rows.length) { note('메인 프롬프트에 작가 태그가 없습니다.'); return; }
    leaveTile();
    closeMenu();
    panel.body.innerHTML = `<div class="atw-packs" hidden></div><div class="atw-grid">${rows.map(tileHtml).join('')}</div>`;
    paintPacks();
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
    const tile = menuTile;
    // 메뉴 안에 초점이 있었으면(키보드로 연 것) 타일로 돌려준다 - 안 그러면 초점이 문서 맨 위로 떨어진다.
    const hadFocus = Boolean(menuEl && menuEl.contains(doc.activeElement));
    if (tile) tile.classList.remove('is-menu');
    menuTile = null;
    if (menuEl) menuEl.hidden = true;
    if (hadFocus && tile?.isConnected) tile.focus();
  }

  function openMenu(tile, x, y, {focus = false} = {}) {
    leaveTile();
    closeMenu();
    const box = menuBox();
    menuTile = tile;
    tile.classList.add('is-menu');
    box.querySelector('[data-atw-menu-name]').textContent = tile.dataset.atwArtist || '';
    // 처음 값은 그 타일의 가중치. 슬라이더 범위 밖(음수 · 2 초과)이면 1 에서 시작한다.
    const own = Number(tile.dataset.atwWeight);
    const start = Number.isFinite(own) && own >= WEIGHT_MIN && own <= WEIGHT_MAX ? own : 1;
    box.querySelector('[data-atw-weight]').value = String(start);
    box.querySelector('[data-atw-weight-out]').textContent = weightText(start);
    box.hidden = false;
    const view = win || doc.defaultView;
    const rect = box.getBoundingClientRect();
    box.style.left = `${Math.round(Math.max(6, Math.min(x, view.innerWidth - rect.width - 6)))}px`;
    box.style.top = `${Math.round(Math.max(6, Math.min(y, view.innerHeight - rect.height - 6)))}px`;
    if (focus) box.querySelector('[data-atw-solo]')?.focus();
  }

  /** 키보드로 열 때의 자리 - 타일 안쪽. */
  function openMenuAtTile(tile) {
    const rect = tile.getBoundingClientRect();
    openMenu(tile, rect.left + Math.min(40, rect.width / 2), rect.top + Math.min(40, rect.height / 2), {focus: true});
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
    // 키보드의 메뉴 키 · Shift+F10 은 좌표 없이(0, 0) 온다.
    if (!event.clientX && !event.clientY) openMenuAtTile(tile);
    else openMenu(tile, event.clientX, event.clientY);
  });
  // 키보드: 타일에 초점을 두고 Enter · Space = 메뉴(마우스 없이도 쓸 수 있게 - Codex 리뷰 2026-11-12 #9).
  panel.body.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const tile = event.target?.classList?.contains('atw-tile') ? event.target : null;
    if (!tile || typeof soloGenerate !== 'function') return;
    event.preventDefault();
    openMenuAtTile(tile);
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
