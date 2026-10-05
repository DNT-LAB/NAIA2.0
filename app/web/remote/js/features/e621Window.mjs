// E621 연구모듈 창 - 떠 있는 창 하나(사용자 지정 2026-10-03: "Artist Thumbnail, Danbooru 처럼 분리형 윈도우").
//
// 예전에는 좌측 모듈 팝업(#modulePopup)을 화면 거의 전체로 넓혀 썼다(.module-popup-e621). 이제는 조건부 프롬프트
// 창과 같은 draggablePanel 에 산다: 끌기 · 크기 조절 · 접기 · 자리 기억, 그리고 다른 모듈과 함께 열어 둘 수 있다.
//
// ⚠️ draggablePanel 은 같은 URL(?v=)로 불러와야 z 레지스트리를 나눠 쓴다(다르면 창끼리 겹침 순서가 깨진다).
// ⚠️ 별도 브라우저 창으로 떼어 낸 모듈(?detached=module&module=e621_event)은 그 창 전체가 모듈 팝업이다 - 그 길은
//    이 창을 만들지 않고 예전 배치를 그대로 쓴다(app.js 의 e621UsesWindow).
//
// 내용은 e621EventPanel 이 그린다 - 이 모듈은 창만 만든다(본문 = `host`).
//
// 작게 보기(사용자 지정 2026-10-05): 머리줄의 단추로 켠다. 창이 좁아지고(분류 · 폴더가 숨고 태그 아래에 보낼 프롬프트가
// 붙는다 - 그 배치는 패널이 한다), 선택한 태그의 설명은 이 창 옆에 뜨는 작은 창으로 나간다. 그 작은 창은 '누르면 뜨는
// 툴팁' 이다: 다른 곳을 누르거나, 생성하거나, × 를 누를 때까지 떠 있다.

import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'e6w-style';
const COMPACT_KEY = 'naia.e621.compact';
const COMPACT_WIDTH = 480;      // 툴바 한 줄(검색 · 보기 · 설명 상태 · 숨김 · 설정)이 접히지 않는 폭(실측: 471 부터)

export function createE621Window({
  document: doc,
  window: win,
  host,
  // 닫혀 있다가 열렸을 때 - 서버 상태를 한 번 받는다(예전 openModule 이 하던 일).
  onShow = () => {},
  onHide = () => {},
  onVisibilityChange = () => {},
  // 작게 보기를 켜거나 껐다 - 패널이 배치를 바꾼다.
  onCompactChange = () => {},
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  escHtml,
}) {
  ensureStyle(doc);

  // 처음 크기 · 자리는 화면에 맞춘다(네 칸이라 넓게 시작한다). 좁은 화면이면 화면 안으로 줄인다.
  const vw = win?.innerWidth || doc.documentElement.clientWidth || 1280;
  const vh = win?.innerHeight || doc.documentElement.clientHeight || 800;
  const width = Math.max(320, Math.min(1080, vw - 12));
  const height = Math.max(300, Math.min(740, vh - 70));

  let compact = false;
  try {
    compact = storage?.getItem(COMPACT_KEY) === '1';
  } catch (error) { /* 저장소를 못 읽으면 크게 시작한다 */ }
  // 보기마다 쓰던 폭(이번 실행 동안). 없으면 그 보기의 기본 폭.
  const widths = {full: null, compact: null};
  // 창의 폭이 지금 어느 보기에 맞춰져 있는가. 처음 열 때 작게 보기가 켜져 있으면 그때 줄인다.
  let sizedFor = 'full';

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title: 'E621 연구모듈',
    variant: 'e6w',
    storageKey: 'e621-research',
    width,
    minWidth: Math.min(340, width),
    maxWidth: 2000,
    height,
    minHeight: 300,
    resizable: true,
    // 왼쪽 프롬프트 열 바로 옆에서 시작한다. 좁으면 화면 안으로 당긴다.
    initial: { x: Math.max(6, Math.min(500, vw - width - 6)), y: 56 },
    escHtml,
    onOpen: () => onVisibilityChange(),
    onClose: () => {
      detail.close();
      onHide();
      onVisibilityChange();
    },
    onCollapse: () => {
      detail.close();
      onVisibilityChange();
    },
  });
  panel.el.id = 'e621ResearchWindow';
  host.classList.add('e621-host');
  panel.body.appendChild(host);

  // 머리줄의 [작게 보기] 단추. 접기 · 닫기 바로 왼쪽에 둔다.
  const modeBtn = doc.createElement('button');
  modeBtn.type = 'button';
  modeBtn.className = 'e6w-mode';
  modeBtn.textContent = '작게 보기';
  panel.slot.appendChild(modeBtn);
  modeBtn.addEventListener('click', () => setCompact(!compact));

  // 선택한 태그의 설명이 나가는 작은 창(작게 보기에서만 쓴다). 이 창을 따라다니고, 끌어서 옮길 수 있다.
  const detail = createDraggablePanel({
    document: doc,
    window: win,
    title: '선택한 태그',
    variant: 'e6w e6w-detail',
    storageKey: 'e621-research-detail',
    parentPanel: panel,
    width: 340,
    minWidth: 240,
    maxWidth: 900,
    height: Math.max(220, Math.min(440, vh - 120)),
    minHeight: 140,
    resizable: true,
    collapsible: false,
    escHtml,
  });
  detail.el.id = 'e621DetailWindow';
  const detailHost = doc.createElement('div');
  detailHost.className = 'e621-detail-host';
  detail.body.appendChild(detailHost);

  // 설명 창은 '누르면 뜨는 툴팁' 이다 - 다른 곳을 누르면 닫는다. 태그 목록 안(다른 태그를 누르거나 목록을 굴린다)은
  // 닫지 않는다: 다른 태그를 누르면 그 태그의 설명으로 바뀔 뿐이다.
  doc.addEventListener('pointerdown', event => {
    if (!detail.isOpen()) return;
    const target = event.target;
    if (detail.el.contains(target) || target?.closest?.('.e6-tags')) return;
    detail.close();
  }, true);

  function paintMode() {
    modeBtn.classList.toggle('on', compact);
    modeBtn.setAttribute('aria-pressed', String(compact));
    modeBtn.title = compact ? '작게 보기를 끕니다 - 분류 · 폴더 · 설명 칸이 돌아옵니다'
      : '작게 보기 - 태그 목록과 보낼 프롬프트만 남기고, 설명은 태그를 누르면 옆에 뜹니다';
  }

  // 창의 폭을 지금 보기에 맞춘다. 떠나는 보기의 폭은 적어 두었다가 돌아올 때 되살린다.
  function fitWidth() {
    const mode = compact ? 'compact' : 'full';
    if (sizedFor === mode || !panel.isOpen()) return;
    const rect = panel.el.getBoundingClientRect();
    if (rect.width > 0) widths[sizedFor] = rect.width;
    sizedFor = mode;
    panel.sizeTo(widths[mode] ?? (compact ? COMPACT_WIDTH : width), panel.isCollapsed() ? NaN : rect.height);
  }

  function setCompact(next) {
    next = Boolean(next);
    if (compact === next) return;
    compact = next;
    try {
      storage?.setItem(COMPACT_KEY, compact ? '1' : '0');
    } catch (error) { /* 못 적으면 이번 실행에만 산다 */ }
    if (!compact) detail.close();
    paintMode();
    fitWidth();
    onCompactChange(compact);
  }

  /** 창을 연다. 펼쳐져 있고 toggle 이면 닫는다(모듈 단추를 다시 누른 것). */
  function show({ toggle = false, requestState = true } = {}) {
    const wasOpen = panel.isOpen();
    if (wasOpen && toggle && !panel.isCollapsed()) {
      panel.close();
      return;
    }
    // 한 번도 그려진 적이 없으면 빈 창 대신 '불러오는 중' 을 보인다(빈 창은 고장으로 보인다).
    if (!host.firstElementChild) host.innerHTML = '<div class="mod-empty e621-loading">E621 사전을 불러오는 중…</div>';
    panel.open();
    if (panel.isCollapsed()) panel.expand();
    fitWidth();
    if (!wasOpen && requestState) onShow();
    onVisibilityChange();
  }

  paintMode();

  return {
    el: panel.el,
    show,
    close: () => panel.close(),
    isOpen: () => panel.isOpen(),
    isShown: () => panel.isOpen() && !panel.isCollapsed(),
    isCompact: () => compact,
    setCompact,
    // 패널이 설명을 그리는 자리와, 그 창을 여닫는 손잡이.
    detail: {
      host: detailHost,
      open: () => { if (compact && panel.isOpen() && !panel.isCollapsed()) detail.open(); },
      close: () => detail.close(),
      isOpen: () => detail.isOpen(),
    },
  };
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = E6W_CSS;
  doc.head.appendChild(style);
}

// 창 본문의 크기만 정한다. 패널의 배치 · 모양 · 폭 반응은 전부 e621EventPanel 의 PANEL_CSS 가 싣는다
// (.e6-root 가 컨테이너라 창 폭을 스스로 잰다) - 떼어 낸 브라우저 창의 모듈 팝업에서도 같은 화면이 나온다.
const E6W_CSS = `
.dragpanel.e6w .dragpanel-body{padding:0;gap:0;overflow:hidden;position:relative;background:var(--bg-surface)}
.dragpanel.e6w .e621-host{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;padding:8px;box-sizing:border-box}
.dragpanel.e6w .e621-loading{padding:16px;text-align:center}
.dragpanel.e6w .dragpanel-slot{justify-content:flex-end}
.e6w-mode{flex:0 0 auto;height:22px;padding:0 8px;border:1px solid var(--border-dim);border-radius:4px;background:transparent;
  color:var(--text-muted);font-family:var(--font-display);font-size:11px;white-space:nowrap;cursor:pointer}
.e6w-mode:hover{background:var(--bg-hover);color:var(--text-primary)}
.e6w-mode.on{border-color:var(--accent);background:rgba(124,106,239,0.24);color:var(--text-primary)}
.dragpanel.e6w-detail .e621-detail-host{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
`;
