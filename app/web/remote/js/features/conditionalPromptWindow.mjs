// 조건부 프롬프트 창 - 떠 있는 창 하나(사용자 지정 2026-09-26: "새 플로팅 스타일로 바꾸고 컴팩트화").
//
// 예전에는 좌측 모듈 팝업(#modulePopup)을 화면 거의 전체(left/right 24px)로 넓혀 4칸(프리셋 · 규칙 목록 ·
// 조건 · 동작)을 늘어놓았다. 이제는 Search | Tag Filter 창과 같은 draggablePanel 에 산다:
// 끌기 · 크기 조절 · 접기 · 자리 기억, 그리고 **다른 모듈과 함께 열어 둘 수 있다**.
//
// ⚠️ draggablePanel 은 같은 URL(?v=)로 불러와야 z 레지스트리를 나눠 쓴다(다르면 창끼리 겹침 순서가 깨진다).
//
// 내용은 conditionalPromptPanel 이 그린다 - 이 모듈은 창과 동반 창(프리셋)만 만든다:
// - 본 창 본문 = `host`(패널의 moduleBody). 패널은 한 번 그리고 에코마다 다시 그린다.
// - 프리셋 = 동반 창 '조건부 프리셋'(`presetHost`). 예전의 창 안 팝오버는 1800px 기준의 화면 폭
//   미디어 쿼리에 묶여 넓은 화면에서 Legacy 로는 프리셋에 들어갈 길이 없던 적이 있다(Codex 지적).
//   창 폭과 무관하게 늘 같은 자리에 뜬다.
// - 창 폭에 따른 배치는 **컨테이너 질의**로 한다(화면 폭이 아니라 창 폭을 봐야 한다).

import { createDraggablePanel } from './draggablePanel.mjs?v=20260919-headdrag';

const STYLE_ID = 'cpw-style';

export function createConditionalPromptWindow({
  document: doc,
  window: win,
  host,
  presetHost = null,
  // 'Test Rules / Simulation' 동반 창 본문(사용자 지정 2026-09-26 - 본 창엔 결과를 둘 공간이 모자라다).
  simHost = null,
  // 닫혀 있다가 열렸을 때 - 서버 상태를 한 번 받는다(예전 openModule 이 하던 일).
  onShow = () => {},
  // 창이 닫힐 때 - 0.5초 대기 중인 Legacy 편집을 보내야 한다(안 그러면 사라진다).
  onHide = () => {},
  onVisibilityChange = () => {},
  onPresetsVisibility = () => {},
  escHtml,
}) {
  ensureStyle(doc);

  // 처음 크기·자리는 화면에 맞춘다 - 폰(375px)에서 660px 창이 화면 밖으로 나갔다(실측).
  const vw = win?.innerWidth || doc.documentElement.clientWidth || 1280;
  const vh = win?.innerHeight || doc.documentElement.clientHeight || 800;
  const width = Math.max(300, Math.min(660, vw - 12));
  const height = Math.max(240, Math.min(600, vh - 70));

  const panel = createDraggablePanel({
    document: doc,
    window: win,
    title: '조건부 프롬프트',
    variant: 'cpw',
    storageKey: 'conditional-prompt',
    width,
    minWidth: Math.min(380, width),
    maxWidth: 1400,
    height,
    minHeight: 240,
    resizable: true,
    // 왼쪽 프롬프트 열 바로 옆에서 시작한다(Search 창은 오른쪽 끝). 좁으면 화면 안으로 당긴다.
    initial: { x: Math.max(6, Math.min(500, vw - width - 6)), y: 56 },
    escHtml,
    onOpen: () => onVisibilityChange(),
    onClose: () => {
      if (presetsPanel && presetsPanel.isOpen()) presetsPanel.close();
      if (simPanel && simPanel.isOpen()) simPanel.close();
      onHide();
      onVisibilityChange();
    },
    onCollapse: () => onVisibilityChange(),
  });
  panel.el.id = 'conditionalPromptWindow';
  host.classList.add('cond-host');
  panel.body.appendChild(host);

  // ── 프리셋 동반 창 ─────────────────────────────────────────────────────
  let presetsPanel = null;

  /** 창 **오른쪽**(자리가 없으면 왼쪽). 처음 뜰 때만 쓰고, 그 뒤로는 창이 제 자리를 기억한다. */
  function besideSpot(width, height, anchorRect) {
    const vw = win?.innerWidth || doc.documentElement.clientWidth;
    const vh = win?.innerHeight || doc.documentElement.clientHeight;
    const roomRight = vw - anchorRect.right;
    const left = roomRight >= width + 16 ? anchorRect.right + 10 : anchorRect.left - width - 10;
    return {
      x: Math.round(Math.max(6, Math.min(left, vw - width - 6))),
      y: Math.round(Math.max(6, Math.min(anchorRect.top, vh - height - 6))),
    };
  }

  function ensurePresetsPanel() {
    if (presetsPanel || !presetHost) return presetsPanel;
    const width = 280;
    const height = 420;
    const spot = besideSpot(width, height, panel.el.getBoundingClientRect());
    presetsPanel = createDraggablePanel({
      document: doc,
      window: win,
      title: '조건부 프리셋',
      variant: 'cppw',
      storageKey: 'conditional-prompt-presets',
      width, height, minWidth: 220, maxWidth: 640, minHeight: 180,
      resizable: true,
      initial: { x: spot.x, y: spot.y },
      escHtml,
      onOpen: () => onPresetsVisibility(true),
      onClose: () => onPresetsVisibility(false),
    });
    presetsPanel.el.id = 'conditionalPresetWindow';
    presetHost.classList.add('cond-preset-host');
    presetsPanel.body.appendChild(presetHost);
    return presetsPanel;
  }

  function togglePresets() {
    const p = ensurePresetsPanel();
    if (!p) return false;
    if (p.isOpen()) p.close();
    else p.open();
    return true;
  }

  // ── Test Rules / Simulation 동반 창 ────────────────────────────────────
  // 결과 카드(규칙마다 바꾼 것 · 샘플 · 네거티브 · 최종 프롬프트)는 본 창에 둘 자리가 없다 - 옆에 띄운다.
  let simPanel = null;

  function ensureSimPanel() {
    if (simPanel || !simHost) return simPanel;
    const width = 400;
    const height = 520;
    const spot = besideSpot(width, height, panel.el.getBoundingClientRect());
    simPanel = createDraggablePanel({
      document: doc,
      parentPanel: panel,
      window: win,
      title: 'Test Rules / Simulation',
      variant: 'cpsw',
      storageKey: 'conditional-prompt-sim',
      width, height, minWidth: 260, maxWidth: 900, minHeight: 160,
      resizable: true,
      initial: { x: spot.x, y: spot.y },
      escHtml,
    });
    simPanel.el.id = 'conditionalSimulationWindow';
    simHost.classList.add('cond-sim-host');
    simPanel.body.appendChild(simHost);
    return simPanel;
  }

  function showSimulation() {
    const p = ensureSimPanel();
    if (!p) return false;
    p.open();
    if (p.isCollapsed()) p.expand();
    return true;
  }

  /** 창을 연다. 같은 창이 펼쳐져 있고 toggle 이면 닫는다(모듈 단추를 다시 누른 것). */
  function show({ toggle = false } = {}) {
    const wasOpen = panel.isOpen();
    if (wasOpen && toggle && !panel.isCollapsed()) {
      panel.close();
      return;
    }
    // 아직 한 번도 그려진 적이 없으면 빈 창 대신 '불러오는 중' 을 보인다(빈 창은 고장으로 보인다).
    if (!host.firstElementChild) host.innerHTML = '<div class="cond-empty cond-loading">조건부 설정을 불러오는 중…</div>';
    panel.open();
    if (panel.isCollapsed()) panel.expand();
    if (!wasOpen) onShow();
    onVisibilityChange();
  }

  return {
    el: panel.el,
    show,
    close: () => panel.close(),
    isOpen: () => panel.isOpen(),
    isShown: () => panel.isOpen() && !panel.isCollapsed(),
    togglePresets,
    isPresetsOpen: () => Boolean(presetsPanel && presetsPanel.isOpen()),
    showSimulation,
    isSimulationOpen: () => Boolean(simPanel && simPanel.isOpen()),
  };
}

function ensureStyle(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CPW_CSS;
  doc.head.appendChild(style);
}

// 컴팩트(Search 창과 같은 톤: 글자 10~11.5px, 단추·입력 22~24px).
// ⚠️ **크기만 줄인다. 색은 style.css 의 기존 `.cond-*` 규칙에 맡긴다**(Search 창 컴팩트 때 사용자 검토:
//    파란 채움·녹색 단추의 색을 덮었다가 되돌렸다). 모든 규칙은 `.dragpanel.cpw` / `.dragpanel.cppw`
//    아래로 한정한다 - 옛 모듈 팝업 배치(분리 창 등)로 새지 않는다.
// ⚠️ style.css 의 `@media (max-width:1800px/900px)` 는 **화면 폭**을 본다. 창 안에서는 그 규칙들을
//    같은 자리에서 더 굵은 선택자로 덮고, 창 폭은 `@container cpw` 로 따로 본다.
const CPW_CSS = `
.dragpanel.cpw{border-color:rgba(92,150,255,0.40)}
.dragpanel.cpw .dragpanel-head{background:rgba(92,150,255,0.08)}
.dragpanel.cpw .dragpanel-body{padding:0;gap:0;overflow:hidden;position:relative;background:var(--bg-surface);
  container-type:inline-size;container-name:cpw}
.dragpanel.cpw .cond-host{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;padding:6px 8px 7px;box-sizing:border-box}
.dragpanel.cpw .cond-root{position:relative;flex:1 1 auto;height:100%;min-height:0;overflow:hidden;gap:6px}
/* 문법 안내의 접힘은 옛 모듈 팝업 규칙(.module-popup-body .collapsed)에만 있었다 - 창 안에도 둔다. */
.dragpanel.cpw .collapsed{display:none}

/* ── 머리줄: 활성화 · 편집기 · (프리셋 · 되돌리기 · 가이드 · 적용 상태) 한 줄 ── */
.dragpanel.cpw .cond-topbar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;padding:0}
.dragpanel.cpw .cond-enable-row{min-height:22px;padding:0;gap:5px}
.dragpanel.cpw .cond-enable-row .mod-checkbox-label{font-size:10.5px}
.dragpanel.cpw .cond-mode-row{display:inline-flex;gap:0}
.dragpanel.cpw .cond-mode-btn{min-height:22px;height:22px;padding:0 10px;font-size:10.5px;border-radius:0}
.dragpanel.cpw .cond-mode-btn:first-child{border-radius:5px 0 0 5px}
.dragpanel.cpw .cond-mode-btn:last-child{border-radius:0 5px 5px 0;margin-left:-1px}
.dragpanel.cpw .cond-status-row{flex:1 1 auto;gap:5px;flex-wrap:wrap}
.dragpanel.cpw .cond-preset-toggle{display:inline-flex;align-items:center;min-height:22px;height:22px;padding:0 10px;
  font-size:10.5px;max-width:190px}
.dragpanel.cpw .cond-preset-toggle.is-open{border-color:rgba(245,220,138,0.7);color:#f5dc8a}
.dragpanel.cpw .cond-status-chip{max-width:none;padding:2px 7px}
.dragpanel.cpw .cond-guide-link{padding:2px 8px}

/* ── 알림 · 린트 · 요약 ── */
.dragpanel.cpw .cond-empty-notice{margin:0;padding:5px 9px;font-size:10.5px}
.dragpanel.cpw .cond-lint-box{margin:0;padding:6px 8px;font-size:10.5px;max-height:92px}
.dragpanel.cpw .cond-summary-box{min-height:0;max-height:none;padding:4px 9px;font-size:11px;line-height:1.4;
  white-space:nowrap;text-overflow:ellipsis}

/* ── New Editor: [규칙 목록 | (조건 / 동작)] 두 칸 ── */
.dragpanel.cpw .cond-v2-grid{flex:1 1 auto;min-height:0;display:grid;gap:6px;
  grid-template-columns:minmax(150px,32%) minmax(0,1fr);grid-template-rows:minmax(90px,1fr) fit-content(58%);overflow:hidden}
.dragpanel.cpw .cond-rule-pane{grid-column:1;grid-row:1 / span 2}
.dragpanel.cpw .cond-condition-pane{grid-column:2;grid-row:1}
.dragpanel.cpw .cond-action-pane{grid-column:2;grid-row:2;overflow:auto}
/* min-height:0 - style.css 의 @media (max-width:900px) .cond-pane{min-height:260px}(화면 폭 기준)가 폰에서 창을 넘치게 한다. */
.dragpanel.cpw .cond-pane{padding:6px 7px;gap:5px;border-radius:7px;min-height:0}
.dragpanel.cpw .cond-pane-title{font-size:11px;padding-left:6px;border-left-width:2px}
.dragpanel.cpw .cond-pane-title.small{font-size:10px}
.dragpanel.cpw .cond-pane-count{margin-left:4px;font-family:var(--font-mono);font-size:9.5px;font-weight:500;color:var(--text-muted)}
.dragpanel.cpw .cond-empty{padding:7px 8px;font-size:10.5px}
.dragpanel.cpw .cond-empty.compact{padding:5px 7px}

/* 규칙 목록 */
.dragpanel.cpw .cond-rule-list{flex:1 1 auto;gap:3px}
.dragpanel.cpw .cond-rule-item{min-height:26px;grid-template-columns:7px auto minmax(0,1fr) auto;gap:5px;padding:3px 6px;border-radius:5px}
.dragpanel.cpw .cond-rule-item .cond-badge.kind-leaf,.dragpanel.cpw .cond-rule-item .cond-badge.kind-group,
.dragpanel.cpw .cond-rule-item .cond-badge.kind-raw{display:none}
.dragpanel.cpw .cond-rule-dot{width:6px;height:6px}
.dragpanel.cpw .cond-rule-item strong{font-size:11px;font-weight:600}
.dragpanel.cpw .cond-rule-item small{font-size:9px}
.dragpanel.cpw .cond-badge{padding:1px 4px;font-size:9px}
.dragpanel.cpw .cond-rule-tools{display:grid;grid-template-columns:minmax(0,1fr) auto auto auto auto;gap:3px}

/* 단추는 한 벌로 줄인다(옛 규칙: 32px · 12px) */
.dragpanel.cpw .cond-rule-tools button,.dragpanel.cpw .cond-button-row button,
.dragpanel.cpw .cond-bottom-actions button,.dragpanel.cpw .cond-node-row button{
  min-height:22px;height:22px;padding:0 7px;font-size:10.5px;border-radius:5px;white-space:nowrap}
.dragpanel.cpw .cond-tool-add{font-weight:700}

/* 조건 */
.dragpanel.cpw .cond-condition-scroll{flex:1 1 auto;display:flex;flex-direction:column;gap:5px}
.dragpanel.cpw .cond-condition-card,.dragpanel.cpw .cond-action-card{flex:0 0 auto;gap:5px;padding:5px 6px;border-radius:5px}
.dragpanel.cpw .cond-condition-card.leaf{padding:3px 5px}
.dragpanel.cpw .cond-children{gap:4px;padding-left:4px}
.dragpanel.cpw .cond-node-row{gap:4px}
/* ⚠️ 기본 .mod-input/.mod-select 는 width:100% 라 한 줄에 모이지 않고 칸마다 줄을 바꾼다 - width:auto 로 푼다. */
.dragpanel.cpw .cond-node-row .mod-input,.dragpanel.cpw .cond-node-row .mod-select{flex:0 1 auto;width:auto;min-width:0;height:22px;min-height:22px;
  padding:1px 6px;font-size:10.5px;border-radius:5px}
.dragpanel.cpw .cond-node-row .mod-select{padding-right:18px;background-position:right 6px center}
/* ⚠️ 이 앱은 <select class="mod-select"> 를 자체 드롭다운(.custom-select.custom-mod-select, width:100%)으로
   바꿔 끼운다 - 화면에 보이는 것은 그쪽이라 폭·높이도 그쪽에 준다(native 만 줄이면 칸마다 줄을 바꾼다). */
.dragpanel.cpw .cond-node-row .custom-select{flex:0 1 auto;width:auto;min-width:0}
.dragpanel.cpw .cond-node-row .custom-select .custom-select-button{height:22px;padding:0 7px;gap:6px;font-size:10.5px;border-radius:5px}
.dragpanel.cpw .cond-node-row .cond-in-tag{flex:1 1 110px;min-width:90px}
.dragpanel.cpw .cond-node-row .cond-in-num{flex:0 0 46px;width:46px}
.dragpanel.cpw .cond-grow{flex:1 1 auto}
.dragpanel.cpw .cond-delete-node-btn{flex:0 0 22px;width:22px;min-width:22px;padding:0}
.dragpanel.cpw .cond-inline-check{min-height:22px;padding:0;gap:4px}
.dragpanel.cpw .cond-mini{flex:0 0 auto;color:var(--text-muted);font-size:10px}

/* 동작 */
.dragpanel.cpw .cond-action-card{flex:0 0 auto}
.dragpanel.cpw .cond-tag-editor{gap:3px}
.dragpanel.cpw .cond-tag-editor > label{font-size:10px;font-weight:600;color:var(--text-muted)}
.dragpanel.cpw .cond-chip-list,.dragpanel.cpw .cond-action-pane .cond-action-card .cond-chip-list{min-height:30px;gap:4px;padding:4px}
.dragpanel.cpw .cond-action-pane .cond-action-card .cond-tag-editor{flex:0 0 auto}
.dragpanel.cpw .cond-chip{padding:1px 6px;font-size:10.5px;gap:4px}
.dragpanel.cpw .cond-chip-input{min-width:90px;font-size:11px;line-height:20px}
.dragpanel.cpw .cond-dsl-viewer{flex:0 0 auto;gap:3px;padding:4px 6px;border-radius:5px}
.dragpanel.cpw .cond-dsl-viewer textarea{min-height:34px;height:40px;padding:4px 7px;font-size:11px;line-height:1.45}
.dragpanel.cpw .cond-dsl-viewer.has-sim textarea{height:170px}
.dragpanel.cpw .cond-raw-editor{min-height:90px}

/* 아래 단추 줄 */
.dragpanel.cpw .cond-bottom-actions{width:auto;margin:0;display:flex;gap:4px;justify-content:flex-end}
.dragpanel.cpw .cond-bottom-actions .mod-action-btn{flex:0 0 auto;padding:0 12px}
.dragpanel.cpw .cond-bottom-actions [data-cond-action="reload-state"]{margin-right:auto}

/* ── Legacy DSL ── */
.dragpanel.cpw .cond-rules-section{gap:3px;min-height:90px}
.dragpanel.cpw .cond-rules-head .mod-section-label{padding-bottom:0}
.dragpanel.cpw .cond-rules-wrap,.dragpanel.cpw .cond-rules-section .cond-rules-wrap{min-height:80px}
.dragpanel.cpw .cond-rules-input{min-height:80px}
.dragpanel.cpw .cond-foot-row{flex:0 0 auto;display:flex;align-items:flex-start;gap:8px}
.dragpanel.cpw .cond-foot-row > div:first-child{flex:1 1 auto;min-width:0}
.dragpanel.cpw .cond-foot-row .mod-section-label{padding:3px 0 0}
.dragpanel.cpw .cond-foot-row .mod-start{flex:0 0 auto;height:22px;padding:0 12px;font-size:10.5px;border-radius:5px}

/* ── 실행 기록(접힘) ── */
.dragpanel.cpw .cond-log-fold{flex:0 0 auto;display:flex;flex-direction:column;border-top:1px solid rgba(255,255,255,0.06);margin:0 -8px -7px}
.dragpanel.cpw .cond-log-head{display:flex;align-items:center;gap:6px;width:100%;height:22px;padding:0 9px;border:none;
  background:rgba(255,255,255,0.025);color:var(--text-muted);font-size:10px;font-weight:700;cursor:pointer;text-align:left}
.dragpanel.cpw .cond-log-head:hover{color:var(--text-primary);background:rgba(255,255,255,0.05)}
.dragpanel.cpw .cond-log-caret{width:0;height:0;border-left:4px solid currentColor;border-top:3.5px solid transparent;
  border-bottom:3.5px solid transparent;transition:transform .12s}
.dragpanel.cpw .cond-log-fold.is-open .cond-log-caret{transform:rotate(90deg)}
.dragpanel.cpw .cond-log-name{flex:0 0 auto}
.dragpanel.cpw .cond-log-meta{flex:1 1 auto;min-width:0;font-family:var(--font-mono);font-weight:500;color:var(--text-dim);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dragpanel.cpw .cond-log-fold .mod-log-viewer{margin:0 8px 7px;min-height:40px;max-height:140px}
.dragpanel.cpw .cond-log-fold .mod-log-viewer[hidden]{display:none}

/* ── 대화상자(새 프리셋 · 덮어쓰기): 창 본문을 덮는다 ── */
.dragpanel.cpw .cond-preset-dialog-backdrop{padding:12px}
.dragpanel.cpw .cond-preset-dialog{gap:8px;padding:11px 12px}
.dragpanel.cpw .cond-preset-dialog-title{font-size:13px}
.dragpanel.cpw .cond-preset-dialog-close{width:24px;height:24px}
.dragpanel.cpw .cond-preset-dialog-label{font-size:10.5px}
.dragpanel.cpw .cond-preset-mode-option{min-height:28px;padding:4px 8px;font-size:11px}
.dragpanel.cpw .cond-preset-dialog-actions button{min-height:26px;font-size:11px}
.dragpanel.cpw .cond-preset-dialog-body{font-size:11px}
.dragpanel.cpw .mod-input,.dragpanel.cpw .mod-select{height:24px;padding-top:2px;padding-bottom:2px;font-size:11px}

/* ── 창이 좁으면(창 폭 기준) 세로로 쌓는다: 규칙 목록 → 조건 → 동작 ── */
@container cpw (max-width: 540px){
  .dragpanel.cpw .cond-v2-grid{grid-template-columns:minmax(0,1fr);grid-template-rows:fit-content(28%) minmax(80px,1fr) fit-content(45%)}
  .dragpanel.cpw .cond-rule-pane{grid-column:1;grid-row:1}
  .dragpanel.cpw .cond-condition-pane{grid-column:1;grid-row:2}
  .dragpanel.cpw .cond-action-pane{grid-column:1;grid-row:3}
}

/* ── 프리셋 동반 창 ── */
.dragpanel.cppw{border-color:rgba(245,220,138,0.35)}
.dragpanel.cppw .dragpanel-head{background:rgba(245,220,138,0.07)}
.dragpanel.cppw .dragpanel-body{padding:0;gap:0;overflow:hidden;background:var(--bg-surface)}
.dragpanel.cppw .cond-preset-host{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.dragpanel.cppw .cond-preset-root{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;gap:0}
/* ⚠️ style.css 의 옛 팝오버 규칙 .cond-root:not(.cond-v2-editor) .cond-preset-pane{display:none;position:absolute}
   과 굵기가 같으면 파일 순서로만 이긴다 - 뿌리 이름을 하나 더 넣어 확실히 이긴다. */
.dragpanel.cppw .cond-preset-root .cond-preset-pane{display:flex;position:static;flex:1 1 auto;min-height:0;width:auto;max-height:none;
  box-shadow:none;border:none;border-radius:0;padding:7px;gap:6px;background:transparent}
.dragpanel.cppw .cond-preset-list{flex:1 1 auto;min-height:0;overflow-y:auto;gap:3px;padding:3px;background:rgba(0,0,0,0.24);border-radius:6px}
.dragpanel.cppw .cond-preset-row{display:flex;align-items:stretch;gap:3px}
.dragpanel.cppw .cond-preset-item{flex:1 1 auto;min-width:0;min-height:26px;padding:3px 8px;gap:6px}
.dragpanel.cppw .cond-preset-item span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px}
.dragpanel.cppw .cond-preset-del{flex:0 0 22px;border:1px solid transparent;border-radius:5px;background:transparent;
  color:var(--text-muted);font-size:13px;line-height:1;cursor:pointer}
.dragpanel.cppw .cond-preset-del:hover{border-color:rgba(240,64,64,0.5);color:#ff8a8a}
.dragpanel.cppw .cond-preset-save-row{display:flex;gap:4px}
.dragpanel.cppw .cond-preset-save-row .mod-input{flex:1 1 auto;min-width:0;height:24px;padding:2px 8px;font-size:11px}
.dragpanel.cppw .cond-preset-save-row button,.dragpanel.cppw .cond-preset-new{flex:0 0 auto;white-space:nowrap;height:24px;padding:0 10px;
  border:1px solid var(--border-dim);border-radius:5px;background:var(--bg-elevated);color:var(--text-primary);
  font-family:var(--font-display);font-size:10.5px;font-weight:700;cursor:pointer}
.dragpanel.cppw .cond-preset-save-row button:hover,.dragpanel.cppw .cond-preset-new:hover{border-color:var(--accent-blue)}
.dragpanel.cppw .cond-empty{padding:8px;font-size:10.5px}

/* ── Test Rules / Simulation 동반 창 ── */
.dragpanel.cpsw{border-color:rgba(120,190,150,0.42)}
.dragpanel.cpsw .dragpanel-head{background:rgba(120,190,150,0.09)}
.dragpanel.cpsw .dragpanel-body{padding:0;gap:0;overflow:auto;background:var(--bg-surface)}
.dragpanel.cpsw .cond-sim-host{padding:8px 9px 10px}
.dragpanel.cpsw .cond-sim-root{display:flex;flex-direction:column;gap:8px}
.dragpanel.cpsw .csim-head{display:flex;align-items:center;gap:7px}
.dragpanel.cpsw .csim-status{font-size:12px;font-weight:800;color:var(--text-primary)}
.dragpanel.cpsw .csim-status.ok{color:#9ddfa8}
.dragpanel.cpsw .csim-status.none{color:var(--text-muted)}
.dragpanel.cpsw .csim-status.fail{color:#ff9a8a}
.dragpanel.cpsw .csim-info{color:var(--text-muted);font-size:11px;cursor:help}
.dragpanel.cpsw .csim-rerun{margin-left:auto;height:22px;padding:0 10px;border:1px solid var(--border-dim);border-radius:5px;
  background:var(--bg-elevated);color:var(--text-primary);font-size:10.5px;font-weight:700;cursor:pointer}
.dragpanel.cpsw .csim-rerun:hover{border-color:var(--accent-blue)}
.dragpanel.cpsw .csim-flag{padding:4px 8px;border-radius:5px;font-size:10.5px;color:var(--text-muted);background:rgba(255,255,255,0.04)}
.dragpanel.cpsw .csim-flag.stale{color:#ffcc80;background:rgba(255,183,77,0.10);border:1px solid rgba(255,183,77,0.35)}
.dragpanel.cpsw .csim-error{padding:6px 8px;border-radius:5px;font-size:11px;color:#ffb4a8;background:rgba(240,64,64,0.10)}
.dragpanel.cpsw .csim-empty{padding:10px;border:1px dashed var(--border-dim);border-radius:6px;color:var(--text-muted);font-size:11px;line-height:1.5}
.dragpanel.cpsw .csim-sec{display:flex;flex-direction:column;gap:4px}
.dragpanel.cpsw .csim-label{font-family:var(--font-mono);font-size:9.5px;letter-spacing:.06em;color:var(--text-dim)}
.dragpanel.cpsw .csim-row{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.dragpanel.cpsw .csim-sample{padding:1px 7px;border-radius:999px;font-size:10.5px;color:#b2dfdb;
  border:1px solid rgba(178,223,219,0.28);background:rgba(178,223,219,0.08)}
.dragpanel.cpsw .csim-step{display:flex;flex-direction:column;gap:3px;padding:5px 7px;border-radius:6px;
  border:1px solid rgba(120,128,170,0.22);background:rgba(14,14,22,0.7)}
.dragpanel.cpsw .csim-step-head{display:flex;align-items:center;gap:6px;min-width:0}
.dragpanel.cpsw .csim-idx{flex:0 0 auto;min-width:16px;height:16px;border-radius:4px;background:rgba(92,150,255,0.18);
  color:#9ecbff;font-size:9.5px;font-weight:800;display:inline-flex;align-items:center;justify-content:center}
.dragpanel.cpsw .csim-pass{font-size:9.5px;color:var(--text-muted)}
.dragpanel.cpsw .csim-cond{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:var(--text-primary)}
.dragpanel.cpsw code.csim-cond{font-family:var(--font-mono);font-size:10.5px;padding:0 5px;border-radius:4px;background:rgba(0,0,0,0.3)}
.dragpanel.cpsw .csim-cond.is-always{color:var(--text-muted);font-style:italic}
.dragpanel.cpsw .csim-arrow{color:var(--text-dim)}
.dragpanel.cpsw .csim-step-body{display:flex;flex-direction:column;gap:3px;padding-left:22px}
.dragpanel.cpsw .csim-change{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
.dragpanel.cpsw .csim-where{font-size:10px;font-weight:700;color:var(--text-muted);margin-right:2px}
.dragpanel.cpsw .csim-chip{padding:1px 6px;border-radius:4px;font-size:10.5px;color:var(--text-primary)}
.dragpanel.cpsw .csim-chip.add{border:1px solid rgba(76,175,80,0.35);background:rgba(76,175,80,0.18)}
.dragpanel.cpsw .csim-chip.same{border:1px dashed rgba(255,255,255,0.18);color:var(--text-muted)}
.dragpanel.cpsw .csim-chip.del{border:1px solid rgba(240,64,64,0.35);background:rgba(240,64,64,0.14);text-decoration:line-through}
.dragpanel.cpsw .csim-note{font-size:10.5px;color:var(--text-muted)}
.dragpanel.cpsw .csim-toggle{align-self:flex-start;border:none;background:transparent;padding:0;color:var(--text-muted);
  font-size:10.5px;font-weight:700;cursor:pointer}
.dragpanel.cpsw .csim-toggle:hover{color:var(--text-primary)}
.dragpanel.cpsw .csim-full{padding:6px 8px;border-radius:5px;background:rgba(7,7,12,0.96);font-family:var(--font-editor);
  font-size:11px;line-height:1.5;color:var(--text-muted);word-break:break-word;user-select:text}
.dragpanel.cpsw .csim-full mark{background:rgba(76,175,80,0.28);color:var(--text-primary);border-radius:3px;padding:0 2px}
`;
