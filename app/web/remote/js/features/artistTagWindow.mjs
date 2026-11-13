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
//     다른 작가를 전부 걷고 이 작가만 넣은 글로 한 장 생성한다. 글을 만들고 보내는 것은 app.js(soloGenerate) - [현재 프롬프트로]
//     는 프롬프트 칸을 바꾸지 않고, [랜덤+생성] 은 칸을 **보낸 글**(이 작가만 든 글)로 바꾼다(사용자 지시 2026-11-13).
//   - 둘째 칸 [가중치를 업데이트하여 생성](사용자 지시 2026-11-13 · 목업 승인): 다른 작가는 두고 이 작가의 가중치만 바꿔 한 장.
//     두 단추 다 프롬프트 칸도 그 글로 바꾼다(app.js reweightGenerate). 이 작가가 PE 의 prefix · postfix 에서 왔으면(`sources`)
//     [이 가중치로 prefix 업데이트] - PE 칸의 그 작가 가중치만 고친다(생성 없음 · 다음 Random 부터).
//   - 슬라이더 값은 작가마다 · 칸마다 기억한다(storage). 다음에 메뉴를 열면 프롬프트의 값이 아니라 기억한 값에서 시작한다.
//   - 창이 열린 채로 Random 이 돌면 한 번 다시 읽는다(app.js 가 refresh() 를 부른다).
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
.atw-menu { position: fixed; z-index: calc(var(--z-drag-panel-zoom, 10195) + 5); width: 270px;
  background: var(--bg-elevated); border: 1px solid var(--border-glow); border-radius: 10px;
  box-shadow: 0 14px 40px rgba(0,0,0,0.6); overflow: hidden; user-select: none; }
.atw-menu[hidden] { display: none !important; }
.atw-menu-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; font-size: 13px; font-weight: 600;
  color: var(--text-primary); border-bottom: 1px solid var(--border-dim); }
.atw-menu-head > span:first-child { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.atw-menu-src { flex: 0 0 auto; padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px;
  font-weight: 400; color: var(--text-muted); background: var(--bg-hover); }
.atw-menu-gap { border-top: 1px solid var(--border-dim); margin-top: 2px; }
.atw-menu-pe { display: block; width: calc(100% - 24px); margin: 0 12px 10px; padding: 6px; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--accent); background: transparent; color: var(--text-primary); font-family: inherit; font-size: 12px; }
.atw-menu-pe:hover, .atw-menu-pe:focus-visible { background: var(--bg-hover); outline: none; }
.atw-menu-pe[hidden] { display: none; }
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
  // [가중치를 업데이트하여 생성] - {artist, weight, random}. 반환은 soloGenerate 와 같다. 없으면 그 칸을 숨긴다.
  reweightGenerate = null,
  // [이 가중치로 PE 업데이트] - {artist, weight, sources}. 알릴 글 또는 false.
  peReweight = null,
  // 지금 PE 의 prefix · postfix 글 - 타일마다 그 작가가 어느 칸에서 왔는지 서버가 짚는다.
  getPeFields = () => ({pre: '', post: ''}),
  // 슬라이더 값을 기억할 곳(localStorage). 없으면 이번 실행에만 기억한다.
  storage = null,
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
  // 창이 열린 동안 받기 상태를 늘 묻는다 - 받는 중 0.9초 · 쉬는 중 3초. 실패해도 다음 차례에 다시 묻고, Artist Thumbnail
  // 탭에서 시작한 받기도 이렇게 알아챈다(Codex 리뷰 1차 #2 · #3).
  // 요청마다 번호를 매겨 먼저 보낸 요청의 늦은 답이 나중 답을 덮지 못하게 한다 - 창을 열 때의 GET 이 [받기] POST 보다
  // 늦게 와서 '안 받는 중' 으로 감시를 끝내던 것(Codex 리뷰 1차 #1).
  const DL_POLL_BUSY_MS = 900, DL_POLL_IDLE_MS = 3000;
  let dlIssued = 0;        // 마지막으로 보낸 상태 요청 번호
  let dlApplied = 0;       // 마지막으로 반영한 응답의 요청 번호
  let dlSeenDone = '';     // 다시 읽기를 이미 한 '받기 끝남' 상태(팩 · 시각) - 같은 끝남으로 거듭 읽지 않는다
  let dlWatching = '';     // 진행 중으로 본 받기의 팩 - 끝남(active -> 아님)은 이것으로만 안다(done · error 는 지난 값이 남는다)
  let dlStarting = false;  // [받기] 를 누르고 응답을 기다리는 동안 - 연타 막기
  let dlCancelled = '';    // 이 창에서 [취소] 를 누른 받기 - 끝날 때 오류가 아니라 안내로 알린다
  const panel = createDraggablePanel({
    document: doc, window: win, id: 'artistTagWindow', title: '아티스트 태그 관리',
    variant: 'em-overlay em-window atw-window', storageKey: 'artist-tag-manager',
    width: 560, height: 520, minWidth: 260, maxWidth: 960, minHeight: 200, resizable: true,
    escHtml,
    onOpen: () => { load(); stopDlPoll(); void refreshDownload(); onVisibilityChange(); },
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
    const sources = Array.isArray(row.sources) ? row.sources.filter(v => v === 'prefix' || v === 'postfix') : [];
    return `<div class="atw-tile" tabindex="0" title="${escHtml(tip)}" data-atw-artist="${escHtml(name)}" data-atw-weight="${escHtml(String(weight))}"`
      + ` data-atw-sources="${escHtml(sources.join(','))}">${picture}`
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

  const timers = win || globalThis;

  function stopDlPoll() { if (dlTimer) { timers.clearTimeout(dlTimer); dlTimer = null; } }

  /** 다음 상태 묻기를 하나만 예약한다(이미 있으면 그대로). 창이 닫혀 있으면 묻지 않는다. */
  function scheduleDlPoll() {
    if (dlTimer || !panel.isOpen()) return;
    dlTimer = timers.setTimeout(() => { dlTimer = null; void refreshDownload(); },
      dl?.active || dlStarting ? DL_POLL_BUSY_MS : DL_POLL_IDLE_MS);
  }

  /** 서버의 받기 상태를 읽는다. 지켜보던 받기가 끝났으면 알리고 타일을 다시 읽는다. */
  async function refreshDownload() {
    const issue = ++dlIssued;
    let state = null;
    try {
      const response = await fetchFn('/api/artist-thumb/download');
      state = await response.json();
      if (!response.ok || state?.error && state.active === undefined) throw new Error(state?.error || `HTTP ${response.status}`);
    } catch (_) {
      scheduleDlPoll();      // 다음 차례에 다시 - 상태를 못 읽었다고 받기가 멈춘 것은 아니다
      return;
    }
    if (!panel.isOpen()) { stopDlPoll(); return; }
    applyDownload(state, issue);
  }

  function finishWatched(mode) {
    if (dl?.error && dlCancelled === mode) notify(`${mode} 받기를 취소했습니다`, 'info');
    else if (dl?.error) notify(`${mode} 받기 - ${dl.error}`, 'error');
    else if (dl?.done) notify(`${mode} 팩을 받았습니다`, 'info');
    dlCancelled = '';
    void load({quiet: true});      // 새 팩으로 타일 · 띠를 다시(끝남 판정이 애매해도 다시 읽는 것은 해가 없다)
  }

  function applyDownload(state, issue) {
    if (issue < dlApplied) { scheduleDlPoll(); return; }    // 먼저 보낸 요청의 늦은 답 - 버린다
    dlApplied = issue;
    const prev = dlWatching;
    dl = state && typeof state === 'object' ? state : null;
    if (dl?.active) {
      dlWatching = String(dl.mode || '');
      // 보던 받기가 끝나고 그사이 다른 받기가 시작됐다(폴링 사이) - 앞의 것으로 타일을 다시 읽는다.
      if (prev && prev !== dlWatching) { dlCancelled = ''; void load({quiet: true}); }
    } else if (prev) {
      dlWatching = '';
      finishWatched(prev);
    } else if (dl?.done && !dl.error) {
      // 진행 중인 모습을 한 번도 못 보고 끝난 받기(시작 응답이 늦어 버려진 경우 등 - Codex 리뷰 2차). 띠에 아직 '안 받음' 인
      // 팩이 끝났다고 서버가 말하면 한 번 다시 읽는다. 같은 끝남(팩 · 시각)으로는 다시 하지 않는다.
      const doneKey = `${dl.mode || ''}|${dl.updated_at || ''}`;
      if (doneKey !== dlSeenDone && packs.some(pk => pk.key === dl.mode && !pk.exists)) {
        dlSeenDone = doneKey;
        void load({quiet: true});
      }
    }
    paintPacks();
    stopDlPoll();
    scheduleDlPoll();
  }

  async function startPack(key) {
    if (!key || dlStarting || dl?.active) return;
    dlStarting = true;
    paintPacks();
    const issue = ++dlIssued;
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
      applyDownload(state, issue);
    } catch (error) {
      dlStarting = false;
      notify(`받기를 시작하지 못했습니다 - ${error?.message || error}`, 'error');
      paintPacks();
    }
  }

  async function cancelPack() {
    dlCancelled = dlWatching;
    const issue = ++dlIssued;
    try {
      const response = await fetchFn('/api/artist-thumb/download/cancel', {method: 'POST'});
      const state = await response.json();
      if (response.ok && state && state.active !== undefined) applyDownload(state, issue);
    } catch (error) {
      notify(`취소하지 못했습니다 - ${error?.message || error}`, 'error');
    }
  }

  panel.body.addEventListener('click', event => {
    const start = event.target?.closest?.('[data-atw-pack]');
    if (start) { void startPack(start.dataset.atwPack || ''); return; }
    if (event.target?.closest?.('[data-atw-pack-cancel]')) void cancelPack();
  });

  function peBody() {
    try {
      const fields = getPeFields() || {};
      return {pre: String(fields.pre || ''), post: String(fields.post || '')};
    } catch (_) {
      return {pre: '', post: ''};
    }
  }

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
        body: JSON.stringify({text: String(getPrompt() || ''), mode: String(getThumbMode() || ''), ...peBody()}),
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

  // ── 우클릭 = 이 아티스트로만 생성 · 가중치를 업데이트하여 생성 ─────────────
  const WEIGHT_MIN = 0, WEIGHT_MAX = 2, WEIGHT_STEP = 0.01;    // 범위는 Artist Thumbnail 의 슬라이더와 같다. 눈금은 0.01 - 0.05 면 타일의 0.83 이 0.85 로 바뀐 채 시작한다
  let menuEl = null;
  let menuTile = null;
  let menuBusy = false;

  const weightText = value => String(Math.round(Number(value) * 100) / 100);

  // 슬라이더 기억 - {solo: {작가: 값}, update: {작가: 값}}. 칸마다 따로다(혼자일 때의 세기와 여럿 사이의 세기는 뜻이 다르다).
  const MEMORY_KEY = 'naia.artistTagWindow.weights';
  const MEMORY_MAX = 400;          // 칸마다 이만큼만 - 넘으면 오래 안 고친 작가부터 잊는다
  let memory = null;
  const memoryKey = name => String(name || '').trim().toLowerCase();

  function readMemory() {
    if (memory) return memory;
    memory = {solo: {}, update: {}};
    try {
      const saved = JSON.parse(storage?.getItem?.(MEMORY_KEY) || 'null');
      for (const kind of ['solo', 'update']) {
        const rows = saved && typeof saved[kind] === 'object' ? saved[kind] : {};
        for (const [name, value] of Object.entries(rows || {})) {
          const n = Number(value);
          if (name && Number.isFinite(n) && n >= WEIGHT_MIN && n <= WEIGHT_MAX) memory[kind][name] = n;
        }
      }
    } catch (_) {}
    return memory;
  }

  function remembered(kind, name) {
    const value = readMemory()[kind][memoryKey(name)];
    return Number.isFinite(value) ? value : null;
  }

  function remember(kind, name, value) {
    const key = memoryKey(name);
    const n = Math.round(Number(value) * 100) / 100;
    if (!key || !Number.isFinite(n)) return;
    const rows = readMemory()[kind];
    delete rows[key];                  // 맨 뒤로 - 가장 최근에 고친 작가
    rows[key] = n;
    const keys = Object.keys(rows);
    for (const old of keys.slice(0, Math.max(0, keys.length - MEMORY_MAX))) delete rows[old];
    try { storage?.setItem?.(MEMORY_KEY, JSON.stringify(memory)); } catch (_) {}
  }

  const sliderHtml = kind => `<label class="atw-menu-weight"><span>가중치</span>
        <input type="range" min="${WEIGHT_MIN}" max="${WEIGHT_MAX}" step="${WEIGHT_STEP}" data-atw-weight="${kind}" aria-label="가중치">
        <b data-atw-weight-out="${kind}"></b></label>`;
  const slider = kind => menuEl.querySelector(`[data-atw-weight="${kind}"]`);

  function setSlider(kind, value) {
    slider(kind).value = String(value);
    menuEl.querySelector(`[data-atw-weight-out="${kind}"]`).textContent = weightText(value);
  }

  function menuBox() {
    if (menuEl) return menuEl;
    menuEl = doc.createElement('div');
    menuEl.className = 'atw-menu';
    menuEl.hidden = true;
    menuEl.setAttribute('role', 'menu');
    menuEl.innerHTML = `
      <div class="atw-menu-head"><span data-atw-menu-name></span><span class="atw-menu-src" data-atw-menu-src></span></div>
      <div class="atw-menu-sec">이 아티스트로만 생성</div>
      <button type="button" class="atw-menu-item" role="menuitem" data-atw-solo="current">현재 프롬프트로</button>
      <button type="button" class="atw-menu-item" role="menuitem" data-atw-solo="random">랜덤+생성</button>
      ${sliderHtml('solo')}
      <div data-atw-update-sec>
        <div class="atw-menu-gap"></div>
        <div class="atw-menu-sec">가중치를 업데이트하여 생성</div>
        <button type="button" class="atw-menu-item" role="menuitem" data-atw-update="current">현재 프롬프트로</button>
        <button type="button" class="atw-menu-item" role="menuitem" data-atw-update="random">랜덤+생성</button>
        ${sliderHtml('update')}
        <button type="button" class="atw-menu-pe" role="menuitem" data-atw-pe hidden></button>
      </div>`;
    doc.body.appendChild(menuEl);
    menuEl.addEventListener('input', event => {
      const kind = event.target?.dataset?.atwWeight;
      if (!kind || !menuTile) return;
      menuEl.querySelector(`[data-atw-weight-out="${kind}"]`).textContent = weightText(event.target.value);
      remember(kind, menuTile.dataset.atwArtist, event.target.value);
    });
    menuEl.addEventListener('click', event => {
      const solo = event.target?.closest?.('[data-atw-solo]');
      if (solo) { void runSolo(solo.dataset.atwSolo === 'random'); return; }
      const update = event.target?.closest?.('[data-atw-update]');
      if (update) { void runUpdate(update.dataset.atwUpdate === 'random'); return; }
      if (event.target?.closest?.('[data-atw-pe]')) void runPe();
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
    const name = tile.dataset.atwArtist || '';
    const sources = tileSources(tile);
    box.querySelector('[data-atw-menu-name]').textContent = name;
    box.querySelector('[data-atw-menu-src]').textContent = sources[0] || '랜덤 글';
    // 처음 값은 기억한 값, 없으면 그 타일의 가중치. 슬라이더 범위 밖(음수 · 2 초과)이면 1 에서 시작한다.
    const own = Number(tile.dataset.atwWeight);
    const start = Number.isFinite(own) && own >= WEIGHT_MIN && own <= WEIGHT_MAX ? own : 1;
    setSlider('solo', remembered('solo', name) ?? start);
    setSlider('update', remembered('update', name) ?? start);
    box.querySelector('[data-atw-update-sec]').hidden = typeof reweightGenerate !== 'function';
    const pe = box.querySelector('[data-atw-pe]');
    pe.hidden = !sources.length || typeof peReweight !== 'function';
    pe.textContent = `이 가중치로 ${sources.join(' · ')} 업데이트`;
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

  function tileSources(tile) {
    return String(tile?.dataset?.atwSources || '').split(',').filter(v => v === 'prefix' || v === 'postfix');
  }

  /** 메뉴의 단추 하나를 돌린다 - 메뉴를 닫고, 그동안 다른 단추를 막는다(연타가 두 장이 되지 않게 · 랜덤+생성은 Random 응답을 기다린다). */
  async function runMenu(kind, action, failText) {
    if (!menuTile || menuBusy) return;
    const artist = menuTile.dataset.atwArtist || '';
    const weight = Number(slider(kind).value);
    const sources = tileSources(menuTile);
    closeMenu();
    if (!artist) return;
    menuBusy = true;
    try {
      const sent = await action({artist, weight, sources});
      if (typeof sent === 'string' && sent) notify(sent, 'info');
    } catch (error) {
      notify(`${failText} - ${error?.message || error}`, 'error');
    } finally {
      menuBusy = false;
    }
  }

  const runSolo = random => runMenu('solo', ({artist, weight}) => soloGenerate({artist, weight, random}), '생성을 보내지 못했습니다');
  const runUpdate = random => runMenu('update', ({artist, weight}) => reweightGenerate({artist, weight, random}), '생성을 보내지 못했습니다');
  const runPe = () => runMenu('update', args => peReweight(args), 'PE 를 고치지 못했습니다');

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
    /** 열려 있으면 지금 프롬프트로 한 번 다시 읽는다(Random 이 돌았을 때 - app.js). 닫혀 있으면 아무 일도 없다. */
    refresh: () => { if (panel.isOpen()) void load({quiet: true}); },
    el: panel.el,
  };
}
