// Search | Tag Filter | 심층 검색 리모컨 창 - 떠 있는 창 하나에 세 층. 한 층을 펼치면 나머지는 접힌다
// (사용자 지정 2026-09-21 두 층 · 2026-09-25 심층 검색을 세 번째 층으로 - 메뉴 안에 숨어 기능이 유실된 것처럼 보였다).
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
  // 층이 **보이게 된** 순간(펼침 · 창 열림). 심층 검색 층은 이때 처음 준비된다(app.js).
  onLayerShown = () => {},
  // 창이 닫힐 때 - 심층 검색이 창 없이 혼자 남지 않게 app.js 가 함께 닫는다.
  onWindowClose = () => {},
  // 저장된 필터 창이 열리고 닫힐 때([Filters] 단추의 눌림 표시).
  onPresetsVisibility = () => {},
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
    onClose: () => {
      if (libPanel && libPanel.isOpen()) libPanel.close();
      if (presetsPanel && presetsPanel.isOpen()) presetsPanel.close();
      closeRefineSide();
      onWindowClose();
      onVisibilityChange();
    },
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
    </section>
    <section class="sqw-sec" data-sqw-sec="refine">
      <button type="button" class="sqw-head" data-sqw-head="refine">
        <span class="sqw-caret" aria-hidden="true"></span>
        <span class="sqw-name">심층 검색</span>
        <span class="sqw-meta" data-sqw-meta="refine"></span>
      </button>
      <div class="sqw-body" data-sqw-body="refine"></div>
    </section>`;

  const searchBody = panel.body.querySelector('[data-sqw-body="search"]');
  const tagBody = panel.body.querySelector('[data-sqw-body="tag"]');
  const refineBody = panel.body.querySelector('[data-sqw-body="refine"]');
  searchBody.appendChild(searchHost);
  liftTagFilter();
  // 심층 검색 화면(#refineView)도 **옮긴다**(베끼지 않는다) - 모듈 팝업 안에 있던 그 요소 그대로.
  const refineView = doc.getElementById('refineView');
  if (refineView) refineBody.appendChild(refineView);
  applyLayer();
  mirrorMeta();

  panel.body.addEventListener('click', event => {
    if (event.target.closest('[data-sqw="refine-side"]')) { toggleRefineSide(); return; }
    const head = event.target.closest('[data-sqw-head]');
    if (!head) return;
    setLayer(normalizeLayer(head.dataset.sqwHead));
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

  function normalizeLayer(value) {
    return value === 'tag' || value === 'refine' ? value : 'search';
  }

  function readLayer() {
    try { return normalizeLayer(storage && storage.getItem(LAYER_KEY)); } catch { return 'search'; }
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
    if (panel.isOpen()) onLayerShown(layer);
    syncRefineSide();
    onVisibilityChange();
  }

  // ── 심층 검색 도구 동반 창(사용자 지정 2026-09-25: 2단) ─────────────────────
  // 심층 검색 층의 오른쪽 칸(샘플 미리보기 · 스테이징 · 병합&내보내기)을 창 **오른쪽**에 붙인다.
  // 한 층에 다 쌓으니 너무 길어 조화가 없었다. 칸 요소는 refinePanel 이 그린 그대로 옮긴다.
  let refineSide = null;
  let refineSideDismissed = false;       // 사용자가 × 로 닫았으면 층을 오가도 다시 띄우지 않는다

  function rightOfSpot(width, height, anchorRect) {
    const vw = win?.innerWidth || doc.documentElement.clientWidth;
    const vh = win?.innerHeight || doc.documentElement.clientHeight;
    const roomRight = vw - anchorRect.right;
    const left = roomRight >= width + 16 ? anchorRect.right + 10 : anchorRect.left - width - 10;
    return {
      x: Math.round(Math.max(6, Math.min(left, vw - width - 6))),
      y: Math.round(Math.max(6, Math.min(anchorRect.top, vh - height - 6))),
    };
  }

  function ensureRefineSide() {
    if (refineSide) return refineSide;
    const width = 320;
    const height = 600;
    const spot = rightOfSpot(width, height, panel.el.getBoundingClientRect());
    refineSide = createDraggablePanel({
      document: doc,
      window: win,
      title: '심층 검색 도구',
      variant: 'rfsw',
      storageKey: 'search-quick-refine-side',
      width, height, minWidth: 260, maxWidth: 700, minHeight: 200,
      resizable: true,
      initial: { x: spot.x, y: spot.y },
      escHtml,
      onClose: () => { refineSideDismissed = true; },
    });
    refineSide.el.id = 'searchRefineSideWindow';
    return refineSide;
  }

  function attachRefineRight() {
    // refinePanel 이 층 안에 그린 오른쪽 칸을 동반 창으로 옮긴다(이미 옮겼으면 그대로).
    const side = ensureRefineSide();
    const right = doc.querySelector('#refineView .refine-right') || side.body.querySelector('.refine-right');
    if (right && right.parentNode !== side.body) side.body.appendChild(right);
    return Boolean(right);
  }

  function openRefineSide() {
    if (!attachRefineRight()) return;
    refineSideDismissed = false;
    if (!refineSide.isOpen()) refineSide.open();
  }

  function closeRefineSide() {
    if (refineSide && refineSide.isOpen()) {
      refineSide.close();
      refineSideDismissed = false;       // 창이 닫은 것 - 사용자가 닫은 것이 아니다
    }
  }

  function toggleRefineSide() {
    if (refineSide && refineSide.isOpen()) { refineSide.close(); return; }
    openRefineSide();
  }

  /** 심층 검색 층이 보이면 함께 띄우고, 다른 층으로 가면 닫는다. */
  function syncRefineSide() {
    if (panel.isOpen() && layer === 'refine') {
      if (!refineSideDismissed) openRefineSide();
    } else {
      closeRefineSide();
    }
  }

  // ── 저장된 필터 동반 창(사용자 지정 2026-09-25) ──────────────────────────────
  // Tag Filter 층 안의 목록은 180px 에서 스크롤 속 스크롤이 됐다(5줄쯤). 목록 요소(#tagFilterPresets)를
  // **옮겨** 창에 붙인다 - quickFilter 는 id 로 찾으므로 그대로 그린다. 백업 슬롯은 맨 위에 고정(sticky).
  let presetsPanel = null;

  function ensurePresetsPanel() {
    if (presetsPanel) return presetsPanel;
    const list = doc.getElementById('tagFilterPresets');
    if (!list) return null;
    const width = 300;
    const height = 440;
    const spot = rightOfSpot(width, height, panel.el.getBoundingClientRect());
    presetsPanel = createDraggablePanel({
      document: doc,
      window: win,
      title: '저장된 필터',
      variant: 'tfpw',
      storageKey: 'search-quick-filter-presets',
      width, height, minWidth: 220, maxWidth: 700, minHeight: 180,
      resizable: true,
      initial: { x: spot.x, y: spot.y },
      escHtml,
      onOpen: () => onPresetsVisibility(true),
      onClose: () => onPresetsVisibility(false),
    });
    presetsPanel.el.id = 'searchFilterPresetsWindow';
    presetsPanel.body.innerHTML = `
      <div class="tfpw-search"><input type="text" id="tagFilterPresetSearch" placeholder="이름으로 찾기…" spellcheck="false" autocomplete="off"></div>`;
    list.removeAttribute('hidden');
    presetsPanel.body.appendChild(list);
    return presetsPanel;
  }

  /** [Filters] - 창을 열고 닫는다. 창을 못 만들면 false(옛 접이식 목록으로 떨어진다). */
  function togglePresets() {
    const p = ensurePresetsPanel();
    if (!p) return false;
    if (p.isOpen()) p.close();
    else p.open();
    return true;
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
    else {
      if (target === 'tag') doc.getElementById('tagFilterInput')?.focus();
      onLayerShown(layer);
      syncRefineSide();
    }
    if (!wasOpen) requestSearchState();
    onVisibilityChange();
  }

  const api = {
    el: panel.el,
    showSearch: (options = {}) => openAt('search', options),
    showTagFilter: (options = {}) => openAt('tag', options),
    showRefine: (options = {}) => openAt('refine', options),
    isRefineShown: () => panel.isOpen() && !panel.isCollapsed() && layer === 'refine',
    isRefineSideOpen: () => Boolean(refineSide && refineSide.isOpen()),
    close: () => panel.close(),
    collapse: () => panel.collapse(),
    toggleLibrary,
    showLibrary,
    togglePresets,
    isPresetsOpen: () => Boolean(presetsPanel && presetsPanel.isOpen()),
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
/* 본문 바탕 = 옛 Search·Tag Filter 팝업의 바탕(--bg-surface). 떠 있는 창의 기본 바탕(--bg-elevated)을
   쓰면 그 위의 --bg-elevated 요소(Filters·Clear 단추, 칩, 슬라이더 트랙)가 전부 배경에 묻힌다. */
.dragpanel.sqw .dragpanel-body{padding:0;gap:0;overflow:hidden;position:relative;background:var(--bg-surface)}
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

/* ── Tag Filter 층: 옛 팝업 몸통을 그대로 품고 Search 층과 같은 톤으로 줄인다 ── */
/* ⚠️ 저장 줄·저장 내역은 display:flex 라 [hidden] 을 이겨 **항상 보였다**(사용자 제보: Filters 를
   눌러야 펼쳐질 목록이 늘 떠 있다). 창 밖 옛 팝업에서도 같았다 - 범위를 좁히지 않고 짝 규칙을 둔다. */
.tag-filter-presets[hidden],.tag-filter-save-row[hidden]{display:none!important}
.sqw-body .tag-filter-body{padding:0;gap:6px;overflow:visible}
.sqw-body .tag-filter-rating-row{gap:6px;padding:0 0 6px}
.sqw-body .tag-filter-section-label{font-size:9.5px;letter-spacing:.06em}
.sqw-body .tag-filter-count{font-size:10px;padding:1px 7px}
.sqw-body .tag-filter-rating-row .rating-btn{padding:2px 7px;font-size:10px}
.sqw-body .tag-filter-input{height:24px;padding:2px 7px;font-size:11px;border-radius:5px}
.sqw-body .tag-filter-chips:empty{display:none}
.sqw-body .tag-filter-chip{padding:1px 6px;font-size:10.5px;gap:3px}
.sqw-body .tag-filter-stop-row{margin:0}
.sqw-body .tag-filter-stop-toggle .opt-label{font-size:10px}
.sqw-body .tag-filter-actions{display:flex;gap:4px;justify-content:stretch;padding-top:6px}
/* 크기만 줄인다. 색·굵기는 기존 팝업 규칙(style.css .tag-filter-btn-action.*)을 그대로 쓴다 -
   Commit 녹색(--success) · Save Filter/저장 파란 채움 · Filters/Clear 흰 굵은 글씨. 예전에 여기서
   배경·글자색을 한꺼번에 덮어 파란 단추가 회색이 됐다(사용자 검토: 기존 느낌을 살려라). */
.sqw-body .tag-filter-btn-action{flex:1 1 0;min-width:0;height:24px;padding:0 6px;font-size:10.5px;border-radius:5px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sqw-body .tag-filter-btn-action:disabled{opacity:.35;pointer-events:none}
.sqw-body .tag-filter-btn-action.filters.is-open{box-shadow:inset 0 0 0 1px rgba(245,220,138,0.7);color:#f5dc8a}
.sqw-body .tag-filter-save-row{padding-top:0}
.sqw-body .tag-filter-save-row .tag-filter-btn-action{flex:0 0 auto;padding:0 12px}
.sqw-body .tag-filter-presets{max-height:180px;padding:4px;margin:0;gap:3px;background:rgba(0,0,0,0.24);border-radius:6px}
.sqw-body .tf-preset{padding:3px 8px;border-radius:5px}
.sqw-body .tf-preset-name{font-size:11px}
.sqw-body .tf-preset-empty{font-size:10.5px;padding:6px}
/* 해제됨 오버레이는 이 층만 덮는다(층이 기준 상자). */
.sqw-body .tag-filter-released{position:absolute;inset:0}
/* ── 심층 검색 층: 옮겨 온 #refineView(모듈 팝업용 2칸 배치)를 창 폭에 맞춰 한 줄로 쌓는다 ── */
.sqw-body > #refineView{display:flex;padding:0;gap:8px}
.sqw-body #refineView .refine-header{border-bottom:none;padding-bottom:0;justify-content:flex-end}
/* 층 머리줄이 제목·되돌아가기를 맡는다 - 옛 [← SEARCH] 와 제목은 숨긴다. */
.sqw-body #refineView .refine-back,.sqw-body #refineView .refine-title{display:none}
.sqw-body #refineView .refine-header{justify-content:space-between}
.sqw-body #refineView .rf-side-toggle{display:inline-flex;align-items:center;height:20px;padding:0 9px;border-radius:4px;
  font-size:10px;font-weight:700;cursor:pointer;border:1px solid rgba(120,190,150,0.5);background:rgba(120,190,150,0.12);
  color:#bfe8cf;margin-right:auto}
.sqw-body #refineView .rf-side-toggle:hover{background:rgba(120,190,150,0.26);color:#fff}
/* 동반 창 '심층 검색 도구' - 옮겨 온 오른쪽 칸(샘플 · 스테이징 · 병합&내보내기) */
/* 저장된 필터 동반 창 - 옮겨 온 #tagFilterPresets 가 창 높이를 채우고, 백업 슬롯은 맨 위에 붙어 있다. */
.dragpanel.tfpw{border-color:rgba(245,220,138,0.35)}
.dragpanel.tfpw .dragpanel-head{background:rgba(245,220,138,0.07)}
.dragpanel.tfpw .dragpanel-body{display:flex;flex-direction:column;gap:6px;padding:7px;background:var(--bg-surface);overflow:hidden}
.dragpanel.tfpw .tfpw-search input{width:100%;box-sizing:border-box;height:24px;padding:2px 8px;font-size:11px;border-radius:5px;
  border:1px solid var(--border-dim,#33333f);background:var(--bg-deep,#0e0e12);color:var(--text-primary,#e8e8ee)}
.dragpanel.tfpw #tagFilterPresets{flex:1 1 auto;min-height:0;max-height:none;margin:0;padding:0 4px 4px;gap:3px;overflow-y:auto;
  background:rgba(0,0,0,0.24);border-radius:6px}
.dragpanel.tfpw #tagFilterPresets .tf-preset.is-backup{position:sticky;top:0;z-index:1;margin:0 -4px 2px;padding-left:14px;
  background:var(--bg-deep,#0e0e12);border-radius:6px 6px 0 0}
.dragpanel.tfpw .tf-preset-name{font-size:11px}
.dragpanel.rfsw{border-color:rgba(120,190,150,0.42)}
.dragpanel.rfsw .dragpanel-head{background:rgba(120,190,150,0.10)}
.dragpanel.rfsw .dragpanel-body{padding:8px;background:var(--bg-surface);overflow:auto}
.dragpanel.rfsw .refine-right{display:flex;flex-direction:column;gap:8px;width:100%}
.dragpanel.rfsw .refine-preview,.dragpanel.rfsw .refine-stageboard,.dragpanel.rfsw .refine-staging{padding:8px;border-radius:8px}
.dragpanel.rfsw .rf-prev-body{min-height:80px}
.dragpanel.rfsw .mod-action-btn{height:26px;min-height:26px;font-size:11px;padding:0 8px}
.dragpanel.rfsw .rf-sample-btn,.dragpanel.rfsw .rf-gen-btn{height:24px;font-size:10.5px}
.sqw-body #refineView .refine-2col{flex-direction:column;gap:8px}
.sqw-body #refineView .refine-left,.sqw-body #refineView .refine-right{flex:1 1 auto;width:100%;gap:7px}
.sqw-body #refineView .mod-input{height:24px;padding:2px 7px;font-size:11px}
.sqw-body #refineView .depth-filter-grid{display:grid;grid-template-columns:auto 1fr;gap:4px 8px;align-items:center}
.sqw-body #refineView .refine-actions-island,.sqw-body #refineView .refine-stageboard,
.sqw-body #refineView .refine-staging,.sqw-body #refineView .refine-preview{padding:8px;border-radius:8px}
.sqw-body #refineView .rf-prev-body{min-height:60px}
/* 컴팩트(다른 층과 같은 톤): 행 수는 작게 · 등급은 한 줄 · 숫자 필터는 두 쌍씩 */
.sqw-body #refineView .rf-counts{display:flex;gap:12px;align-items:flex-end}
.sqw-body #refineView .rf-counts > div{flex:1 1 0;min-width:0}
.sqw-body #refineView .search-count-display{font-size:17px;line-height:1.2}
.sqw-body #refineView .mod-checkbox-grid{display:flex;flex-wrap:wrap;gap:2px 12px}
.sqw-body #refineView .mod-checkbox-item{display:inline-flex;align-items:center;gap:4px;margin:0}
.sqw-body #refineView .mod-checkbox-label{font-size:10.5px}
.sqw-body #refineView .depth-filter-grid{grid-template-columns:auto minmax(0,1fr) auto minmax(0,1fr);gap:3px 8px}
.sqw-body #refineView .mod-input-sm{height:22px;padding:1px 6px;font-size:10.5px}
.sqw-body #refineView .mod-action-btn{height:26px;min-height:26px;font-size:11px;padding:0 8px}
.sqw-body #refineView .rf-sample-btn,.sqw-body #refineView .rf-gen-btn{height:24px;font-size:10.5px}
/* 잠금은 본문 전체(모든 층)를 덮고 머리줄은 남긴다. */
.dragpanel.sqw > .dragpanel-body > #tagFilterLock{position:absolute;inset:0;z-index:5}
`;
