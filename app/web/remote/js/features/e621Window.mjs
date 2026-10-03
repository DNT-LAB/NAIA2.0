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

import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'e6w-style';

export function createE621Window({
  document: doc,
  window: win,
  host,
  // 닫혀 있다가 열렸을 때 - 서버 상태를 한 번 받는다(예전 openModule 이 하던 일).
  onShow = () => {},
  onHide = () => {},
  onVisibilityChange = () => {},
  escHtml,
}) {
  ensureStyle(doc);

  // 처음 크기 · 자리는 화면에 맞춘다(세 칸 + 상세 두 칸이라 넓게 시작한다). 좁은 화면이면 화면 안으로 줄인다.
  const vw = win?.innerWidth || doc.documentElement.clientWidth || 1280;
  const vh = win?.innerHeight || doc.documentElement.clientHeight || 800;
  const width = Math.max(320, Math.min(1080, vw - 12));
  const height = Math.max(300, Math.min(740, vh - 70));

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title: 'E621 연구모듈',
    variant: 'e6w',
    storageKey: 'e621-research',
    width,
    minWidth: Math.min(420, width),
    maxWidth: 2000,
    height,
    minHeight: 300,
    resizable: true,
    // 왼쪽 프롬프트 열 바로 옆에서 시작한다. 좁으면 화면 안으로 당긴다.
    initial: { x: Math.max(6, Math.min(500, vw - width - 6)), y: 56 },
    escHtml,
    onOpen: () => onVisibilityChange(),
    onClose: () => {
      onHide();
      onVisibilityChange();
    },
    onCollapse: () => onVisibilityChange(),
  });
  panel.el.id = 'e621ResearchWindow';
  host.classList.add('e621-host');
  panel.body.appendChild(host);

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
    if (!wasOpen && requestState) onShow();
    onVisibilityChange();
  }

  return {
    el: panel.el,
    show,
    close: () => panel.close(),
    isOpen: () => panel.isOpen(),
    isShown: () => panel.isOpen() && !panel.isCollapsed(),
  };
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = E6W_CSS;
  doc.head.appendChild(style);
}

// 배치와 크기만 정한다. ⚠️ 색은 style.css 의 기존 `.e621-*` 규칙에 맡긴다(조건부 창 때 사용자 검토 - 색을 덮었다가
// 되돌렸다). 모든 규칙은 `.dragpanel.e6w` 아래로 한정한다 - 떼어 낸 창의 옛 모듈 팝업 배치로 새지 않는다.
// 창 폭에 따른 배치는 **컨테이너 질의**로 한다(화면 폭이 아니라 창 폭을 봐야 한다).
const E6W_CSS = `
.dragpanel.e6w .dragpanel-body{padding:0;gap:0;overflow:hidden;position:relative;background:var(--bg-surface);
  container-type:inline-size;container-name:e6w}
.dragpanel.e6w .e621-host{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;padding:6px 8px 8px;box-sizing:border-box}
.dragpanel.e6w .e621-loading{padding:16px;text-align:center}

/* 위에서부터: 검색줄 · 필터줄 · [카테고리 | 폴더 | 태그 | 선택한 태그] · 낮은 띠 [테스트벤치 | 숨긴 태그].
   선택한 태그 칸(번역 · 본문)이 창 높이를 다 쓴다(사용자 지정 2026-10-03). */
.dragpanel.e6w .e621-panel{flex:1 1 auto;height:100%;min-height:0;display:grid;
  grid-template-rows:auto auto minmax(0,1fr) minmax(96px,0.2fr);gap:6px}
.dragpanel.e6w .e621-toolbar{gap:5px}
.dragpanel.e6w .e621-toolbar .mod-input{height:24px;min-height:24px;padding:2px 8px;font-size:11px}
.dragpanel.e6w .e621-toolbar .mod-btn-sm{height:24px;padding:0 10px;font-size:10.5px}
.dragpanel.e6w .e621-toolbar.compact{gap:4px 8px}
.dragpanel.e6w .e621-toolbar.compact .mod-btn-sm{height:22px;padding:0 9px}
.dragpanel.e6w .e621-toolbar.compact .mod-check-row{min-height:22px;padding:0;font-size:10.5px}
.dragpanel.e6w .e621-description-filter{font-size:10.5px}
.dragpanel.e6w .e621-research-summary{font-size:9.5px;line-height:1.4}

.dragpanel.e6w .e621-layout.has-detail{min-height:0;gap:6px;
  grid-template-columns:minmax(140px,0.75fr) minmax(110px,0.5fr) minmax(200px,1fr) minmax(250px,1.2fr)}
.dragpanel.e6w .e621-column{display:flex;flex-direction:column;min-height:0}
.dragpanel.e6w .e621-column.categories{display:grid;grid-template-rows:auto minmax(0,1fr) auto minmax(0,0.45fr)}
.dragpanel.e6w .e621-chip-grid,.dragpanel.e6w .e621-scroll-list{overflow:auto}
.dragpanel.e6w .e621-scroll-list{flex:1;max-height:none;padding:3px;gap:3px}
.dragpanel.e6w .e621-chip-grid{gap:3px}
.dragpanel.e6w .e621-chip,.dragpanel.e6w .e621-list-item,.dragpanel.e6w .e621-hidden-item{min-height:26px;padding:3px 7px;gap:6px}
.dragpanel.e6w .e621-pagination{padding-top:4px}
.dragpanel.e6w .e621-pagination .mod-btn-sm{height:22px;padding:0 10px;font-size:10.5px}

.dragpanel.e6w .e621-bottom{min-height:0;gap:6px}
.dragpanel.e6w .e621-detail-card{display:flex;flex-direction:column;min-height:0;padding:6px 8px}
.dragpanel.e6w .e621-selected-actions .mod-btn-sm{height:22px;padding:0 9px;font-size:10.5px}
.dragpanel.e6w .e621-testbench-row #e621Testbench{flex:1 1 auto;min-height:40px;font-size:11px}
.dragpanel.e6w .e621-testbench-row .mod-start{height:auto;margin:0;padding:0 16px}
.dragpanel.e6w .e621-hidden-list{flex:1;max-height:none}

/* 창이 좁으면(창 폭 기준) 한 줄로 쌓고 창 안을 굴린다. */
@container e6w (max-width: 760px){
  .dragpanel.e6w .e621-panel{display:flex;flex-direction:column;overflow:auto}
  .dragpanel.e6w .e621-layout.has-detail,.dragpanel.e6w .e621-bottom{grid-template-columns:minmax(0,1fr)}
  .dragpanel.e6w .e621-column.categories{display:flex}
  .dragpanel.e6w .e621-chip-grid{max-height:150px}
  .dragpanel.e6w .e621-scroll-list{flex:0 0 auto;max-height:220px}
  .dragpanel.e6w .e621-detail-card{min-height:auto}
  .dragpanel.e6w .e621-column.detail .e621-research-details{max-height:320px}
  .dragpanel.e6w .e621-testbench-row #e621Testbench{min-height:70px}
}
`;
