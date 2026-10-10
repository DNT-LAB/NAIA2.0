/** 메인 프롬프트 칸의 [prefix] [postfix] 꼬리표 - Prompt Engineering 의 두 칸을 **작은 떠 있는 창 둘**로 연다.
 *
 *  사용자 지시(2026-10-10): 불편은 "이미지를 보면서 동시에 prefix / postfix 수정이 쉽지 않다 · 고치려면
 *  매번 열어 줘야 한다" 는 것. 메인 칸 모서리에 **매우 작은** 단추 둘을 두고, 누르면 끌어 옮길 수 있는
 *  창으로 편다.
 *
 *      ┌ prompt ───────────────────┐
 *      │▾prefix                    │
 *      │┌⠿ prefix ─────── 358자 ×┐│   ← 처음엔 칸 **안쪽 위** (합쳐진 글의 prefix 가 있는 자리)
 *      ││ 1.2::artist:kim eb ::, …││
 *      │└───────────────────────◢┘│
 *      │  #랜덤프롬프트 …           │
 *      │┌⠿ postfix ────── 318자 ×┐│   ← 처음엔 칸 **안쪽 아래**
 *      ││ year 2025, …            ││
 *      │└───────────────────────◢┘│
 *      │▾postfix                   │
 *      ├ Estimated Tokens : 250 ───┤
 *
 *  사용자 지정(같은 날 · 목업을 보고):
 *   · **창은 둘이다** - prefix 와 postfix 를 따로 열고 따로 옮긴다("분리하여 각각 상 하단에 배치").
 *   · **작게** - 머리줄 한 줄(18px)에 칸 이름 · 글자 수 · 닫기. 리모컨 창처럼 제목 줄 + 칸 이름 줄을 따로
 *     쓰지 않는다("헤더가 두껍고, 라벨 영역을 추가로 소모"). 접기 단추도 없다 - 꼬리표가 열고 닫는다.
 *   · **처음 자리는 메인 칸 안쪽 위 / 아래**, 불편하면 끌어 옮긴다. **옮긴 자리는 기억한다.**
 *   · 리모컨의 PE 창은 지금 모양 그대로 둔다.
 *
 *  ⚠️ **판은 리모컨의 것(`peQuickEdit`)을 그대로 쓴다** - 읽기 · 쓰기 · 프리셋 도장 · 강조 · 자동완성 · 칸을
 *     벗어날 때 저장. 규칙을 여기서 다시 쓰지 않는다. 그 판은 prefix · postfix 두 줄을 늘 함께 만들므로,
 *     창마다 **제 줄만 보이게** 가리고(style.css `.pefloat[data-pe-field]`) 줄 머리(칸 이름 단추)는 숨긴다 -
 *     그 일은 창의 머리줄이 한다. 판의 파일은 건드리지 않았다.
 *  ⚠️ 판은 Esc 에 "저장하고 접는다". 줄 머리가 안 보이는 창에서 줄이 접히면 **빈 창**이 남는다 -
 *     그래서 줄이 접히면 창도 닫는다("창이 떠 있으면 칸은 펴져 있다"). Esc = 저장하고 닫기.
 *  ⚠️ 자리는 **직접** 기억한다(`naia.pe.mainQuick`). 공용 창 뼈대(`draggablePanel`)에 기억을 맡기면
 *     "이번 실행에 처음 여는 창은 왼쪽 패널과 결과 탭 사이에 연다" 는 규칙이 먼저 걸려, 정해 준 첫 자리도
 *     기억한 자리도 못 쓴다. 그래서 뼈대에는 열쇠를 주지 않고, 끌기가 끝났다는 신호만 받아 적는다.
 *  ⚠️ 고친 글은 **다음 Random 부터** 나간다. 메인 칸의 프롬프트는 이미 조립된 글이다(모듈에서 고칠 때와 같다).
 *  ⚠️ 꼬리표는 글자를 가리지 않는 자리에 선다 - 입력칸의 위 여백(14px)과, 토큰 줄 바로 위의 빈 띠(14px:
 *     입력칸 아래 여백 48 / 66px 에서 토큰 줄 34 / 52px 을 뺀 나머지). 그 수가 바뀌면 style.css 의
 *     `.pe-mini` 도 같이 고쳐야 한다.
 */

const FIELDS = [
  {key: 'pre_prompt', label: 'prefix', where: 'top',
    tip: 'Prefix Prompt 창을 엽니다 (프롬프트 엔지니어링과 같은 값 · 다음 Random 부터 적용)'},
  {key: 'post_prompt', label: 'postfix', where: 'bottom',
    tip: 'Postfix Prompt 창을 엽니다 (프롬프트 엔지니어링과 같은 값 · 다음 Random 부터 적용)'},
];
const POSITION_KEY = 'naia.pe.mainQuick';
const WINDOW_HEIGHT = 130;
const TAG_BAND = 15;            // 꼬리표 띠(14px) + 틈 - 창이 꼬리표를 덮지 않게
const INSET = 4;                // 메인 칸 안쪽 가장자리와의 틈

export function createMainPeQuick({
  document: doc,
  window: win,
  storage = null,                // 자리를 기억할 곳(localStorage)
  host,                          // 메인 프롬프트의 `.prompt-highlight-wrap`
  loadPeQuickEdit,               // () => Promise<createPeQuickEdit>
  loadDraggablePanel,            // () => Promise<createDraggablePanel>
  escHtml,
  showToast = () => {},
  getField = () => '',           // (key) => string
  setField = () => {},           // (key, text, seenPreset) => void   ⚠️ 도장은 이 안에서 찍힌다
  getPreset = () => '',
  requestState = () => {},
  attachHighlight = null,
  bindAssist = null,
} = {}) {
  if (!doc || !host) return null;

  function readPositions() {
    try {
      const parsed = JSON.parse(storage?.getItem(POSITION_KEY) || 'null');
      return (parsed && typeof parsed === 'object') ? parsed : {};
    } catch (_) { return {}; }
  }
  function writePosition(key, x, y) {
    try {
      const all = readPositions();
      all[key] = {x: Math.round(x), y: Math.round(y)};
      storage?.setItem(POSITION_KEY, JSON.stringify(all));
    } catch (_) { /* 못 외우는 것뿐이다 */ }
  }

  /** 옮긴 적이 없을 때의 자리 - 메인 칸 안쪽, prefix 는 위 꼬리표 바로 아래 · postfix 는 아래 꼬리표 바로 위. */
  function homeSpot(field, height) {
    const box = host.getBoundingClientRect();
    const footer = host.querySelector('.prompt-token-footer')?.getBoundingClientRect();
    const floor = footer && footer.height > 0 ? footer.top : box.bottom;
    return {
      x: box.left + INSET,
      y: field.where === 'top' ? box.top + TAG_BAND : floor - TAG_BAND - height,
    };
  }

  const slots = new Map();       // key -> {field, btn, quick, panel, count, opening}
  FIELDS.forEach(field => {
    const btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = `pe-mini pe-mini--${field.where}`;
    btn.dataset.peField = field.key;
    btn.title = field.tip;
    btn.setAttribute('aria-pressed', 'false');
    btn.innerHTML = `<span class="pe-mini-caret">▸</span>${escHtml(field.label)}`;
    btn.addEventListener('click', () => { void toggle(field.key); });
    host.appendChild(btn);
    slots.set(field.key, {field, btn, quick: null, panel: null, count: null, opening: null});
  });

  const textOf = slot => slot.quick?.el.querySelector(`[data-peq-key="${slot.field.key}"] .peq-text`) || null;
  const boxOf = slot => slot.quick?.el.querySelector(`[data-peq-key="${slot.field.key}"] .peq-box`) || null;

  function paint(slot) {
    const on = !!(slot.panel && slot.panel.isOpen());
    slot.btn.classList.toggle('is-on', on);
    slot.btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    slot.btn.querySelector('.pe-mini-caret').textContent = on ? '▾' : '▸';
  }

  /** 머리줄의 글자 수 - 창에 지금 떠 있는 글을 센다(안 떠 있으면 서버 값). */
  function paintCount(slot) {
    if (!slot.count) return;
    const text = textOf(slot);
    const length = String(text ? text.value : getField(slot.field.key) || '').trim().length;
    slot.count.textContent = length ? `${length}자` : '비어 있음';
  }

  async function ensure(slot) {
    if (slot.panel) return slot.panel;
    if (slot.opening) return slot.opening;
    slot.opening = (async () => {
      const [createPeQuickEdit, createDraggablePanel] = await Promise.all([loadPeQuickEdit(), loadDraggablePanel()]);
      const quick = createPeQuickEdit({
        document: doc, escHtml, showToast,
        attachHighlight, bindAssist,
        getField, setField, getPreset, requestState,
      });
      const width = Math.max(240, Math.round(host.getBoundingClientRect().width) - INSET * 2);
      const panel = createDraggablePanel({
        document: doc, window: win,
        variant: 'pewin pefloat',
        title: slot.field.label,
        // ⚠️ 기억 열쇠를 주지 않는다 - 머리말의 '자리는 직접 기억한다' 참조.
        width, height: WINDOW_HEIGHT, minWidth: 200, maxWidth: 720, minHeight: 56,
        resizable: true, collapsible: false,
        escHtml,
        onOpen: () => paint(slot),
        // 펼친 채 닫으면 마지막 편집이 날아간다 - 칸을 벗어난 것과 같이 친다.
        onClose: () => { quick.flush(); paint(slot); },
      });
      panel.el.dataset.peField = slot.field.key;
      const count = doc.createElement('span');
      count.className = 'pefloat-count';
      panel.slot.appendChild(count);
      panel.body.appendChild(quick.el);
      slot.quick = quick;
      slot.panel = panel;
      slot.count = count;
      // 끌기(와 크기 조절)가 끝났다 - 그 자리를 적는다.
      panel.el.addEventListener('dragpanel-move-end', () => {
        const rect = panel.el.getBoundingClientRect();
        writePosition(slot.field.key, rect.left, rect.top);
      });
      quick.el.addEventListener('input', () => paintCount(slot));
      quick.el.addEventListener('keydown', event => {
        // Alt+Enter(Random)는 문서의 단축키다 - 여기서 치던 글을 **먼저** 보내야 그 Random 이 새 글을 쓴다.
        // 저장과 Random 은 같은 소켓으로 차례대로 나간다. (Ctrl+Enter 는 판이 '저장' 으로 쓴다 - 그대로 둔다.)
        if (event.key === 'Enter' && event.altKey && !event.ctrlKey && !event.isComposing) quick.flush();
      }, true);
      // 판이 Esc 로 줄을 접었으면 창도 닫는다 - 줄 머리가 없는 창에 빈 상자만 남지 않게(머리말).
      quick.el.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        Promise.resolve().then(() => {
          const box = boxOf(slot);
          if (panel.isOpen() && box && box.hidden) panel.close();
        });
      });
      return panel;
    })();
    try { return await slot.opening; } finally { slot.opening = null; }
  }

  /** 꼬리표 = 그 칸의 창을 열고 닫는다. 두 창은 서로 상관없이 뜬다. */
  async function toggle(key) {
    const slot = slots.get(key);
    if (!slot) return;
    let panel;
    try { panel = await ensure(slot); } catch (error) {
      showToast(`${slot.field.label} 창을 열지 못했습니다 — ${error?.message || error}`, 'error');
      return;
    }
    if (panel.isOpen()) { panel.close(); return; }
    panel.open();
    // 옮긴 적이 있으면 그 자리, 없으면 메인 칸 안쪽의 제 자리(칸 크기가 바뀌었을 수 있어 열 때마다 다시 잰다).
    const saved = readPositions()[key];
    const spot = (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y))
      ? saved
      : homeSpot(slot.field, panel.el.getBoundingClientRect().height || WINDOW_HEIGHT);
    panel.moveTo(spot.x, spot.y, {persist: false});
    slot.quick.sync();
    slot.quick.openField(key);
    paintCount(slot);
    paint(slot);
  }

  return {
    /** PE 상태가 바뀌었다(프리셋 전환 · 다른 창의 편집). 치는 중인 칸은 판이 알아서 지킨다. */
    sync() {
      slots.forEach(slot => {
        try { slot.quick?.sync(); paintCount(slot); } catch (_) {}
      });
    },
    toggle,
    isOpen: key => !!(slots.get(key)?.panel?.isOpen()),
  };
}
