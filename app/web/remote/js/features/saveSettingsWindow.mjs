// Auto Save · Save Directory 창 - 떠 있는 창 하나씩(사용자 지시 2026-11-18).
//
// 예전에는 왼쪽 모듈 팝업(#modulePopupBody)에 그렸다. 이제는 PE · 조건부 창과 같은 draggablePanel 에 산다:
// 끌기 · 크기 조절 · 접기 · 자리 기억, 그리고 생성하는 동안 옆에 열어 둘 수 있다.
// 본문은 각 패널(autoSavePanel · saveDirectoryPanel)이 그린다 - 여기는 껍데기와 `host` 만 준다.
//
// ⚠️ draggablePanel 은 다른 창과 같은 URL(?v=)로 불러온다(다르면 창끼리 겹침 순서가 깨진다).
// ⚠️ 별도 브라우저 창으로 떼어 낸 모듈(?detached=module)은 그 창 전체가 모듈 팝업이다 - 그 길은 이 창을 만들지 않는다
//    (app.js 의 saveUsesWindow).
// ⚠️ 창을 열어 둔 채 서버가 상태를 다시 보내면 본문 전체를 다시 그린다. 글을 적던 칸이 있으면 **그리기를 미뤘다가**
//    칸을 떠날 때 그린다(`paintWhenIdle`). 적는 도중에 칸을 갈아 끼우면 글이 지워지고, 숫자 칸은 반쯤 친 값
//    (3000 을 치다 만 30)이 change 로 서버에 가서 히스토리 한도가 100 으로 내려갔다(Codex 리뷰 2026-11-18 HIGH).

import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const STYLE_ID = 'savewin-style';

const SAVEWIN_CSS = `
.dragpanel.savewin .dragpanel-body{padding:0;gap:0;overflow:hidden;background:var(--bg-surface)}
.dragpanel.savewin .savewin-host{flex:1 1 auto;min-height:0;overflow-y:auto;padding:12px 14px;display:flex;flex-direction:column;gap:10px;box-sizing:border-box}
.dragpanel.savewin .dragpanel-slot{justify-content:flex-end;gap:4px}
.savewin-head-btn{flex:0 0 auto;height:22px;padding:0 8px;border:1px solid var(--border-dim);border-radius:4px;background:transparent;
  color:var(--text-muted);font-family:var(--font-display);font-size:11px;white-space:nowrap;cursor:pointer}
.savewin-head-btn:hover{background:var(--bg-hover);color:var(--text-primary)}
.dragpanel.savewin .auto-save-unsaved-section{flex-wrap:wrap}
.dragpanel.savewin .auto-save-unsaved-count{flex:1 0 auto}
`;

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = SAVEWIN_CSS;
  doc.head.appendChild(style);
}

export function createSaveSettingsWindow({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  title,
  storageKey,
  width = 360,
  height = 600,
  // 닫혀 있다가 열렸을 때 - 서버에 최신 상태를 묻는다(카운터는 생성 때 방송되지 않는다).
  onShow = () => {},
  // 열 때 받아 둔 상태가 있으면 바로 그린다(빈 창보다 낫다).
  renderCached = () => false,
  // 창이 닫힐 때 - 0.5초 대기 중인 글(분류 규칙 등)을 지금 보낸다. 예전 모듈 팝업의 closeModule 이 하던 일.
  onClose = () => {},
  // 없으면 ↗ 단추를 만들지 않는다(예전 모듈 팝업 머리줄의 '떼어 내기' - PE 창과 같다).
  onDetach = null,
  escHtml,
}) {
  ensureStyle(doc);
  const vw = win?.innerWidth || doc.documentElement.clientWidth || 1280;
  const vh = win?.innerHeight || doc.documentElement.clientHeight || 800;
  const w = Math.max(280, Math.min(width, vw - 12));
  const h = Math.max(220, Math.min(height, vh - 70));

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title,
    variant: 'savewin',
    storageKey,
    width: w,
    minWidth: Math.min(280, w),
    maxWidth: 720,
    height: h,
    minHeight: 160,
    resizable: true,
    escHtml,
    onClose: () => onClose(),
  });
  const host = doc.createElement('div');
  host.className = 'savewin-host';
  panel.body.appendChild(host);

  if (typeof onDetach === 'function') {
    const detachBtn = doc.createElement('button');
    detachBtn.type = 'button';
    detachBtn.className = 'savewin-head-btn savewin-detach';
    detachBtn.textContent = '↗';
    detachBtn.title = 'Open detached window';
    detachBtn.setAttribute('aria-label', 'Open detached window');
    detachBtn.addEventListener('click', () => onDetach());
    panel.slot.appendChild(detachBtn);
  }

  /** 창을 연다. 펼쳐져 있고 toggle 이면 닫는다(런처 단추를 다시 누른 것). */
  function show({toggle = false, requestState = true} = {}) {
    const wasOpen = panel.isOpen();
    if (wasOpen && toggle && !panel.isCollapsed()) {
      panel.close();
      return;
    }
    if (!wasOpen && !renderCached() && !host.firstElementChild) {
      host.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
    }
    panel.open();
    if (panel.isCollapsed()) panel.expand();
    panel.raise?.();
    // 폰처럼 좁은 화면에서는 첫 자리(FN | Result 경계)에서 창이 화면 밖으로 삐져나간다 - 다 보이면 두고, 아니면 안으로 당긴다.
    panel.bringIntoView?.();
    // 열려 있던 창을 다시 불러도 묻는다 - 생성 뒤의 카운터 · 저장 안 됨 개수가 그 사이 바뀌었다.
    // 떼어 낸 창을 다시 붙일 때는 넘어온 상태가 있으니 묻지 않는다(requestState=false).
    if (requestState) onShow();
  }

  return {
    host,
    show,
    close: () => panel.close(),
    isOpen: () => panel.isOpen(),
    isShown: () => panel.isOpen() && !panel.isCollapsed(),
  };
}

function isTextEntry(el) {
  if (!el) return false;
  if (el.tagName === 'TEXTAREA') return true;
  return el.tagName === 'INPUT' && /^(text|search|number|url|)$/i.test(el.type || '');
}

const PENDING_PAINT = new WeakMap();

/** 본문을 다시 그린다. 단, 이 본문 안의 글칸(input/textarea)에 글을 적는 중이면 **미뤘다가** 그 칸을 떠날 때 그린다.
 *  - 칸에서 칸으로 옮겨 가며 적는 동안은 계속 미룬다(마지막 그리기 하나만 남긴다).
 *  - 떠날 때는 change → focusout 순서라, 그 칸의 change 처리(서버로 보내기)가 먼저 끝난 뒤 그린다.
 *  - select · 단추에 있을 때는 바로 그린다(분류를 바꾸면 규칙 칸이 곧바로 보여야 한다). */
export function paintWhenIdle(doc, host, paint) {
  const active = doc.activeElement;
  if (!host || !active || !host.contains(active) || !isTextEntry(active)) {
    PENDING_PAINT.delete(host);
    paint();
    return;
  }
  const waiting = PENDING_PAINT.has(host);
  PENDING_PAINT.set(host, paint);
  if (waiting) return;
  const onOut = () => {
    setTimeout(() => {
      const now = doc.activeElement;
      if (now && host.contains(now) && isTextEntry(now)) return;   // 다른 글칸으로 옮겼다 - 다음에 떠날 때
      host.removeEventListener('focusout', onOut);
      const later = PENDING_PAINT.get(host);
      PENDING_PAINT.delete(host);
      if (later) later();
    }, 0);
  };
  host.addEventListener('focusout', onOut);
}
