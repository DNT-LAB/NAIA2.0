// 프롬프트 엔지니어링 창 - 떠 있는 창 하나(사용자 지시 2026-10-15: PE 개편 1단계 · docs/PE_WINDOW_REDESIGN_2026_10_15.md).
//
// 예전에는 왼쪽 모듈 팝업(#modulePopup)에 그렸다. 이제는 조건부 프롬프트 · E621 창과 같은 draggablePanel 에 산다:
// 끌기 · 크기 조절 · 접기 · 자리 기억, 그리고 다른 모듈과 함께 열어 둘 수 있다.
// 본문은 promptEngineeringPanel 이 그린다(본문 = `host`). 2단계(2026-10-15)부터 2단이다 - 창이 좁으면 1단으로 접힌다
// (패널의 .pe-layout 컨테이너 질의 - 화면 폭이 아니라 창 폭을 본다).
//
// ⚠️ draggablePanel 은 다른 창과 같은 URL(?v=)로 불러온다(다르면 창끼리 겹침 순서가 깨진다).
// ⚠️ 별도 브라우저 창으로 떼어 낸 모듈(?detached=module&module=prompt_engineering)은 그 창 전체가 모듈 팝업이다 - 그 길은
//    이 창을 만들지 않고 예전 배치를 그대로 쓴다(app.js 의 peUsesWindow).
// ⚠️ 보조 창 여섯(프리셋 추가 · 관리 · e621 · Danbooru · AI 부스트 설정 · Setting & Preview)은 **떠 있는 창**이다(사용자 지시
//    2026-10-15 - 결정 D4 를 A '붙는 팝업' 에서 바꿨다). 이벤트 맵 창과 같은 껍데기(`em-overlay em-window` - 얇은 핸들 줄)이고
//    이 창의 자식이라 이 창을 끌면 따라온다(draggablePanel 의 부모 따라가기 · 핀으로 풀 수 있다). 내용은 예전 `.pe-popup`
//    요소를 통째로 옮겨 담는다 - id · `.pe-popup-body` 를 그리는 렌더러는 그대로다(openAux). 접거나 닫으면 onAuxClose 로 닫는다.
//
// 머리줄에는 예전 모듈 팝업 머리줄의 단추를 그대로 옮긴다: [추천 설정 적용](모드가 받을 때만) · ⓘ 가이드 · ↗(떼어 내기).

import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'pew-style';
// 2단이 들어가는 폭(왼쪽 프롬프트 칸 · 오른쪽 전처리 2열). 본문이 680px 아래면 1단이 된다(style.css .pe-layout).
const START_WIDTH = 780;
// 보조 창의 id - 이벤트 맵의 보조 창(`permExcludeWindow`)처럼 창마다 하나.
const AUX_IDS = {
  presetAdd: 'pePresetAddWindow',
  presetManage: 'pePresetManageWindow',
  e621: 'peE621Window',
  danbooru: 'peDanbooruWindow',
  ollamaBoost: 'peAiBoostWindow',
  debug: 'peDebugWindow',
};

export function createPromptEngineeringWindow({
  document: doc,
  window: win,
  host,
  // 머리줄 ⓘ 의 문구(예전 모듈 팝업의 개요 가이드와 같은 글).
  overviewGuide = '',
  // 닫혀 있다가 열렸을 때 - 받아 둔 상태로 그리고 서버에 한 번 더 묻는다(예전 openModule 이 하던 일).
  onShow = () => {},
  // 창이 닫힐 때 - 0.5초 대기 중인 편집과 칸의 글을 보내야 한다(안 그러면 사라진다).
  onHide = () => {},
  onVisibilityChange = () => {},
  // 창이 옮겨지거나 크기가 바뀌는 중이다(프레임마다) - 붙어 있는 보조 창을 다시 앉힌다.
  onMove = () => {},
  // 접거나 닫았다 - 붙어 있는 보조 창을 닫는다.
  onAuxClose = () => {},
  onApplyRecommended = () => {},
  // 없으면 ↗ 단추를 만들지 않는다.
  onDetach = null,
  escHtml,
}) {
  ensureStyle(doc);

  // 처음 크기 · 자리는 화면에 맞춘다 - 폰에서 창이 화면 밖으로 나가지 않게(조건부 창에서 실측한 일).
  const vw = win?.innerWidth || doc.documentElement.clientWidth || 1280;
  const vh = win?.innerHeight || doc.documentElement.clientHeight || 800;
  const width = Math.max(300, Math.min(START_WIDTH, vw - 12));
  // 2단의 내용 높이(왼쪽 프롬프트 칸 넷)에 맞춘다 - 예전 팝업 높이(760)로 열면 아래가 비었다. 1단이면 본문이 구른다.
  const height = Math.max(260, Math.min(620, vh - 70));

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title: '프롬프트 엔지니어링',
    variant: 'pew',
    storageKey: 'prompt-engineering',
    width,
    minWidth: Math.min(320, width),
    maxWidth: 1400,
    height,
    minHeight: 240,
    resizable: true,
    // 왼쪽 프롬프트 열 바로 옆에서 시작한다(조건부 · E621 창과 같은 자리). 좁으면 화면 안으로 당긴다.
    initial: { x: Math.max(6, Math.min(500, vw - width - 6)), y: 56 },
    escHtml,
    onOpen: () => onVisibilityChange(),
    onClose: () => {
      onAuxClose();
      onHide();
      onVisibilityChange();
    },
    onCollapse: () => {
      onAuxClose();
      onVisibilityChange();
    },
  });
  panel.el.id = 'promptEngineeringWindow';
  // 끄는 **동안** 따라오게 프레임마다 나는 이동 · 크기 신호를 듣는다(`onMove` 옵션은 손을 뗄 때만 온다).
  // 붙어 있는 자식 창(draggablePanel 의 부모 따라가기)이 듣는 신호와 같다.
  panel.el.addEventListener('dragpanel-move', () => onMove());
  panel.el.addEventListener('dragpanel-resize', () => onMove());
  host.classList.add('pew-host');
  panel.body.appendChild(host);

  // ── 머리줄 단추(예전 모듈 팝업 머리줄의 것) ─────────────────────────────
  const recommendBtn = doc.createElement('button');
  recommendBtn.type = 'button';
  recommendBtn.className = 'pew-head-btn pew-recommend';
  recommendBtn.textContent = '추천 설정 적용';
  recommendBtn.hidden = true;
  recommendBtn.addEventListener('click', () => onApplyRecommended());
  panel.slot.appendChild(recommendBtn);

  if (overviewGuide) {
    const guideBtn = doc.createElement('button');
    guideBtn.type = 'button';
    guideBtn.className = 'pew-head-btn pew-guide';
    guideBtn.textContent = 'ⓘ 가이드';
    guideBtn.dataset.naiaGuide = overviewGuide;
    panel.slot.appendChild(guideBtn);
  }

  if (typeof onDetach === 'function') {
    const detachBtn = doc.createElement('button');
    detachBtn.type = 'button';
    detachBtn.className = 'pew-head-btn pew-detach';
    detachBtn.textContent = '↗';
    detachBtn.title = 'Open detached window';
    detachBtn.setAttribute('aria-label', 'Open detached window');
    detachBtn.addEventListener('click', () => onDetach());
    panel.slot.appendChild(detachBtn);
  }

  // ── 보조 창 ───────────────────────────────────────────────────────────
  const auxWindows = new Map();

  /** 보조 창을 연다(처음이면 만든다). popupEl = 예전 `.pe-popup` 요소 - 머리줄은 숨기고 ⓘ 가이드만 핸들 줄로 옮긴다.
   *  onClose = 창의 × (app.js 의 닫기 함수 - 상태 · 보류 중인 값을 정리한다). */
  function openAux(key, popupEl, { title = '', width: auxWidth = 420, height: auxHeight = 620, onClose = () => {} } = {}) {
    if (!popupEl) return false;
    let aux = auxWindows.get(key);
    if (!aux) {
      const viewH = win?.innerHeight || doc.documentElement.clientHeight || 800;
      aux = createDraggablePanel({
        document: doc,
        window: win,
        parentPanel: panel,
        id: AUX_IDS[key] || '',
        title,
        variant: 'em-overlay em-window pe-aux-window',
        storageKey: `prompt-engineering-aux-${key}`,
        width: auxWidth,
        height: Math.max(200, Math.min(auxHeight, viewH - 70)),
        minWidth: 300,
        maxWidth: 900,
        minHeight: 160,
        resizable: true,
        escHtml,
        onClose: () => onClose(),
      });
      const guide = popupEl.querySelector('.module-popup-header .header-guide-btn');
      if (guide) aux.slot.appendChild(guide);
      // 붙는 팝업 시절에 positionFloatingPanel 이 박아 둔 자리 · 크기를 걷는다 - 이제 창이 정한다.
      ['left', 'top', 'right', 'bottom', 'width', 'maxWidth', 'maxHeight'].forEach(prop => { popupEl.style[prop] = ''; });
      popupEl.classList.add('pe-popup--in-window');
      aux.body.appendChild(popupEl);
      auxWindows.set(key, aux);
    }
    aux.open();
    if (aux.isCollapsed()) aux.expand();
    // 구석에 박혀 일부가 화면 밖이면 PE 창 옆으로 끄집어낸다(사용자 지시 2026-10-17) - 다 보이면 둔 자리 그대로.
    aux.bringIntoView?.();
    return true;
  }

  function closeAux(key) {
    const aux = auxWindows.get(key);
    if (aux && aux.isOpen()) aux.close();
  }

  /** [추천 설정 적용] 은 그 모드가 추천 프리셋을 가질 때만(NAI · WEBUI · ComfyUI ANIMA - app.js 가 판단한다). */
  function setRecommended(visible) {
    recommendBtn.hidden = !visible;
  }

  /** 창을 연다. 펼쳐져 있고 toggle 이면 닫는다(모듈 단추를 다시 누른 것). */
  function show({ toggle = false, requestState = true } = {}) {
    const wasOpen = panel.isOpen();
    if (wasOpen && toggle && !panel.isCollapsed()) {
      panel.close();
      return;
    }
    // 한 번도 그려진 적이 없으면 빈 창 대신 '불러오는 중' 을 보인다(빈 창은 고장으로 보인다).
    if (!host.firstElementChild) {
      host.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
    }
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
    setRecommended,
    openAux,
    closeAux,
  };
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = PEW_CSS;
  doc.head.appendChild(style);
}

// 창 본문은 예전 모듈 팝업 본문(`.module-popup-body`)과 같은 여백 · 간격 · 바탕이다.
// 머리줄 단추는 E621 창의 [작게 보기] 와 같은 옷.
const PEW_CSS = `
.dragpanel.pew .dragpanel-body{padding:0;gap:0;overflow:hidden;background:var(--bg-surface)}
.dragpanel.pew .pew-host{flex:1 1 auto;min-height:0;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:12px;box-sizing:border-box}
.dragpanel.pew .dragpanel-slot{justify-content:flex-end;gap:4px}
.pew-head-btn{flex:0 0 auto;height:22px;padding:0 8px;border:1px solid var(--border-dim);border-radius:4px;background:transparent;
  color:var(--text-muted);font-family:var(--font-display);font-size:11px;white-space:nowrap;cursor:pointer}
.pew-head-btn:hover{background:var(--bg-hover);color:var(--text-primary)}
.pew-head-btn[hidden]{display:none}
.dragpanel.pe-aux-window .pe-popup{position:static;display:flex;flex:1 1 auto;min-height:0;width:auto!important;max-width:none!important;max-height:none!important;border:0;border-radius:0;box-shadow:none;background:transparent;z-index:auto}
.dragpanel.pe-aux-window .pe-popup>.module-popup-header{display:none}
.dragpanel.pe-aux-window .dragpanel-slot{justify-content:flex-end}
.dragpanel.pe-aux-window .dragpanel-slot .header-guide-btn{height:16px;padding:0 6px;font-size:10px;line-height:14px}
`;
