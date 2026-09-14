/** Remote 컨트롤러 — 화면 어디에나 놓고 쓰는 떠 있는 조작판.
 *
 *  Web-Remote(폰으로 여는 원격 화면)와는 **다른 것**이다. 이쪽은 같은 화면 안에서
 *  손이 닿는 자리에 조작판 하나를 띄워 두는 것 - 리모컨에 가깝다(사용자 지정
 *  2026-09-14). 탭을 옮겨 다녀도 따라오고, 사용자가 정한 자리에 그대로 있는다.
 *
 *  여기서 하는 일은 **껍데기**뿐이다. 끄는 힘·자리 기억·앞뒤 순서·접기·크기 조절은
 *  전부 `draggablePanel.mjs` 가 맡는다. 조작 항목(무엇을 리모컨에 올릴지)은 다음
 *  단계에서 `setBody()` / `mountSlot()` 으로 얹는다.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260914-rctl1';

export function createRemoteController({
  document: doc,
  window: win = (typeof window !== 'undefined' ? window : null),
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  showToast = () => {},
  escHtml = value => String(value ?? ''),
  onOpenChange = null,
} = {}) {
  const panel = createDraggablePanel({
    document: doc,
    window: win,
    storage,
    id: 'remoteController',
    variant: 'rctl',
    title: 'Remote',
    storageKey: 'remote-controller',
    width: 248,
    minWidth: 200,
    maxWidth: 420,
    minHeight: 120,
    resizable: true,
    collapsible: true,
    closable: true,
    // 처음 열리는 자리 - 오른쪽 가장자리에서 24px, 위에서 조금 내려온 곳.
    initial: {right: 24, y: 132},
    escHtml,
    onOpen: () => { if (typeof onOpenChange === 'function') onOpenChange(true); },
    onClose: () => { if (typeof onOpenChange === 'function') onOpenChange(false); },
  });

  // 아직 조작 항목이 없다 - 자리만 잡아 둔다. 다음 단계에서 setBody() 로 갈아 끼운다.
  panel.body.innerHTML = `
    <p class="rctl-placeholder">조작 항목은 아직 배선하지 않았습니다.<br>
      머리줄을 잡아 원하는 자리에 놓아 보세요.</p>
    <div class="rctl-foot">
      <button type="button" class="rctl-reset">위치 초기화</button>
    </div>
  `;
  panel.body.querySelector('.rctl-reset')?.addEventListener('click', () => {
    panel.resetGeometry();
    showToast('Remote 컨트롤러 위치를 초기화했습니다.', 'info');
  });

  return {
    ...panel,
    /** 본문을 통째로 갈아 끼운다(다음 단계의 배선 지점). */
    setBody(node) {
      panel.body.innerHTML = '';
      if (typeof node === 'string') panel.body.innerHTML = node;
      else if (node) panel.body.appendChild(node);
      return panel.body;
    },
    /** 머리줄 오른쪽(제목과 [—][×] 사이)에 작은 표시를 끼운다. */
    mountSlot(node) {
      panel.slot.innerHTML = '';
      if (typeof node === 'string') panel.slot.innerHTML = node;
      else if (node) panel.slot.appendChild(node);
      return panel.slot;
    },
  };
}
