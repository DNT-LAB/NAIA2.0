// Search | Tag Filter 리모컨 창 - 떠 있는 창 하나에 두 층(위 Search / 아래 Tag Filter).
// 한 층을 펼치면 다른 층은 접힌다(사용자 지정 2026-09-21).
//
// 창 기반 = draggablePanel(Artist Thumbnail 리모컨과 같은 것: 끌기·크기·접기·z 레지스트리·자리 기억).
// ⚠️ 같은 URL(?v=)로 불러와야 z 레지스트리를 나눠 쓴다 - 다르면 모듈이 둘이 되어 창끼리 겹침 순서가 깨진다.
//
// 내용은 **베끼지 않고 옮긴다**(remoteController 원칙):
// - Search 층 = searchPanel 이 그리는 전용 요소(searchHost)를 그대로 품는다. 예전엔 모든 좌측 모듈이
//   함께 쓰는 #modulePopupBody 에 그렸다.
// - Tag Filter 층 = index.html 의 #tagFilterPopup 안 `.tag-filter-body` 를 옮겨 온다. quickFilter 는
//   전부 id 로 찾으므로 그대로 동작한다. 껍데기(#tagFilterPopup)는 남긴다(시험·CSS 가 그 이름을 본다).
// - 잠금 오버레이(#tagFilterLock)는 창 **본문 뿌리**로 - 두 층을 함께 덮고 머리줄은 남긴다
//   (창 뿌리에 두면 머리줄까지 덮어 잠금 중 창을 못 끌고 못 닫는다). 해제됨 오버레이(#tagFilterReleased)는
//   Tag Filter 층에.
//
// 접힌 층도 **계속 갱신**한다(렌더를 미루지 않는다) - searchPanel 은 한 번 그리고 제자리 패치라 비용이 없고,
// '마지막 메시지 재생' 을 넣으면 같은 상태가 두 곳에 산다.

import { createDraggablePanel } from './draggablePanel.mjs?v=20260919-headdrag';

const LAYER_KEY = 'naia.sqw.layer';
const STYLE_ID = 'sqw-style';

export function createSearchQuickWindow({
  document: doc,
  window: win,
  searchHost,
  // Custom Parquets 카드 그리드가 그려지는 요소 - 검색 창 옆 동반 창에 붙인다(사용자 지정 2026-09-21,
  // Artist Thumbnail 옆 Prompt Engineering 창과 같은 방식).
  libraryHost = null,
  onLibraryVisibility = () => {},
  requestSearchState = () => {},
  onVisibilityChange = () => {},
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  escHtml,
}) {
  ensureStyle(doc);
  let layer = readLayer();

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title: 'Search',
    variant: 'sqw',
    storageKey: 'search-quick',
    width: 400,
    minWidth: 320,
    maxWidth: 760,
    height: 640,
    minHeight: 220,
    resizable: true,
    // 모듈 팝업·심층검색은 왼쪽(492px)에 뜬다 - 겹치지 않게 오른쪽에서 시작한다.
    initial: { right: 24, y: 64 },
    escHtml,
    onOpen: () => onVisibilityChange(),
    // 동반 창은 함께 닫는다 - 혼자 남으면 무엇의 목록인지 모른다.
    onClose: () => { if (libPanel && libPanel.isOpen()) libPanel.close(); onVisibilityChange(); },
    onCollapse: () => onVisibilityChange(),
  });
  panel.el.id = 'searchQuickWindow';

  panel.body.innerHTML = `
    <section class="sqw-sec" data-sqw-sec="search">
      <button type="button" class="sqw-head" data-sqw-head="search">
        <span class="sqw-caret" aria-hidden="true"></span>
        <span class="sqw-name">Search</span>
        <span class="sqw-meta" data-sqw-meta="search"></span>
      </button>
      <div class="sqw-body" data-sqw-body="search"></div>
    </section>
    <section class="sqw-sec" data-sqw-sec="tag">
      <button type="button" class="sqw-head" data-sqw-head="tag">
        <span class="sqw-caret" aria-hidden="true"></span>
        <span class="sqw-name">Tag Filter</span>
        <span class="sqw-meta" data-sqw-meta="tag"></span>
      </button>
      <div class="sqw-body" data-sqw-body="tag"></div>
    </section>`;

  const searchBody = panel.body.querySelector('[data-sqw-body="search"]');
  const tagBody = panel.body.querySelector('[data-sqw-body="tag"]');
  searchBody.appendChild(searchHost);
  liftTagFilter();
  applyLayer();
  mirrorMeta();

  panel.body.addEventListener('click', event => {
    const head = event.target.closest('[data-sqw-head]');
    if (!head) return;
    setLayer(head.dataset.sqwHead === 'tag' ? 'tag' : 'search');
  });

  function liftTagFilter() {
    const shell = doc.getElementById('tagFilterPopup');
    const body = shell && shell.querySelector('.tag-filter-body');
    if (body) tagBody.appendChild(body);
    const released = doc.getElementById('tagFilterReleased');
    if (released) tagBody.appendChild(released);
    const lock = doc.getElementById('tagFilterLock');
    if (lock) panel.body.appendChild(lock);
  }

  // 층 머리줄에 개수를 비춘다 - 접힌 층도 지금 상태가 보여야 한다.
  function mirrorMeta() {
    const pairs = [
      [doc.getElementById('searchCount'), panel.body.querySelector('[data-sqw-meta="search"]'), text => text ? `풀 ${text}` : ''],
      [doc.getElementById('tagFilterCount'), panel.body.querySelector('[data-sqw-meta="tag"]'), text => text],
    ];
    for (const [source, target, format] of pairs) {
      if (!source || !target) continue;
      const sync = () => { target.textContent = format((source.textContent || '').trim()); };
      sync();
      if (typeof MutationObserver === 'function') {
        new MutationObserver(sync).observe(source, { childList: true, characterData: true, subtree: true });
      }
    }
  }

  function readLayer() {
    try { return storage && storage.getItem(LAYER_KEY) === 'tag' ? 'tag' : 'search'; } catch { return 'search'; }
  }

  function applyLayer() {
    panel.el.dataset.layer = layer;
    for (const sec of panel.body.querySelectorAll('[data-sqw-sec]')) {
      sec.classList.toggle('is-open', sec.dataset.sqwSec === layer);
    }
  }

  function setLayer(next) {
    if (next === layer) return;
    layer = next;
    try { storage && storage.setItem(LAYER_KEY, layer); } catch { /* 기억 못 해도 동작은 한다 */ }
    applyLayer();
    if (layer === 'tag') {
      const input = doc.getElementById('tagFilterInput');
      if (input) input.focus();
    }
    onVisibilityChange();
  }

  // ── Custom Parquets 동반 창 ─────────────────────────────────────────────
  let libPanel = null;

  /** 창 **바깥** 좌우 중 넓은 쪽(remoteController.besideSpot 과 같은 규칙). 처음 뜰 때만 쓰고,
   *  그 뒤로는 창이 제 자리를 기억한다(storageKey). */
  function besideSpot(width, height, anchorRect) {
    const vw = win?.innerWidth || doc.documentElement.clientWidth;
    const vh = win?.innerHeight || doc.documentElement.clientHeight;
    const roomLeft = anchorRect.left;
    const roomRight = vw - anchorRect.right;
    const left = (roomLeft >= width + 16 || roomLeft > roomRight)
      ? anchorRect.left - width - 10
      : anchorRect.right + 10;
    return {
      x: Math.round(Math.max(6, Math.min(left, vw - width - 6))),
      y: Math.round(Math.max(6, Math.min(anchorRect.top, vh - height - 6))),
    };
  }

  function ensureLibraryPanel() {
    if (libPanel || !libraryHost) return libPanel;
    const width = 360;
    const height = 560;
    const spot = besideSpot(width, height, panel.el.getBoundingClientRect());
    libPanel = createDraggablePanel({
      document: doc,
      window: win,
      title: 'Custom Parquets',
      variant: 'pqlw',
      storageKey: 'search-quick-parquets',
      width, height, minWidth: 240, maxWidth: 900, minHeight: 160,
      resizable: true,
      initial: { x: spot.x, y: spot.y },
      escHtml,
      onOpen: () => onLibraryVisibility(true),
      onClose: () => onLibraryVisibility(false),
    });
    libPanel.el.id = 'searchParquetWindow';
    libPanel.body.appendChild(libraryHost);
    return libPanel;
  }

  function toggleLibrary() {
    const p = ensureLibraryPanel();
    if (!p) return;
    if (p.isOpen()) p.close(); else p.open();
  }

  function showLibrary() {
    const p = ensureLibraryPanel();
    if (p) p.open();
  }

  // 창을 연다(닫혀 있었으면 검색 상태를 한 번 받는다 - 예전 openModule('search') 가 하던 일).
  function openAt(target, { toggle = false } = {}) {
    const wasOpen = panel.isOpen();
    if (wasOpen && toggle && layer === target && !panel.isCollapsed()) {
      panel.close();
      return;
    }
    panel.open();
    if (panel.isCollapsed()) panel.expand();
    if (layer !== target) setLayer(target);
    else if (target === 'tag') doc.getElementById('tagFilterInput')?.focus();
    if (!wasOpen) requestSearchState();
    onVisibilityChange();
  }

  const api = {
    el: panel.el,
    showSearch: (options = {}) => openAt('search', options),
    showTagFilter: (options = {}) => openAt('tag', options),
    close: () => panel.close(),
    collapse: () => panel.collapse(),
    toggleLibrary,
    showLibrary,
    isLibraryOpen: () => Boolean(libPanel && libPanel.isOpen()),
    isOpen: () => panel.isOpen(),
    isSearchShown: () => panel.isOpen() && !panel.isCollapsed() && layer === 'search',
    isTagFilterShown: () => panel.isOpen() && !panel.isCollapsed() && layer === 'tag',
    // quickFilter 가 '팝업이 열려 있나' 대신 묻는 곳(자동완성·카운트 갱신·토글).
    tagSurface: {
      isOpen: () => panel.isOpen() && !panel.isCollapsed() && layer === 'tag',
      // 층이 접혀 있어도 창이 열려 있으면 카운트는 갱신한다(층 머리줄에 비친다).
      isWindowOpen: () => panel.isOpen(),
      open: () => openAt('tag'),
      close: () => { if (panel.isOpen() && layer === 'tag') panel.close(); },
    },
  };
  return api;
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = SQW_CSS;
  doc.head.appendChild(style);
}

// 컴팩트(Memo·Tagger 기준: 글자 9.5~11px, 단추 22px). 옮겨 온 요소는 원래 클래스를 달고 오므로
// 여기서는 **이 창 안에서만** 줄인다(.dragpanel.sqw 아래로 한정 - 다른 화면에 새지 않는다).
const SQW_CSS = `
.dragpanel.sqw{border-color:rgba(120,190,150,0.42)}
.dragpanel.sqw .dragpanel-head{background:rgba(120,190,150,0.10)}
.dragpanel.sqw .dragpanel-body{padding:0;gap:0;overflow:hidden;position:relative}
.sqw-sec{display:flex;flex-direction:column;min-height:0;border-bottom:1px solid rgba(255,255,255,0.06)}
.sqw-sec.is-open{flex:1 1 auto}
.sqw-head{display:flex;align-items:center;gap:6px;width:100%;height:26px;padding:0 9px;border:none;
  background:rgba(255,255,255,0.025);color:var(--text-muted,#9a9aa6);font-size:11px;font-weight:700;
  letter-spacing:.02em;cursor:pointer;text-align:left;flex:0 0 auto}
.sqw-head:hover{color:var(--text-primary,#e8e8ee);background:rgba(255,255,255,0.05)}
.sqw-sec.is-open .sqw-head{color:var(--text-primary,#e8e8ee)}
.sqw-caret{width:0;height:0;border-left:4px solid currentColor;border-top:3.5px solid transparent;
  border-bottom:3.5px solid transparent;transition:transform .12s}
.sqw-sec.is-open .sqw-caret{transform:rotate(90deg)}
.sqw-name{flex:0 0 auto}
.sqw-meta{margin-left:auto;font-family:var(--font-mono,monospace);font-size:10px;font-weight:500;
  color:var(--accent-green,#5a9e6f);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sqw-body{display:none;min-height:0;overflow:auto;padding:7px 9px 9px;position:relative}
.sqw-sec.is-open .sqw-body{display:flex;flex-direction:column;gap:7px;flex:1 1 auto}

/* ── Search 층 안쪽을 줄인다 ── */
.sqw-body .search-host{display:flex;flex-direction:column;gap:7px}
.sqw-body .mod-section-label{font-size:9.5px;margin-bottom:2px}
.sqw-body .mod-action-btn{height:22px;min-height:22px;padding:0 8px;font-size:10.5px;border-radius:5px}
.sqw-body .mod-input{height:24px;padding:2px 7px;font-size:11px}
.sqw-body .mod-checkbox-grid{gap:2px 10px}
.sqw-body .mod-checkbox-label{font-size:10.5px}
.sqw-body .header-guide-btn{font-size:9px;padding:0 5px;height:16px}
.sqw-body .search-tag-update{padding:6px 9px;margin:0 0 4px;font-size:11px}
.sqw-body .search-tag-update .stu-title{font-size:11px}
.sqw-body .search-tag-update .stu-span,.sqw-body .search-tag-update .stu-sub{font-size:10px}
.sqw-body .dr-track{margin:16px 7px 6px}
.sqw-body .mod-start{height:26px;font-size:11.5px}

/* ── Tag Filter 층: 옛 팝업 몸통을 그대로 품는다 ── */
.sqw-body .tag-filter-body{padding:0;gap:6px}
.sqw-body .tag-filter-input{height:24px;font-size:11px}
.sqw-body .tag-filter-btn-action{height:22px;font-size:10.5px}
/* 해제됨 오버레이는 이 층만 덮는다(층이 기준 상자). */
.sqw-body .tag-filter-released{position:absolute;inset:0}
/* 잠금은 본문 전체(두 층)를 덮고 머리줄은 남긴다. */
.dragpanel.sqw > .dragpanel-body > #tagFilterLock{position:absolute;inset:0;z-index:5}
`;
