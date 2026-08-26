// 좌표 지정 스테이지 — 그림 위에 마커를 놓고 끄는 공용 엔진.
//
// 캐릭터 퀵 패널의 POS 화면(`characterQuickPanel.mjs`)이 쓰던 규칙을 뽑아낸 것이다.
// V5 인페인트 캔버스도 같은 몸짓이어야 해서(사용자 지정 2026-08-26) 두 번 짜지 않는다.
//
// ⚠️ 여기 담긴 세 규칙은 전부 **실측으로 얻은 것**이다. 다시 짜지 마라:
//
//  1) 드래그 중에는 다시 그리지 않는다. 끌고 있던 노드가 교체되면 참조가 끊겨
//     드래그가 통째로 무시된다.
//  2) 놓는 순간에만 저장한다. 끌 때마다 보내면 한 번의 드래그가 수십 번의 왕복이 된다.
//  3) 저장 직전에 화면을 **먼저** 새 값으로 맞춘다. 서버 echo 까지 한 박자가 있는데,
//     그 사이에 무엇이든 다시 그리면 마커가 옛 자리로 튀었다가 돌아온다.
//
// 좌표계: 바깥에는 늘 **콘텐츠 픽셀**(캔버스/이미지 실제 크기)로 주고받는다. 화면이
// 줄어 있어도(`scale`) 호출부는 그것을 몰라도 된다.

export const GRID_STEP = 64;

/** 격자 SVG. `w`/`h` 는 콘텐츠 픽셀. */
export function gridSvg(w, h, {step = GRID_STEP, className = 'pos-grid'} = {}) {
  if (!(w > 0) || !(h > 0)) return '';
  const id = `posGrid${Math.round(w)}x${Math.round(h)}`;
  const cx = w / 2;
  const cy = h / 2;
  return `<svg class="${className}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">`
    + `<defs><pattern id="${id}" width="${step}" height="${step}" patternUnits="userSpaceOnUse">`
    + `<path d="M ${step} 0 L 0 0 0 ${step}" class="pos-grid-line"/>`
    + `</pattern></defs>`
    + `<rect width="${w}" height="${h}" fill="url(#${id})"/>`
    + `<line x1="${cx}" y1="0" x2="${cx}" y2="${h}" class="pos-grid-mid"/>`
    + `<line x1="0" y1="${cy}" x2="${w}" y2="${cy}" class="pos-grid-mid"/>`
    + `</svg>`;
}

/** 포인터 이벤트를 콘텐츠 픽셀 좌표로. 스테이지 밖으로 나가도 안쪽으로 가둔다. */
export function pointToContent(event, stageEl, contentW, contentH) {
  const rect = stageEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return {x: 0, y: 0};
  const ratioX = (event.clientX - rect.left) / rect.width;
  const ratioY = (event.clientY - rect.top) / rect.height;
  return {
    x: Math.round(Math.min(1, Math.max(0, ratioX)) * contentW),
    y: Math.round(Math.min(1, Math.max(0, ratioY)) * contentH),
  };
}

/** 콘텐츠 픽셀 -> 스테이지 안에서의 % (마커/손잡이 배치용). */
export function contentToPercent(x, y, contentW, contentH) {
  return {
    left: `${(contentW ? (x / contentW) : 0) * 100}%`,
    top: `${(contentH ? (y / contentH) : 0) * 100}%`,
  };
}

/**
 * 스테이지를 만든다. 반환값의 `beginDrag` 를 pointerdown 에서 부르면 된다.
 *
 * @param {object} o
 * @param {HTMLElement|(() => HTMLElement)} o.stage  좌표를 재는 기준 요소, 또는 그것을
 *        돌려주는 함수. 매 렌더마다 노드가 새로 만들어지는 화면은 **함수로** 넘겨야
 *        한다 - 고정 노드를 쥐고 있으면 다시 그린 뒤 옛 노드를 재게 된다.
 * @param {() => {w:number,h:number}} o.getContentSize  콘텐츠 픽셀 크기
 * @param {(payload:{x:number,y:number,key:string}) => void} o.onCommit  놓을 때 한 번
 * @param {() => void} [o.onDragStart]
 * @param {() => void} [o.onDragEnd]
 */
export function createPosStage({stage, getContentSize, onCommit, onDragStart, onDragEnd}) {
  let dragging = false;
  const stageEl = () => (typeof stage === 'function' ? stage() : stage);

  /** 드래그 중인가. 호출부는 이 값이 true 인 동안 renderStage 를 **막아야** 한다(규칙 1). */
  function isDragging() {
    return dragging;
  }

  /**
   * @param {PointerEvent} event
   * @param {HTMLElement} node   끌리는 요소. 위치는 이 함수가 직접 갱신한다.
   * @param {string} key         onCommit 에 그대로 넘어가는 식별자
   * @param {(x:number,y:number) => void} [place]  기본 배치가 안 맞을 때 쓰는 훅
   */
  function beginDrag(event, node, key, place) {
    const host = stageEl();
    if (!host || !node) return;
    event.preventDefault();
    const size = getContentSize() || {w: 0, h: 0};
    let last = null;

    const put = (x, y) => {
      if (place) { place(x, y); return; }
      const pos = contentToPercent(x, y, size.w, size.h);
      node.style.left = pos.left;
      node.style.top = pos.top;
    };

    const move = (ev) => {
      last = pointToContent(ev, host, size.w, size.h);
      put(last.x, last.y);
    };

    const up = () => {
      dragging = false;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
      node.classList.remove('is-drag');
      // ⚠️ **커밋이 먼저다.** `onDragEnd` 가 대개 재렌더인데, 그게 먼저 돌면 끌던
      //    노드가 교체되면서 거기 붙여 둔 값(dataset 등)이 사라진다 - 실측: 베이스
      //    오프셋이 통째로 안 실렸다. 화면은 드래그 중에 이미 새 값이다(규칙 3).
      if (last) onCommit?.({x: last.x, y: last.y, key});
      onDragEnd?.();
    };

    dragging = true;
    node.classList.add('is-drag');
    onDragStart?.();
    // 누른 자리로 곧장 옮긴다 - 손잡이를 잡자마자 튀지 않게 첫 좌표를 여기서 잡는다.
    move(event);
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
  }

  return {beginDrag, isDragging};
}
